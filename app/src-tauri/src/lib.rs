//! Moldura nativa da MÊTIS: abre a janela e se liga ao núcleo em Python.
//!
//! O núcleo (`core/`) é dono dos terminais dos agentes e roda por conta própria (v0.9.2):
//! fechar, recarregar ou recompilar a janela não derruba os agentes. Ao abrir, a janela
//! procura o núcleo que já está no ar (`~/.harness/runtime.json`); se não houver, sobe um
//! com `uv run` a partir da pasta do repositório, fora do grupo de processos do app.
//! Se `HARNESS_CORE_URL` e `HARNESS_TOKEN` vierem no ambiente, usa esse núcleo.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream, ToSocketAddrs};
use std::os::unix::process::CommandExt;
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
    /// O app subiu este núcleo agora (false = se ligou a um que já estava no ar).
    managed: bool,
}

struct CoreState {
    info: Mutex<CoreInfo>,
    /// O núcleo que este app subiu (só para não deixar zumbi enquanto o app vive).
    child: Mutex<Option<Child>>,
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

fn harness_home() -> PathBuf {
    std::env::var("HARNESS_HOME").map(PathBuf::from).unwrap_or_else(|_| {
        PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/tmp".into())).join(".harness")
    })
}

fn runtime_file() -> PathBuf {
    harness_home().join("runtime.json")
}

/// Pedido HTTP curto ao núcleo (sem biblioteca: só GET/POST locais). Devolve o código e o corpo.
fn core_request(url: &str, method: &str, path: &str, token: &str) -> Option<(u16, String)> {
    let host = url.trim_start_matches("http://").trim_end_matches('/');
    let addr = host.to_socket_addrs().ok()?.next()?;
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(600)).ok()?;
    let _ = stream.set_read_timeout(Some(Duration::from_secs(3)));
    let request = format!(
        "{method} {path} HTTP/1.1\r\nHost: {host}\r\nX-Harness-Token: {token}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(request.as_bytes()).ok()?;
    let mut raw = String::new();
    let _ = stream.read_to_string(&mut raw);
    let status = raw.split_whitespace().nth(1)?.parse().ok()?;
    let body = raw.split("\r\n\r\n").nth(1).unwrap_or("").to_string();
    Some((status, body))
}

fn pid_alive(pid: i64) -> bool {
    pid > 0 && unsafe { libc::kill(pid as libc::pid_t, 0) } == 0
}

/// O núcleo que já está no ar (outra janela, ou a anterior desta), se responder.
fn existing_core() -> Option<CoreInfo> {
    let text = std::fs::read_to_string(runtime_file()).ok()?;
    let value: serde_json::Value = serde_json::from_str(&text).ok()?;
    let url = value["url"].as_str()?.to_string();
    let token = value["token"].as_str()?.to_string();
    if !pid_alive(value["pid"].as_i64().unwrap_or(0)) {
        return None;
    }
    match core_request(&url, "GET", "/sessions", &token) {
        Some((200, _)) => Some(CoreInfo { url, token, managed: false }),
        _ => None,
    }
}

/// Sobe um núcleo independente: grupo de processos próprio (o ⌃C do `tauri dev` e o fim
/// do app não chegam nele) e saída em ~/.harness/nucleo.log.
fn spawn_core() -> (CoreInfo, Option<Child>) {
    let preferred = std::env::var("HARNESS_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(DEFAULT_PORT);
    let port = free_port(preferred);
    let token = random_token();
    let home = harness_home();
    let _ = std::fs::create_dir_all(&home);
    let log = std::fs::OpenOptions::new().create(true).append(true).open(home.join("nucleo.log"));
    let mut command = Command::new("uv");
    command
        .args(["run", "--quiet", "--project"])
        .arg(core_dir())
        .arg("harness-core")
        .env("HARNESS_PORT", port.to_string())
        .env("HARNESS_TOKEN", &token)
        .env_remove("HARNESS_PARENT_PID")
        .stdin(Stdio::null())
        .process_group(0);
    if let Ok(file) = log {
        if let Ok(copy) = file.try_clone() {
            command.stdout(copy);
        }
        command.stderr(file);
    }
    let child = command.spawn();
    if let Err(error) = &child {
        eprintln!("metis: não consegui iniciar o núcleo com uv: {error}");
    }
    (CoreInfo { url: format!("http://127.0.0.1:{port}"), token, managed: true }, child.ok())
}

fn start_core() -> CoreState {
    if let (Ok(url), Ok(token)) = (std::env::var("HARNESS_CORE_URL"), std::env::var("HARNESS_TOKEN")) {
        return CoreState { info: Mutex::new(CoreInfo { url, token, managed: false }), child: Mutex::new(None) };
    }
    if let Some(info) = existing_core() {
        return CoreState { info: Mutex::new(info), child: Mutex::new(None) };
    }
    let (info, child) = spawn_core();
    CoreState { info: Mutex::new(info), child: Mutex::new(child) }
}

/// Espera o núcleo novo gravar o endereço dele (com o nosso token) no runtime.json.
fn wait_runtime(info: &mut CoreInfo) {
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline {
        if let Ok(text) = std::fs::read_to_string(runtime_file()) {
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
                if value["token"] == info.token.as_str() {
                    if let Some(url) = value["url"].as_str() {
                        info.url = url.to_string();
                        return;
                    }
                }
            }
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

/// O endereço do núcleo; se o app acabou de subir um, espera ele ficar pronto.
#[tauri::command]
async fn core_info(state: tauri::State<'_, CoreState>) -> Result<CoreInfo, String> {
    let mut info = state.info.lock().map_err(|e| e.to_string())?.clone();
    if info.managed {
        wait_runtime(&mut info);
        if let Ok(mut stored) = state.info.lock() {
            stored.url = info.url.clone();
        }
    }
    Ok(info)
}

/// Reinicia o núcleo (versão nova do código): encerra o atual, que fecha os terminais, e sobe outro.
#[tauri::command]
async fn core_restart(state: tauri::State<'_, CoreState>) -> Result<CoreInfo, String> {
    let current = state.info.lock().map_err(|e| e.to_string())?.clone();
    let pid = std::fs::read_to_string(runtime_file())
        .ok()
        .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
        .and_then(|value| value["pid"].as_i64())
        .unwrap_or(0);
    let _ = core_request(&current.url, "POST", "/desligar", &current.token);
    let deadline = Instant::now() + Duration::from_secs(10);
    while pid_alive(pid) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(100));
    }
    if pid_alive(pid) {
        unsafe {
            libc::kill(pid as libc::pid_t, libc::SIGTERM);
        }
        std::thread::sleep(Duration::from_millis(800));
    }
    if let Some(mut old) = state.child.lock().map_err(|e| e.to_string())?.take() {
        let _ = old.try_wait();
    }
    let (mut info, child) = spawn_core();
    wait_runtime(&mut info);
    *state.child.lock().map_err(|e| e.to_string())? = child;
    *state.info.lock().map_err(|e| e.to_string())? = info.clone();
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
            core_restart,
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

    // Fechar o app não encerra o núcleo: os agentes seguem vivos e a próxima janela se liga a ele.
    // Desligar de vez é pela MÊTIS (Ajustes → Desligar a MÊTIS) ou `metis desligar`.
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = handle.try_state::<CoreState>() {
                if let Ok(mut guard) = state.child.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.try_wait();
                        std::mem::forget(child); // o processo segue sozinho; o launchd adota
                    }
                }
            }
        }
    });
}
