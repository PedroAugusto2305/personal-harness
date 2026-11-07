import { useEffect, type ReactNode } from "react";

interface Props {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  extra?: ReactNode;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Confirmação dentro do app (o alert do navegador trava a janela do Tauri). */
export function Confirm({ title, children, confirmLabel, danger, busy, extra, onConfirm, onCancel }: Props) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="overlay center" onMouseDown={onCancel}>
      <div className="dialog" role="alertdialog" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        <div className="dialog-body">{children}</div>
        <div className="form-buttons">
          {extra}
          <span className="grow" />
          <button type="button" className="btn" onClick={onCancel}>
            Cancelar
          </button>
          <button type="button" className={`btn ${danger ? "danger" : "primary"}`} onClick={onConfirm} disabled={busy} autoFocus>
            {busy ? "Aguarde…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
