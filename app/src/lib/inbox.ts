// Avisos da MÊTIS (v0.9.2): o sino da barra de título guarda os últimos 50, o Dock mostra
// quantos faltam ler, e cada aviso novo toca o sino (janela em foco) ou vira notificação do
// macOS pela mão do núcleo (janela aberta, mas sem foco). Com a janela fechada, quem avisa é
// o próprio núcleo; aqui só chega o que acontece com ela aberta.
import { useCallback, useEffect, useRef, useState } from "react";
import { setDockBadge, type CoreClient } from "./core";
import { chime } from "./pomodoro";
import type { Prefs } from "../types";

/** As chaves batem com as de `Prefs["avisos"]`: cada tipo liga e desliga nos Ajustes. */
export type NoticeKind = "terminou" | "espera" | "aprovacao" | "erro";

export interface Notice {
  id: string;
  kind: NoticeKind;
  titulo: string;
  texto: string;
  /** Quando chegou (ms). */
  at: number;
  lido: boolean;
  /** Para onde o clique leva, quando dá: a sessão, a aprovação ou a automação. */
  sessao?: string;
  aprovacao?: string;
  automacao?: string;
}

export type NoticeInput = Omit<Notice, "id" | "at" | "lido">;

const KEY = "metis.avisos";
const MAX = 50;

/** Os mesmos padrões do núcleo, para antes de os Ajustes chegarem. */
export const DEFAULT_AVISOS: Prefs["avisos"] = {
  terminou: true,
  espera: true,
  aprovacao: true,
  erro: true,
  som: true,
  volume: 0.6,
  silencio: false,
};

function load(): Notice[] {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(saved) ? (saved as Notice[]).slice(0, MAX) : [];
  } catch {
    return [];
  }
}

function save(items: Notice[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    // sem armazenamento: os avisos valem só nesta janela
  }
}

export function useInbox(client: CoreClient | null, prefs: Prefs | null) {
  const [items, setItems] = useState<Notice[]>(load);
  const live = useRef({ client, prefs });
  live.current = { client, prefs };

  useEffect(() => save(items), [items]);

  const unread = items.filter((n) => !n.lido).length;
  const silent = !!prefs?.avisos.silencio;
  // Em silêncio, nem o número no Dock: o sino da janela continua anotando.
  useEffect(() => {
    void setDockBadge(silent ? 0 : unread);
  }, [unread, silent]);

  const push = useCallback((notice: NoticeInput) => {
    const { client: core, prefs: current } = live.current;
    const avisos = current?.avisos ?? DEFAULT_AVISOS;
    if (!avisos[notice.kind]) return; // esse tipo de aviso está desligado nos Ajustes
    const item: Notice = { ...notice, id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`, at: Date.now(), lido: false };
    setItems((all) => [item, ...all].slice(0, MAX));
    if (avisos.silencio) return;
    if (!document.hasFocus()) {
      // Janela sem foco: o núcleo mostra a notificação do macOS e toca o som (se ligado).
      void core?.notifyMac(notice.titulo.slice(0, 120), notice.texto.slice(0, 240)).catch(() => undefined);
    } else if (avisos.som) {
      // Esperar você e aprovação pedem duas notas; terminou e erro, uma.
      chime(notice.kind === "espera" || notice.kind === "aprovacao" ? 2 : 1, avisos.volume);
    }
  }, []);

  const markRead = useCallback((id: string) => setItems((all) => (all.some((n) => n.id === id && !n.lido) ? all.map((n) => (n.id === id ? { ...n, lido: true } : n)) : all)), []);

  /** Abrir a sessão já é ler o que ela avisou. */
  const markSession = useCallback(
    (sessao: string) =>
      setItems((all) => (all.some((n) => n.sessao === sessao && !n.lido) ? all.map((n) => (n.sessao === sessao ? { ...n, lido: true } : n)) : all)),
    [],
  );

  const markAllRead = useCallback(() => setItems((all) => (all.some((n) => !n.lido) ? all.map((n) => ({ ...n, lido: true })) : all)), []);

  const clear = useCallback(() => setItems([]), []);

  return { items, unread, push, markRead, markSession, markAllRead, clear };
}

export type Inbox = ReturnType<typeof useInbox>;
