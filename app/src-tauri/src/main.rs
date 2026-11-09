// Evita a janela de console no Windows em release. Não remover.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // O núcleo avisa pelo app com a janela fechada: `harness --aviso '<json>'` (v0.9.9).
    let mut args = std::env::args().skip(1);
    if args.next().as_deref() == Some("--aviso") {
        std::process::exit(harness_lib::aviso_helper(&args.next().unwrap_or_default()));
    }
    harness_lib::run()
}
