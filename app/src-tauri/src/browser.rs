//! Navegador embutido: cada aba é um WebKit filho da janela, posicionado sobre a área
//! que a interface reserva para ele.
//!
//! A página fala com a MÊTIS por navegações para `metis://…`, que nunca saem daqui:
//! o `on_navigation` lê o pedido e cancela. Assim nenhuma página ganha acesso ao IPC
//! do app nem ao token do núcleo. O pior que uma página pode fazer é mandar uma escolha
//! falsa do modo de design, que só vale com o modo ligado e cai na barra de entrada
//! para revisar.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::Serialize;
use tauri::webview::{DownloadEvent, NewWindowResponse, PageLoadEvent, WebviewBuilder};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, Runtime, Url, WebviewUrl};

const SCRIPT: &str = include_str!("browser.js");

#[derive(Default)]
pub struct Browsers {
    design: Mutex<HashMap<String, bool>>,
}

impl Browsers {
    fn design_on(&self, label: &str) -> bool {
        self.design.lock().map(|map| map.get(label).copied().unwrap_or(false)).unwrap_or(false)
    }

    fn set_design(&self, label: &str, on: bool) {
        if let Ok(mut map) = self.design.lock() {
            map.insert(label.to_string(), on);
        }
    }
}

#[derive(Clone, Serialize)]
struct BrowserState {
    label: String,
    url: Option<String>,
    title: Option<String>,
    loading: Option<bool>,
}

#[derive(Clone, Serialize)]
struct BrowserMessage {
    label: String,
    data: String,
}

#[derive(Clone, Serialize)]
struct BrowserDownload {
    label: String,
    url: String,
    path: Option<String>,
    success: Option<bool>,
}

fn emit_state<R: Runtime>(app: &AppHandle<R>, state: BrowserState) {
    let _ = app.emit_to("main", "browser:state", state);
}

fn webview<R: Runtime>(app: &AppHandle<R>, label: &str) -> Result<tauri::Webview<R>, String> {
    if !label.starts_with("browser-") {
        return Err("aba de navegador inválida".into());
    }
    app.get_webview(label).ok_or_else(|| format!("aba {label} não existe"))
}

/// Navegações para metis://… são mensagens da página; as outras seguem normalmente.
fn on_navigation<R: Runtime>(app: &AppHandle<R>, label: &str, url: &Url) -> bool {
    if url.scheme() != "metis" {
        emit_state(app, BrowserState { label: label.into(), url: Some(url.to_string()), title: None, loading: Some(true) });
        return true;
    }
    let data = url.query_pairs().find(|(key, _)| key == "d").map(|(_, value)| value.into_owned()).unwrap_or_default();
    let browsers = app.state::<Browsers>();
    #[cfg(debug_assertions)]
    eprintln!("metis: {label} → {} ({} bytes, design {})", url.host_str().unwrap_or("?"), data.len(), browsers.design_on(label));
    match url.host_str().unwrap_or("") {
        "pick" if browsers.design_on(label) => {
            let _ = app.emit_to("main", "browser:pick", BrowserMessage { label: label.into(), data });
        }
        "key" => {
            let _ = app.emit_to("main", "browser:key", BrowserMessage { label: label.into(), data });
        }
        "design-off" => {
            browsers.set_design(label, false);
            let _ = app.emit_to("main", "browser:design", BrowserMessage { label: label.into(), data: "off".into() });
        }
        _ => {}
    }
    false
}

