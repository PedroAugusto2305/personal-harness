//! Moldura nativa do Harness: abre a janela e cuida do núcleo em Python.
//!
//! O núcleo (`core/`) é dono dos terminais dos agentes. Em desenvolvimento ele é
//! iniciado com `uv run` a partir da pasta do repositório; se `HARNESS_CORE_URL` e
//! `HARNESS_TOKEN` já vierem no ambiente, o app só se conecta a um núcleo existente.

use std::io::Read;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};

const DEFAULT_PORT: u16 = 47830;

#[derive(Clone, serde::Serialize)]
struct CoreInfo {
    url: String,
    token: String,
    managed: bool,
}

struct CoreState {
    info: CoreInfo,
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

fn core_dir() -> PathBuf {
    std::env::var("HARNESS_CORE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../core"))
}

fn start_core() -> CoreState {
    if let (Ok(url), Ok(token)) = (std::env::var("HARNESS_CORE_URL"), std::env::var("HARNESS_TOKEN")) {
        return CoreState { info: CoreInfo { url, token, managed: false }, child: Mutex::new(None) };
    }
    let port = std::env::var("HARNESS_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(DEFAULT_PORT);
    let token = random_token();
    let child = Command::new("uv")
        .args(["run", "--quiet", "--project"])
        .arg(core_dir())
        .arg("harness-core")
        .env("HARNESS_PORT", port.to_string())
        .env("HARNESS_TOKEN", &token)
        .stdin(Stdio::null())
        .spawn();
    if let Err(error) = &child {
        eprintln!("harness: não consegui iniciar o núcleo com uv: {error}");
    }
    CoreState {
        info: CoreInfo { url: format!("http://127.0.0.1:{port}"), token, managed: true },
        child: Mutex::new(child.ok()),
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

#[tauri::command]
fn core_info(state: tauri::State<CoreState>) -> CoreInfo {
    state.info.clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(start_core())
        .invoke_handler(tauri::generate_handler![core_info])
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
