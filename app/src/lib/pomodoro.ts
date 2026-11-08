// Pomodoro da MÊTIS: vive no App (continua ao trocar de tela) e sobrevive a uma recarga.
// Cada foco terminado vira um bloco no núcleo, que escreve a linha na nota do dia do Brain.
import { useCallback, useEffect, useRef, useState } from "react";
import type { CoreClient } from "./core";

export type Phase = "idle" | "focus" | "break";

export interface PomodoroState {
  phase: Phase;
  endsAt: number | null;
  startedAt: number | null;
  subject: string;
  focusMin: number;
  breakMin: number;
}

const KEY = "metis.pomodoro";
const IDLE: PomodoroState = { phase: "idle", endsAt: null, startedAt: null, subject: "", focusMin: 25, breakMin: 5 };

function load(): PomodoroState {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return saved && typeof saved === "object" ? { ...IDLE, ...saved } : IDLE;
  } catch {
    return IDLE;
  }
}

function save(state: PomodoroState) {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // sem armazenamento: o temporizador vale só nesta janela
  }
}

/** Um sino curto, sem arquivo de áudio. `volume` vai de 0 a 1 (os avisos usam o dos Ajustes). */
export function chime(times = 2, volume = 1) {
  const peak = 0.25 * Math.max(0, Math.min(1, volume));
  if (peak < 0.001) return; // volume zero: nada a tocar (a rampa exponencial não chega a 0)
  try {
    const ctx = new AudioContext();
    for (let i = 0; i < times; i += 1) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880 - i * 220;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + i * 0.35);
      gain.gain.exponentialRampToValueAtTime(peak, ctx.currentTime + i * 0.35 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i * 0.35 + 0.3);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + i * 0.35);
      osc.stop(ctx.currentTime + i * 0.35 + 0.32);
    }
    window.setTimeout(() => void ctx.close(), 1200);
  } catch {
    // sem áudio: o aviso na tela basta
  }
}

export function usePomodoro(client: CoreClient | null, onEvent: (message: string) => void) {
  const [state, setState] = useState<PomodoroState>(load);
  const [now, setNow] = useState(() => Date.now());
  const live = useRef({ state, client, onEvent });
  live.current = { state, client, onEvent };

  const update = useCallback((next: PomodoroState) => {
    save(next);
    setState(next);
  }, []);

  const logBlock = useCallback(async (minutes: number, subject: string) => {
    const { client: core, onEvent: notify } = live.current;
    if (!core || minutes < 1) return;
    try {
      const block = await core.studyBlock(Math.round(minutes * 10) / 10, subject);
      notify(`🍅 ${Math.round(minutes)} min registrados${block.note ? ` em ${block.note}` : ""}.`);
    } catch (cause) {
      notify(`Não registrei o bloco: ${cause instanceof Error ? cause.message : String(cause)}`);
    }
  }, []);

  // Relógio de 1 s só enquanto algo corre; ao vencer, troca de fase.
  useEffect(() => {
    if (state.phase === "idle") return;
    const timer = window.setInterval(() => {
      const t = Date.now();
      setNow(t);
      const s = live.current.state;
      if (s.endsAt == null || t < s.endsAt) return;
      if (s.phase === "focus") {
        chime(3);
        void logBlock(s.focusMin, s.subject);
        update({ ...s, phase: "break", startedAt: t, endsAt: t + s.breakMin * 60000 });
        live.current.onEvent(`Foco de ${s.focusMin} min concluído. Pausa de ${s.breakMin} min.`);
      } else {
        chime(2);
        update({ ...s, phase: "idle", startedAt: null, endsAt: null });
        live.current.onEvent("A pausa acabou. Mais um bloco?");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [state.phase, logBlock, update]);

  const start = (subject: string, focusMin = state.focusMin, breakMin = state.breakMin) => {
    const t = Date.now();
    update({ phase: "focus", startedAt: t, endsAt: t + focusMin * 60000, subject: subject.trim(), focusMin, breakMin });
  };

  /** Para antes da hora: foco de 5 min ou mais ainda conta, pelo tempo feito. */
  const stop = () => {
    const s = state;
    if (s.phase === "focus" && s.startedAt) {
      const done = (Date.now() - s.startedAt) / 60000;
      if (done >= 5) void logBlock(done, s.subject);
    }
    update({ ...s, phase: "idle", startedAt: null, endsAt: null });
  };

  const setDurations = (focusMin: number, breakMin: number) => update({ ...state, focusMin, breakMin });
  const remaining = state.endsAt ? Math.max(0, state.endsAt - now) : state.focusMin * 60000;
  const label = `${String(Math.floor(remaining / 60000)).padStart(2, "0")}:${String(Math.floor((remaining % 60000) / 1000)).padStart(2, "0")}`;
  return { state, remaining, label, start, stop, setDurations };
}

export type Pomodoro = ReturnType<typeof usePomodoro>;
