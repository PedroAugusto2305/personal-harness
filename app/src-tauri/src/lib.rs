//! Moldura nativa do Harness: abre a janela e cuida do núcleo em Python.
//!
//! O núcleo (`core/`) é dono dos terminais dos agentes. Em desenvolvimento ele é
//! iniciado com `uv run` a partir da pasta do repositório; se `HARNESS_CORE_URL` e
//! `HARNESS_TOKEN` já vierem no ambiente, o app só se conecta a um núcleo existente.

use std::io::Read;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

mod browser;

const DEFAULT_PORT: u16 = 47830;
/// Janela da captura rápida (⌥Espaço), a mesma tela React com `?captura=1`.
const CAPTURE: &str = "captura";

fn capture_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::ALT), Code::Space)
}

/// Abre a caixinha de captura por cima de qualquer app (ou fecha, se já estiver na frente).
fn toggle_capture(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(CAPTURE) {
        if window.is_visible().unwrap_or(false) && window.is_focused().unwrap_or(false) {
            let _ = window.hide();
        } else {
            let _ = window.center();
            let _ = window.show();
            let _ = window.set_focus();
            let _ = window.emit("captura:abrir", ());
        }
        return;
    }
    let built = WebviewWindowBuilder::new(app, CAPTURE, WebviewUrl::App("index.html?captura=1".into()))
        .title("MÊTIS · captura")
        .inner_size(640.0, 156.0)
        .resizable(false)
        .decorations(false)
        .always_on_top(true)
        .visible_on_all_workspaces(true)
        .skip_taskbar(true)
        .center()
        .focused(true)
        .build();
    if let Err(error) = built {
        eprintln!("metis: não consegui abrir a captura: {error}");
    }
}

/// O ⌘K da janela principal abre a mesma caixinha.
#[tauri::command]
fn capture_open(app: AppHandle) {
    toggle_capture(&app);
}

#[derive(Clone, serde::Serialize)]
struct CoreInfo {
    url: String,
    token: String,
    managed: bool,
}

struct CoreState {
    info: CoreInfo,
    child: Mutex<Option<Child>>,
    /// Onde o núcleo escreve o endereço real (ele troca de porta se a preferida estiver ocupada).
    runtime_file: Option<PathBuf>,
}

/// Token novo a cada execução, lido de /dev/urandom.
fn random_token() -> String {
    let mut bytes = [0u8; 24];
    if let Ok(mut source) = std::fs::File::open("/dev/urandom") {
        let _ = source.read_exact(&mut bytes);
    }
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// A porta de sempre, se estiver livre; senão uma qualquer que o sistema der.
/// Um núcleo esquecido segurando a 47830 não pode deixar o app sem núcleo.
fn free_port(preferred: u16) -> u16 {
    if TcpListener::bind(("127.0.0.1", preferred)).is_ok() {
        return preferred;
    }
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(preferred)
}

fn core_dir() -> PathBuf {
    std::env::var("HARNESS_CORE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../core"))
}

fn start_core() -> CoreState {
    if let (Ok(url), Ok(token)) = (std::env::var("HARNESS_CORE_URL"), std::env::var("HARNESS_TOKEN")) {
        return CoreState { info: CoreInfo { url, token, managed: false }, child: Mutex::new(None), runtime_file: None };
    }
    let preferred = std::env::var("HARNESS_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(DEFAULT_PORT);
    let port = free_port(preferred);
    let token = random_token();
    let runtime_file = std::env::temp_dir().join(format!("metis-core-{}.json", std::process::id()));
    let _ = std::fs::remove_file(&runtime_file);
    let child = Command::new("uv")
        .args(["run", "--quiet", "--project"])
        .arg(core_dir())
        .arg("harness-core")
        .env("HARNESS_PORT", port.to_string())
        .env("HARNESS_TOKEN", &token)
        // O núcleo se encerra sozinho se o app morrer sem avisar (recompilação, travamento).
        .env("HARNESS_PARENT_PID", std::process::id().to_string())
        .env("HARNESS_RUNTIME_FILE", &runtime_file)
        .stdin(Stdio::null())
        .spawn();
    if let Err(error) = &child {
        eprintln!("harness: não consegui iniciar o núcleo com uv: {error}");
    }
    CoreState {
        info: CoreInfo { url: format!("http://127.0.0.1:{port}"), token, managed: true },
        child: Mutex::new(child.ok()),
        runtime_file: Some(runtime_file),
    }
}

/// SIGTERM primeiro: o núcleo encerra as sessões e os agentes saem direito.
fn stop_core(child: &mut Child) {
    unsafe {
        libc::kill(child.id() as libc::pid_t, libc::SIGTERM);
    }
    let deadline = Instant::now() + Duration::from_secs(4);
    while Instant::now() < deadline {
        if let Ok(Some(_)) = child.try_wait() {
            return;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let _ = child.kill();
    let _ = child.wait();
}

/// O endereço que o núcleo escreveu ao subir; se ainda não escreveu, o que foi pedido a ele.
#[tauri::command]
async fn core_info(state: tauri::State<'_, CoreState>) -> Result<CoreInfo, String> {
    let mut info = state.info.clone();
    if let Some(path) = &state.runtime_file {
        let deadline = Instant::now() + Duration::from_secs(20);
        while Instant::now() < deadline {
            if let Ok(text) = std::fs::read_to_string(path) {
                if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
                    if value["token"] == info.token.as_str() {
                        if let Some(url) = value["url"].as_str() {
                            info.url = url.to_string();
                            break;
                        }
                    }
                }
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    }
    Ok(info)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    if event.state() == ShortcutState::Pressed && shortcut.matches(Modifiers::ALT, Code::Space) {
                        toggle_capture(app);
                    }
                })
                .build(),
        )
        .setup(|app| {
            if let Err(error) = app.global_shortcut().register(capture_shortcut()) {
                eprintln!("metis: o ⌥Espaço está com outro app ({error}); a captura fica no ⌘K");
            }
            Ok(())
        })
        .manage(start_core())
        .manage(browser::Browsers::default())
        .invoke_handler(tauri::generate_handler![
            core_info,
            capture_open,
            browser::browser_open,
            browser::browser_bounds,
            browser::browser_visible,
            browser::browser_navigate,
            browser::browser_go,
            browser::browser_design,
            browser::browser_close,
            browser::open_external
        ])
        .build(tauri::generate_context!())
        .expect("erro ao iniciar o Harness");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = handle.try_state::<CoreState>() {
                if let Some(mut child) = state.child.lock().expect("estado do núcleo").take() {
                    stop_core(&mut child);
                }
            }
        }
    });
}
