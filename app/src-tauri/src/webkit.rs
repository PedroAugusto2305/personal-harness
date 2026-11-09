//! O que o navegador precisa do WebKit e o Tauri não expõe (v0.9.8): a foto da página para o
//! agente, o user agent da emulação e o cofre de cookies de cada perfil (importar do Chrome e
//! apagar o perfil). Tudo roda na thread principal; o resultado volta por um canal.

use std::cell::Cell;
use std::ffi::c_void;
use std::rc::Rc;
use std::sync::mpsc::Sender;
use std::sync::Mutex;

use block2::RcBlock;
use objc2::rc::Retained;
use objc2::runtime::AnyObject;
use objc2::{AllocAnyThread, MainThreadMarker};
use objc2_app_kit::{NSBitmapImageFileType, NSBitmapImageRep, NSImage, NSImageCompressionFactor};
use objc2_foundation::{
    ns_string, NSDataBase64EncodingOptions, NSDate, NSDictionary, NSError, NSHTTPCookie, NSHTTPCookieDomain, NSHTTPCookieExpires,
    NSHTTPCookieName, NSHTTPCookiePath, NSHTTPCookiePropertyKey, NSHTTPCookieSecure, NSHTTPCookieValue, NSMutableDictionary,
    NSNumber, NSString, NSUUID,
};
use objc2_web_kit::{WKSnapshotConfiguration, WKWebView, WKWebsiteDataStore};
use serde::Deserialize;

pub type Reply<T> = Sender<Result<T, String>>;

/// Responde uma vez só, mesmo que o WebKit chame o bloco de novo.
fn once<T: 'static>(tx: Reply<T>) -> impl Fn(Result<T, String>) {
    let slot = Mutex::new(Some(tx));
    move |value| {
        if let Some(tx) = slot.lock().ok().and_then(|mut s| s.take()) {
            let _ = tx.send(value);
        }
    }
}

fn error_text(error: *mut NSError) -> Option<String> {
    unsafe { error.as_ref() }.map(|e| e.localizedDescription().to_string())
}

/// 32 caracteres hex (o identificador do perfil) → o NSUUID do cofre do WebKit.
fn uuid(hex: &str) -> Result<Retained<NSUUID>, String> {
    if hex.len() != 32 || !hex.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err("identificador de perfil inválido".into());
    }
    let text = format!("{}-{}-{}-{}-{}", &hex[0..8], &hex[8..12], &hex[12..16], &hex[16..20], &hex[20..32]);
    NSUUID::initWithUUIDString(NSUUID::alloc(), &NSString::from_str(&text)).ok_or_else(|| "identificador de perfil inválido".into())
}

/// Os 16 bytes que o Tauri pede em `data_store_identifier`.
pub fn identifier_bytes(hex: &str) -> Result<[u8; 16], String> {
    if hex.len() != 32 {
        return Err("identificador de perfil inválido".into());
    }
    let mut out = [0u8; 16];
    for (i, byte) in out.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16).map_err(|_| "identificador de perfil inválido".to_string())?;
    }
    Ok(out)
}

/// A parte visível da página, em JPEG, com 1 pixel por pixel da página (base64).
pub fn snapshot(webview: *mut c_void, tx: Reply<String>) {
    let reply = once(tx);
    let Some(mtm) = MainThreadMarker::new() else {
        return reply(Err("a foto precisa da thread principal".into()));
    };
    let view: &WKWebView = unsafe { &*(webview as *const WKWebView) };
    let config = unsafe { WKSnapshotConfiguration::new(mtm) };
    let scale = view.window().map(|w| w.backingScaleFactor()).unwrap_or(1.0);
    let width = view.bounds().size.width;
    if scale > 1.0 && width > 1.0 {
        unsafe { config.setSnapshotWidth(Some(&NSNumber::new_f64(width / scale))) };
    }
    let block = RcBlock::new(move |image: *mut NSImage, error: *mut NSError| {
        let result = match unsafe { image.as_ref() } {
            Some(image) => jpeg(image),
            None => Err(error_text(error).unwrap_or_else(|| "o WebKit não devolveu a imagem".into())),
        };
        reply(result);
    });
    unsafe { view.takeSnapshotWithConfiguration_completionHandler(Some(&config), &block) };
}

fn jpeg(image: &NSImage) -> Result<String, String> {
    let tiff = image.TIFFRepresentation().ok_or("a imagem veio vazia")?;
    let rep = NSBitmapImageRep::imageRepWithData(&tiff).ok_or("imagem ilegível")?;
    let quality = NSNumber::new_f64(0.72);
    let props: Retained<NSDictionary<NSString, AnyObject>> = NSDictionary::from_slices(&[unsafe { NSImageCompressionFactor }], &[&*quality]);
    let data = unsafe { rep.representationUsingType_properties(NSBitmapImageFileType::JPEG, &props) }.ok_or("não deu para gerar o JPEG")?;
    Ok(data.base64EncodedStringWithOptions(NSDataBase64EncodingOptions(0)).to_string())
}

