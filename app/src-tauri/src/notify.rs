//! Aviso nativo do macOS (v0.9.9, pedido do Pedro: "como o Orca"): a notificação sai pela
//! Central de Notificações com o ícone e o nome da MÊTIS, em vez do `osascript` (que aparece
//! como Editor de Scripts). Clicar no aviso traz a janela e abre o que ele avisou (a sessão, a
//! aprovação ou a automação), pelo evento `metis-aviso`.
//!
//! Só funciona com o app num `.app` (o UserNotifications exige o pacote): na MÊTIS de
//! desenvolvimento (`tauri dev`) tudo responde "fora do app" e a janela cai no aviso pelo núcleo.
//! Com a janela fechada, o núcleo chama o próprio executável com `--aviso <json>` (ver `helper`).

use std::sync::atomic::{AtomicU8, Ordering};
use std::sync::mpsc;
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use block2::RcBlock;
use objc2::rc::Retained;
use objc2::runtime::{Bool, NSObject, NSObjectProtocol, ProtocolObject};
use objc2::{define_class, msg_send, AllocAnyThread};
use objc2_foundation::{NSBundle, NSError, NSString};
use objc2_user_notifications::{
    UNAuthorizationOptions, UNAuthorizationStatus, UNMutableNotificationContent, UNNotification, UNNotificationPresentationOptions,
    UNNotificationRequest, UNNotificationResponse, UNNotificationSettings, UNNotificationSound, UNUserNotificationCenter,
    UNUserNotificationCenterDelegate,
};
use serde::Deserialize;
use tauri::{AppHandle, Emitter, Manager};

static APP: OnceLock<AppHandle> = OnceLock::new();

/// O alvo do último clique: quando o clique abriu o app, a janela ainda não ouve o evento, então
/// ela pede o que ficou guardado ao carregar (`notify_pending`).
static PENDING: Mutex<Option<String>> = Mutex::new(None);

/// 0 = ainda não se sabe, 1 = liberado, 2 = negado (ou erro), 3 = esperando o Pedro responder.
static AUTH: AtomicU8 = AtomicU8::new(0);
static AUTH_ERROR: Mutex<String> = Mutex::new(String::new());

#[derive(Deserialize, Default)]
pub struct Aviso {
    pub titulo: String,
    #[serde(default)]
    pub texto: String,
    #[serde(default)]
    pub subtitulo: String,
    #[serde(default = "sim")]
    pub som: bool,
    /// Para onde o clique leva: "sessao:<id>", "aprovacao:<id>", "automacao:<id>" ou "".
    #[serde(default)]
    pub alvo: String,
    /// Avisos do mesmo grupo (a mesma sessão) ficam empilhados na Central.
    #[serde(default)]
    pub grupo: String,
}

fn sim() -> bool {
    true
}

/// O app roda de um `.app` com identificador: só assim o UserNotifications aceita.
pub fn bundled() -> bool {
    let bundle = NSBundle::mainBundle();
    bundle.bundleIdentifier().is_some() && bundle.bundlePath().to_string().ends_with(".app")
}

define_class!(
    // O centro guarda o delegado como referência fraca: o objeto é esquecido de propósito em `setup`.
    #[unsafe(super(NSObject))]
    #[name = "MetisAvisosDelegate"]
    struct Delegate;

    unsafe impl NSObjectProtocol for Delegate {}

    unsafe impl UNUserNotificationCenterDelegate for Delegate {
        /// Com a MÊTIS na frente o macOS esconderia o aviso; a janela só pede aviso sem foco.
        #[unsafe(method(userNotificationCenter:willPresentNotification:withCompletionHandler:))]
        fn will_present(
            &self,
            _center: &UNUserNotificationCenter,
            _notification: &UNNotification,
            handler: &block2::DynBlock<dyn Fn(UNNotificationPresentationOptions)>,
        ) {
            handler.call((UNNotificationPresentationOptions::Banner
                | UNNotificationPresentationOptions::List
                | UNNotificationPresentationOptions::Sound,));
        }

        #[unsafe(method(userNotificationCenter:didReceiveNotificationResponse:withCompletionHandler:))]
        fn did_receive(&self, _center: &UNUserNotificationCenter, response: &UNNotificationResponse, handler: &block2::DynBlock<dyn Fn()>) {
            let id = response.notification().request().identifier().to_string();
            clicked(&id);
            handler.call(());
        }
    }
);

impl Delegate {
    fn new() -> Retained<Self> {
        let this = Self::alloc().set_ivars(());
        unsafe { msg_send![super(this), init] }
    }
}

/// O identificador do aviso leva o alvo: "metis|<alvo>|<instante>".
fn clicked(id: &str) {
    let Some(app) = APP.get() else { return };
    let target = id.split('|').nth(1).unwrap_or("").to_string();
    if let Ok(mut slot) = PENDING.lock() {
        *slot = Some(target.clone());
    }
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
    let _ = app.emit_to("main", "metis-aviso", target);
}

fn error_text(error: *mut NSError) -> Option<String> {
    unsafe { error.as_ref() }.map(|e| e.localizedDescription().to_string())
}