/// ~/Downloads/<nome>, sem sobrescrever o que já estiver lá.
fn download_path(suggested: &Path, url: &Url) -> PathBuf {
    let home = std::env::var("HOME").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("/tmp"));
    let folder = home.join("Downloads");
    let name = suggested
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .filter(|n| !n.is_empty())
        .or_else(|| url.path_segments().and_then(|mut s| s.next_back().map(str::to_string)).filter(|n| !n.is_empty()))
        .unwrap_or_else(|| "download".into());
    let mut target = folder.join(&name);
    let (stem, ext) = match name.rsplit_once('.') {
        Some((stem, ext)) if !stem.is_empty() => (stem.to_string(), format!(".{ext}")),
        _ => (name.clone(), String::new()),
    };
    let mut n = 1;
    while target.exists() {
        target = folder.join(format!("{stem} ({n}){ext}"));
        n += 1;
    }
    target
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn browser_open(
    app: AppHandle,
    label: String,
    url: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    incognito: bool,
) -> Result<(), String> {
    if !label.starts_with("browser-") {
        return Err("aba de navegador inválida".into());
    }
    if app.get_webview(&label).is_some() {
        return Ok(());
    }
    let window = app.get_window("main").ok_or("janela principal não encontrada")?;
    let parsed = Url::parse(&url).map_err(|e| format!("endereço inválido: {e}"))?;

    let nav = (app.clone(), label.clone());
    let load = (app.clone(), label.clone());
    let title = (app.clone(), label.clone());
    let popup = (app.clone(), label.clone());
    let download = (app.clone(), label.clone());

    let builder = WebviewBuilder::new(&label, WebviewUrl::External(parsed))
        .initialization_script(SCRIPT)
        .incognito(incognito)
        .devtools(true)
        .on_navigation(move |url| on_navigation(&nav.0, &nav.1, url))
        .on_page_load(move |webview, payload| {
            let finished = matches!(payload.event(), PageLoadEvent::Finished);
            emit_state(
                &load.0,
                BrowserState { label: load.1.clone(), url: Some(payload.url().to_string()), title: None, loading: Some(!finished) },
            );
            if finished && load.0.state::<Browsers>().design_on(&load.1) {
                let _ = webview.eval("window.__metis && window.__metis.design(true)");
            }
        })
        .on_document_title_changed(move |_, value| {
            emit_state(&title.0, BrowserState { label: title.1.clone(), url: None, title: Some(value), loading: None });
        })
        .on_new_window(move |url, _| {
            // target=_blank e window.open viram uma aba nova da MÊTIS, não uma janela solta.
            let _ = popup.0.emit_to("main", "browser:new-window", BrowserMessage { label: popup.1.clone(), data: url.to_string() });
            NewWindowResponse::Deny
        })
        .on_download(move |_, event| {
            match event {
                DownloadEvent::Requested { url, destination } => {
                    *destination = download_path(destination, &url);
                    let _ = download.0.emit_to(
                        "main",
                        "browser:download",
                        BrowserDownload {
                            label: download.1.clone(),
                            url: url.to_string(),
                            path: Some(destination.to_string_lossy().into_owned()),
                            success: None,
                        },
                    );
                }
                DownloadEvent::Finished { url, path, success } => {
                    let _ = download.0.emit_to(
                        "main",
                        "browser:download",
                        BrowserDownload {
                            label: download.1.clone(),
                            url: url.to_string(),
                            path: path.map(|p| p.to_string_lossy().into_owned()),
                            success: Some(success),
                        },
                    );
                }
                _ => {}
            }
            true
        });

    window
        .add_child(builder, LogicalPosition::new(x, y), LogicalSize::new(width.max(1.0), height.max(1.0)))
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn browser_bounds(app: AppHandle, label: String, x: f64, y: f64, width: f64, height: f64) -> Result<(), String> {
    let view = webview(&app, &label)?;
    view.set_position(LogicalPosition::new(x, y)).map_err(|e| e.to_string())?;
    view.set_size(LogicalSize::new(width.max(1.0), height.max(1.0))).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn browser_visible(app: AppHandle, label: String, visible: bool) -> Result<(), String> {
    let view = webview(&app, &label)?;
    if visible { view.show() } else { view.hide() }.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn browser_navigate(app: AppHandle, label: String, url: String) -> Result<(), String> {
    let parsed = Url::parse(&url).map_err(|e| format!("endereço inválido: {e}"))?;
    webview(&app, &label)?.navigate(parsed).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn browser_go(app: AppHandle, label: String, action: String) -> Result<(), String> {
    let view = webview(&app, &label)?;
    match action.as_str() {
        "back" => view.eval("history.back()"),
        "forward" => view.eval("history.forward()"),
        "reload" => view.reload(),
        "stop" => view.eval("window.stop()"),
        "focus" => view.set_focus(),
        "devtools" => {
            view.open_devtools();
            Ok(())
        }
        other => return Err(format!("ação desconhecida: {other}")),
    }
    .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn browser_design(app: AppHandle, label: String, on: bool) -> Result<(), String> {
    let view = webview(&app, &label)?;
    app.state::<Browsers>().set_design(&label, on);
    view.eval(format!("window.__metis && window.__metis.design({on})")).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn browser_close(app: AppHandle, label: String) -> Result<(), String> {
    app.state::<Browsers>().set_design(&label, false);
    match app.get_webview(&label) {
        Some(view) => view.close().map_err(|e| e.to_string()),
        None => Ok(()),
    }
}

/// Abre no navegador do Mac (http e https só).
#[tauri::command]
pub async fn open_external(url: String) -> Result<(), String> {
    let parsed = Url::parse(&url).map_err(|e| format!("endereço inválido: {e}"))?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err("só abro http e https".into());
    }
    std::process::Command::new("open").arg(parsed.as_str()).spawn().map(|_| ()).map_err(|e| e.to_string())
}