/// User agent da emulação (None volta ao do Safari); vale a partir da próxima carga.
pub fn set_user_agent(webview: *mut c_void, agent: Option<String>) {
    let view: &WKWebView = unsafe { &*(webview as *const WKWebView) };
    let text = agent.filter(|a| !a.trim().is_empty()).map(|a| NSString::from_str(&a));
    unsafe { view.setCustomUserAgent(text.as_deref()) };
}

/// Apaga o cofre (cookies, cache, armazenamento) de um perfil que não tem mais aba aberta.
pub fn remove_store(hex: String, tx: Reply<()>) {
    let reply = once(tx);
    let Some(mtm) = MainThreadMarker::new() else {
        return reply(Err("precisa da thread principal".into()));
    };
    let id = match uuid(&hex) {
        Ok(id) => id,
        Err(e) => return reply(Err(e)),
    };
    let block = RcBlock::new(move |error: *mut NSError| reply(error_text(error).map_or(Ok(()), Err)));
    unsafe { WKWebsiteDataStore::removeDataStoreForIdentifier_completionHandler(&id, &block, mtm) };
}

#[derive(Deserialize)]
pub struct CookieIn {
    nome: String,
    valor: String,
    dominio: String,
    caminho: Option<String>,
    expira: Option<f64>,
    seguro: bool,
    http_only: bool,
    same_site: Option<String>,
}

/// NSHTTPCookie com o domínio como veio (".google.com" vale para os subdomínios; o wry
/// tiraria o ponto e o cookie ficaria preso ao domínio exato).
fn cookie(c: &CookieIn) -> Option<Retained<NSHTTPCookie>> {
    let name = NSString::from_str(&c.nome);
    let value = NSString::from_str(&c.valor);
    let path = NSString::from_str(c.caminho.as_deref().filter(|p| !p.is_empty()).unwrap_or("/"));
    let domain = NSString::from_str(&c.dominio);
    let props: Retained<NSMutableDictionary<NSHTTPCookiePropertyKey, AnyObject>> = NSMutableDictionary::from_slices(
        &[unsafe { NSHTTPCookieName }, unsafe { NSHTTPCookieValue }, unsafe { NSHTTPCookiePath }, unsafe { NSHTTPCookieDomain }],
        &[&*name, &*value, &*path, &*domain],
    );
    if let Some(when) = c.expira {
        let date = NSDate::dateWithTimeIntervalSince1970(when);
        unsafe { props.insert(NSHTTPCookieExpires, &*date) };
    }
    if c.seguro {
        unsafe { props.insert(NSHTTPCookieSecure, ns_string!("TRUE")) };
    }
    if c.http_only {
        props.insert(ns_string!("HttpOnly"), ns_string!("TRUE"));
    }
    match c.same_site.as_deref() {
        Some("lax") => props.insert(ns_string!("SameSite"), ns_string!("lax")),
        Some("strict") => props.insert(ns_string!("SameSite"), ns_string!("strict")),
        _ => {}
    }
    unsafe { NSHTTPCookie::cookieWithProperties(&props) }
}

/// Grava os cookies no cofre do perfil (None = o perfil Padrão). Devolve quantos entraram.
pub fn import_cookies(profile: Option<String>, cookies: Vec<CookieIn>, tx: Reply<usize>) {
    let reply = Rc::new(once(tx));
    let Some(mtm) = MainThreadMarker::new() else {
        return reply(Err("precisa da thread principal".into()));
    };
    let store = match profile {
        Some(hex) => match uuid(&hex) {
            Ok(id) => unsafe { WKWebsiteDataStore::dataStoreForIdentifier(&id, mtm) },
            Err(e) => return reply(Err(e)),
        },
        None => unsafe { WKWebsiteDataStore::defaultDataStore(mtm) },
    };
    let jar = unsafe { store.httpCookieStore() };
    let built: Vec<Retained<NSHTTPCookie>> = cookies.iter().filter_map(cookie).collect();
    let total = built.len();
    if total == 0 {
        return reply(Ok(0));
    }
    let left = Rc::new(Cell::new(total));
    for item in built {
        let left = left.clone();
        let reply = reply.clone();
        let block = RcBlock::new(move || {
            left.set(left.get() - 1);
            if left.get() == 0 {
                reply(Ok(total));
            }
        });
        unsafe { jar.setCookie_completionHandler(&item, Some(&block)) };
    }
}
