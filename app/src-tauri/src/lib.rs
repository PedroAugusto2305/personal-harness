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
#[cfg(target_os = "macos")]
mod webkit;

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

/// Perfil da MÊTIS em uso (v0.9.8): cada um com a própria pasta de dados, porta e Brain.
#[derive(Clone, Debug)]
struct Profile {
    id: String,
    home: PathBuf,
    port: u16,
    vault: Option<String>,
}

static PROFILE: Mutex<Option<Profile>> = Mutex::new(None);

fn user_home() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/tmp".into()))
}

fn expand(path: &str) -> PathBuf {
    match path.strip_prefix("~/") {
        Some(rest) => user_home().join(rest),
        None if path == "~" => user_home(),
        None => PathBuf::from(path),
    }
}

/// O perfil ativo no registro (~/.harness/perfis.json). Sem registro, ou com HARNESS_HOME
/// imposto pelo ambiente (app de desenvolvimento, testes), é a pasta de sempre.
fn read_profile() -> Profile {
    if let Ok(home) = std::env::var("HARNESS_HOME") {
        let port = std::env::var("HARNESS_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(DEFAULT_PORT);
        return Profile { id: "principal".into(), home: PathBuf::from(home), port, vault: None };
    }
    let principal = Profile { id: "principal".into(), home: user_home().join(".harness"), port: DEFAULT_PORT, vault: None };
    let Ok(text) = std::fs::read_to_string(user_home().join(".harness/perfis.json")) else { return principal };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) else { return principal };
    let active = value["ativo"].as_str().unwrap_or("principal");
    let Some(entry) = value["perfis"].as_array().and_then(|list| list.iter().find(|p| p["id"].as_str() == Some(active))) else {
        return principal;
    };
    Profile {
        id: active.to_string(),
        home: entry["pasta"].as_str().map(expand).unwrap_or(principal.home),
        port: entry["porta"].as_u64().and_then(|p| u16::try_from(p).ok()).unwrap_or(DEFAULT_PORT),
        vault: entry["vault"].as_str().filter(|v| !v.is_empty()).map(str::to_string),
    }
}

fn profile() -> Profile {
    let mut slot = PROFILE.lock().unwrap_or_else(|e| e.into_inner());
    slot.get_or_insert_with(read_profile).clone()
}

fn harness_home() -> PathBuf {
    profile().home
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
    let active = profile();
    let port = free_port(active.port);
    let token = random_token();
    let home = active.home.clone();
    let _ = std::fs::create_dir_all(&home);
    let log = std::fs::OpenOptions::new().create(true).append(true).open(home.join("nucleo.log"));
    let mut command = Command::new("uv");
    command
        .args(["run", "--quiet", "--project"])
        .arg(core_dir())
        .arg("harness-core")
        .env("HARNESS_PORT", port.to_string())
        .env("HARNESS_TOKEN", &token)
        .env("HARNESS_HOME", &home)
        .env("HARNESS_PROFILE", &active.id)
        .env_remove("HARNESS_PARENT_PID")
        .stdin(Stdio::null())
        .process_group(0);
    if let Some(vault) = &active.vault {
        command.env("BRAIN_VAULT", expand(vault));
    }
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

/// O núcleo com o nosso token já gravou o endereço dele no runtime.json? Se sim, guarda o endereço.
fn runtime_ready(info: &mut CoreInfo) -> bool {
    let Ok(text) = std::fs::read_to_string(runtime_file()) else { return false };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) else { return false };
    if value["token"] != info.token.as_str() {
        return false;
    }
    match value["url"].as_str() {
        Some(url) => {
            info.url = url.to_string();
            true
        }
        None => false,
    }
}

/// Espera o núcleo novo gravar o endereço dele (com o nosso token) no runtime.json.
fn wait_runtime(info: &mut CoreInfo) {
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline && !runtime_ready(info) {
        std::thread::sleep(Duration::from_millis(100));
    }
}