/// Ao abrir: o delegado (clique) e o pedido de permissão (o macOS pergunta uma vez só).
pub fn setup(app: &AppHandle) {
    let _ = APP.set(app.clone());
    if !bundled() {
        return;
    }
    let center = UNUserNotificationCenter::currentNotificationCenter();
    let delegate = Delegate::new();
    center.setDelegate(Some(ProtocolObject::from_ref(&*delegate)));
    std::mem::forget(delegate);
    AUTH.store(3, Ordering::SeqCst);
    let block = RcBlock::new(|granted: Bool, error: *mut NSError| {
        let text = error_text(error);
        eprintln!("metis: avisos do macOS {}{}", if granted.as_bool() { "liberados" } else { "negados" }, text.as_deref().map(|t| format!(" ({t})")).unwrap_or_default());
        if let Some(text) = text {
            if let Ok(mut slot) = AUTH_ERROR.lock() {
                *slot = text;
            }
        }
        AUTH.store(if granted.as_bool() { 1 } else { 2 }, Ordering::SeqCst);
    });
    center.requestAuthorizationWithOptions_completionHandler(
        UNAuthorizationOptions::Alert | UNAuthorizationOptions::Sound | UNAuthorizationOptions::Badge,
        &block,
    );
}

/// Como estão os avisos nativos: "ativo", "negado", "pendente" ou "fora do app".
pub fn status() -> String {
    if !bundled() {
        return "fora do app".into();
    }
    match AUTH.load(Ordering::SeqCst) {
        1 => "ativo".into(),
        2 => {
            let error = AUTH_ERROR.lock().map(|e| e.clone()).unwrap_or_default();
            if error.is_empty() { "negado".into() } else { format!("negado: {error}") }
        }
        _ => "pendente".into(),
    }
}

/// Estado da permissão perguntado ao macOS (o ajudante não pede: quem pede é o app aberto).
fn authorized_now() -> bool {
    let (tx, rx) = mpsc::channel::<bool>();
    let slot = Mutex::new(Some(tx));
    let block = RcBlock::new(move |settings: std::ptr::NonNull<UNNotificationSettings>| {
        let ok = matches!(
            unsafe { settings.as_ref() }.authorizationStatus(),
            UNAuthorizationStatus::Authorized | UNAuthorizationStatus::Provisional
        );
        if let Some(tx) = slot.lock().ok().and_then(|mut s| s.take()) {
            let _ = tx.send(ok);
        }
    });
    UNUserNotificationCenter::currentNotificationCenter().getNotificationSettingsWithCompletionHandler(&block);
    rx.recv_timeout(Duration::from_secs(3)).unwrap_or(false)
}

/// Manda o aviso e espera o macOS aceitar (até 3 s).
pub fn post(aviso: &Aviso) -> Result<(), String> {
    if !bundled() {
        return Err("fora do app".into());
    }
    let content = UNMutableNotificationContent::new();
    content.setTitle(&NSString::from_str(&clip(&aviso.titulo, 120)));
    if !aviso.subtitulo.is_empty() {
        content.setSubtitle(&NSString::from_str(&clip(&aviso.subtitulo, 120)));
    }
    content.setBody(&NSString::from_str(&clip(&aviso.texto, 300)));
    if aviso.som {
        content.setSound(Some(&UNNotificationSound::defaultSound()));
    }
    if !aviso.grupo.is_empty() {
        content.setThreadIdentifier(&NSString::from_str(&aviso.grupo));
    }
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    let id = format!("metis|{}|{now}", aviso.alvo.replace('|', ""));
    let request = UNNotificationRequest::requestWithIdentifier_content_trigger(&NSString::from_str(&id), &content, None);

    let (tx, rx) = mpsc::channel::<Option<String>>();
    let slot = Mutex::new(Some(tx));
    let block = RcBlock::new(move |error: *mut NSError| {
        if let Some(tx) = slot.lock().ok().and_then(|mut s| s.take()) {
            let _ = tx.send(error_text(error));
        }
    });
    UNUserNotificationCenter::currentNotificationCenter().addNotificationRequest_withCompletionHandler(&request, Some(&block));
    // Sem resposta do macOS em 5 s, conta como falha: quem chamou cai no aviso pelo osascript
    // (melhor um aviso repetido do que nenhum).
    match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(None) => Ok(()),
        Ok(Some(error)) => Err(error),
        Err(_) => Err("o macOS não respondeu ao aviso".into()),
    }
}

fn clip(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_string();
    }
    let mut out: String = text.chars().take(max - 1).collect();
    out.push('…');
    out
}

/// `harness --aviso '<json>'`: o núcleo avisa pelo app com a janela fechada. Sai com 0 se o
/// macOS aceitou; 2 fora de um `.app`, 3 sem permissão, 4 erro (o núcleo cai no osascript).
pub fn helper(json: &str) -> i32 {
    if !bundled() {
        return 2;
    }
    let Ok(aviso) = serde_json::from_str::<Aviso>(json) else { return 4 };
    if !authorized_now() {
        return 3;
    }
    match post(&aviso) {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("metis --aviso: {error}");
            4
        }
    }
}

#[tauri::command]
pub async fn notify_native(aviso: Aviso) -> Result<(), String> {
    match AUTH.load(Ordering::SeqCst) {
        1 => post(&aviso),
        _ => Err(status()),
    }
}

/// O alvo do clique que ainda não foi tratado (e esquece): a janela pergunta ao carregar.
#[tauri::command]
pub fn notify_pending() -> Option<String> {
    PENDING.lock().ok().and_then(|mut slot| slot.take())
}

#[tauri::command]
pub fn notify_status() -> String {
    status()
}

/// O executável do app, para o núcleo avisar por ele com a janela fechada ("" fora de um `.app`).
#[tauri::command]
pub fn app_exe() -> String {
    if !bundled() {
        return String::new();
    }
    std::env::current_exe().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default()
}