/// Sobe um núcleo e espera ele ficar pronto. Se ele sair antes (a porta ainda presa pelo
/// núcleo que acabou de fechar, por exemplo), espera um pouco e tenta de novo.
fn spawn_ready() -> (CoreInfo, Option<Child>) {
    let mut attempt = 0;
    loop {
        attempt += 1;
        let (mut info, mut child) = spawn_core();
        let deadline = Instant::now() + Duration::from_secs(30);
        loop {
            if runtime_ready(&mut info) {
                return (info, child);
            }
            let exited = match child.as_mut() {
                Some(process) => matches!(process.try_wait(), Ok(Some(_))),
                None => true,
            };
            if exited || Instant::now() >= deadline {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        if attempt >= 4 {
            return (info, child);
        }
        eprintln!("metis: o núcleo novo não subiu (tentativa {attempt}); tentando de novo");
        std::thread::sleep(Duration::from_secs(2));
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

/// Encerra o núcleo deste app (fecha os terminais dele) e espera ele sair.
fn stop_core(state: &CoreState) -> Result<(), String> {
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
    Ok(())
}

/// Reinicia o núcleo (versão nova do código): encerra o atual, que fecha os terminais, e sobe outro.
#[tauri::command]
async fn core_restart(state: tauri::State<'_, CoreState>) -> Result<CoreInfo, String> {
    stop_core(&state)?;
    let (info, child) = spawn_ready();
    *state.child.lock().map_err(|e| e.to_string())? = child;
    *state.info.lock().map_err(|e| e.to_string())? = info.clone();
    Ok(info)
}

/// Troca de perfil (v0.9.8): o núcleo atual já gravou o perfil novo como ativo; aqui ele é
/// desligado (os terminais dele fecham), o registro é relido e sobe o núcleo do outro perfil
/// (ou o app se liga a ele, se já estiver no ar). A tela recarrega depois.
#[tauri::command]
async fn profile_switch(state: tauri::State<'_, CoreState>) -> Result<CoreInfo, String> {
    if std::env::var("HARNESS_HOME").is_ok() || std::env::var("HARNESS_CORE_URL").is_ok() {
        return Err("perfis só trocam na MÊTIS instalada (aqui a pasta veio do ambiente)".into());
    }
    stop_core(&state)?;
    *PROFILE.lock().map_err(|e| e.to_string())? = Some(read_profile());
    let (info, child) = match existing_core() {
        Some(info) => (info, None),
        None => spawn_ready(),
    };
    *state.child.lock().map_err(|e| e.to_string())? = child;
    *state.info.lock().map_err(|e| e.to_string())? = info.clone();
    Ok(info)
}

/// O PATH do shell de login do usuário. Aberto pelo Finder, pelo Launchpad ou pelo Dock,
/// o app recebe só /usr/bin:/bin:/usr/sbin:/sbin e não acharia o `uv` (que sobe o núcleo)
/// nem, no núcleo, o `claude` e o `codex`. O shell responde entre marcas, porque o -i
/// pode imprimir outras coisas; se travar, desiste em 5 s e fica o PATH que veio.
fn login_path() -> Option<String> {
    let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/zsh".into());
    let mut child = Command::new(shell)
        .args(["-l", "-i", "-c", "printf '__METIS_PATH__%s__METIS_PATH__' \"$PATH\""])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(50)),
            _ => {
                let _ = child.kill();
                return None;
            }
        }
    }
    let mut out = String::new();
    child.stdout.take()?.read_to_string(&mut out).ok()?;
    let start = out.find("__METIS_PATH__")? + "__METIS_PATH__".len();
    let end = start + out[start..].find("__METIS_PATH__")?;
    let path = out[start..end].trim().to_string();
    (!path.is_empty()).then_some(path)
}

/// Aberto fora de um terminal (sem TERM), o app passa a usar o PATH do shell de login,
/// com o que já vinha no fim. Roda antes de qualquer thread, por isso o set_var é seguro.
fn adopt_login_path() {
    if std::env::var_os("TERM").is_some() {
        return;
    }
    if let Some(login) = login_path() {
        let current = std::env::var("PATH").unwrap_or_default();
        let mut parts: Vec<&str> = login.split(':').filter(|p| !p.is_empty()).collect();
        for p in current.split(':').filter(|p| !p.is_empty()) {
            if !parts.contains(&p) {
                parts.push(p);
            }
        }
        // SAFETY: chamado no começo do run(), antes de o Tauri ou o núcleo criarem threads.
        unsafe { std::env::set_var("PATH", parts.join(":")) };
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    adopt_login_path();
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
            // A MÊTIS de desenvolvimento (scripts/dev.sh) deixa o ⌥Espaço para a de uso, a instalada.
            if std::env::var("METIS_DEV").is_ok() {
                return Ok(());
            }
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
            profile_switch,
            capture_open,
            browser::browser_open,
            browser::browser_bounds,
            browser::browser_visible,
            browser::browser_navigate,
            browser::browser_go,
            browser::browser_design,
            browser::browser_close,
            browser::browser_eval,
            browser::browser_photo,
            browser::browser_user_agent,
            browser::browser_remove_profile,
            browser::browser_import_cookies,
            browser::browser_zoom,
            browser::app_zoom,
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
