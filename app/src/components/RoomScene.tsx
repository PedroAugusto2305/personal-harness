import { useEffect, useMemo, useRef, useState } from "react";
import sceneDay from "../assets/escritorio-dia.mp4";
import sceneNight from "../assets/escritorio-noite.mp4";
import type { CoreClient } from "../lib/core";
import type { Agent } from "../types";
import { AgentSprite, type SpriteState } from "./AgentSprite";

/**
 * A casa de trabalho dos agentes (v0.9.9, pedido do Pedro): o escritório animado dele, de dia
 * (6h às 18h) e de noite, cobrindo a sala inteira. Agente novo pega a primeira mesa livre e fica
 * nela, parado, com o movimento da própria sprite (respira e pisca) quando ela tem a tira de quadros.
 *
 * Arrastar deixa o agente onde ele for solto (livre no mapa); soltar perto de uma das 10 mesas com a
 * cadeira atrás encaixa nela (as pernas de quem tem corpo inteiro ficam atrás do móvel), e se a mesa
 * tinha dono os dois trocam. O lugar fica guardado nesta janela.
 *
 * Os pontos são em % da largura e da altura do desenho (3:2): nas mesas, a linha de cima do
 * móvel; na mesa do cristal, na mesa redonda, no piso e no lugar livre, os pés.
 *
 * O desenho final (2026-11-10) são os GIFs do Pedro `cenario_idle_loop_v3` (dia) e
 * `cenario_idle_loop_noite` (1024 × 683, 60 quadros, 4 s), no mesmo enquadramento do anterior.
 * Viraram H.264 a 15 qps com cada pixel dobrado sem suavizar (2048 × 1366), para o 4:2:0 do vídeo
 * cair em blocos de um pixel só e as cores não vazarem entre pixels vizinhos.
 */

export const SLOTS: { x: number; y: number; nome: string; mesa?: boolean }[] = [
  // Atrás de cada mesa, na linha de cima do móvel: o agente "trabalha" nela, com as pernas atrás da mesa.
  { x: 27, y: 21.5, nome: "mesa roxa do mezanino", mesa: true },
  { x: 50.5, y: 19, nome: "mesa vermelha do mezanino", mesa: true },
  { x: 75, y: 20.5, nome: "mesa do telescópio", mesa: true },
  { x: 22.5, y: 51.5, nome: "mesa vermelha da esquerda", mesa: true },
  // A cadeira da mesa do cristal fica na frente: o agente fica de pé diante dela.
  { x: 50.5, y: 53, nome: "mesa do cristal" },
  { x: 79, y: 51.5, nome: "mesa turquesa da direita", mesa: true },
  { x: 19.5, y: 67, nome: "mesa do globo", mesa: true },
  { x: 31.5, y: 83, nome: "mesa roxa de baixo", mesa: true },
  { x: 50, y: 84, nome: "mesa da pena", mesa: true },
  { x: 82, y: 67, nome: "mesa turquesa de baixo", mesa: true },
  { x: 68, y: 80, nome: "mesa das cartas", mesa: true },
  { x: 42.5, y: 61.5, nome: "mesa redonda" },
  { x: 56.5, y: 61.5, nome: "mesa redonda" },
  { x: 41, y: 69.5, nome: "mesa redonda" },
  { x: 57, y: 70.5, nome: "mesa redonda" },
  { x: 50, y: 76, nome: "mosaico" },
  { x: 11, y: 79, nome: "piso da esquerda" },
  { x: 89, y: 83, nome: "perto da fonte" },
];

const PLACES_KEY = "metis.sala.lugares";

type Point = { x: number; y: number };
/** Um dos lugares da lista (índice) ou um ponto livre do mapa (em % do desenho). */
export type Place = number | Point;

function isPoint(place: unknown): place is Point {
  return !!place && typeof place === "object" && Number.isFinite((place as Point).x) && Number.isFinite((place as Point).y);
}

function loadPlaces(): Record<string, Place> {
  try {
    const saved = JSON.parse(localStorage.getItem(PLACES_KEY) ?? "{}");
    return saved && typeof saved === "object" ? saved : {};
  } catch {
    return {};
  }
}

function savePlaces(places: Record<string, Place>) {
  try {
    localStorage.setItem(PLACES_KEY, JSON.stringify(places));
  } catch {
    // sem armazenamento: a arrumação vale só agora
  }
}

/** Lugar de cada agente: o guardado vale (lugar da lista ou ponto livre); quem não tem (agente
 * novo) ganha o primeiro lugar da lista que ninguém ocupa. */
export function placesFor(ids: string[], saved: Record<string, Place>): Record<string, Place> {
  const out: Record<string, Place> = {};
  const taken = new Set<number>();
  for (const id of ids) {
    const place = saved[id];
    if (isPoint(place)) {
      out[id] = place;
    } else if (typeof place === "number" && Number.isInteger(place) && place >= 0 && !taken.has(place)) {
      out[id] = place;
      taken.add(place);
    }
  }
  let next = 0;
  for (const id of ids) {
    if (id in out) continue;
    while (taken.has(next)) next++;
    out[id] = next;
    taken.add(next);
  }
  return out;
}

/** O desenho (3:2, a sala de ponta a ponta) é o vídeo inteiro; os lugares são em % dele. As medidas
 * aqui são unidades de um desenho de 1536 × 1024, qualquer que seja a resolução do vídeo (o ímã das
 * mesas, MAGNET, é nelas). O recorte fica para um desenho futuro que venha com margem. */
const FRAME = { w: 1536, h: 1024 };
const CROP = { x: 0, y: 0, w: 1536, h: 1024 };
const SCENE_W = CROP.w;
const SCENE_H = CROP.h;

function toCrop(p: { x: number; y: number }): { x: number; y: number } {
  return { x: (((p.x / 100) * FRAME.w - CROP.x) / CROP.w) * 100, y: (((p.y / 100) * FRAME.h - CROP.y) / CROP.h) * 100 };
}

/** Lugar além da lista (mais agentes que lugares): uma fileira no piso da frente. */
function slotPoint(index: number): { x: number; y: number; mesa?: boolean } {
  if (index < SLOTS.length) return { ...toCrop(SLOTS[index]), mesa: SLOTS[index].mesa };
  const extra = index - SLOTS.length;
  return toCrop({ x: 30 + (extra % 7) * 6.5, y: 85 + Math.floor(extra / 7) * 3 });
}

function placePoint(place: Place): Point & { mesa?: boolean } {
  return isPoint(place) ? { x: place.x, y: place.y } : slotPoint(place);
}

/** Até onde (em pixels do desenho) uma mesa puxa o agente solto perto dela. */
const MAGNET = 70;

/** A mesa mais perto do ponto, se ele caiu a menos de MAGNET dela; senão -1 (fica livre). */
function deskNear(point: Point): number {
  let best = -1;
  let bestD = MAGNET;
  SLOTS.forEach((slot, index) => {
    if (!slot.mesa) return;
    const p = slotPoint(index);
    const d = Math.hypot(((p.x - point.x) / 100) * SCENE_W, ((p.y - point.y) / 100) * SCENE_H);
    if (d < bestD) {
      best = index;
      bestD = d;
    }
  });
  return best;
}

/** Dia das 6h às 18h; o resto é noite. */
export function isDay(date = new Date()): boolean {
  const hour = date.getHours();
  return hour >= 6 && hour < 18;
}

export interface SceneAgent {
  agent: Agent;
  state: SpriteState;
  bubble: string;
  loud: boolean;
  color: string;
  status: string;
}

interface Props {
  client: CoreClient | null;
  items: SceneAgent[];
  selected: string | null;
  onSelect: (id: string) => void;
  onOpen: (agent: Agent) => void;
}

export function RoomScene({ client, items, selected, onSelect, onOpen }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [saved, setSaved] = useState(loadPlaces);
  const [day, setDay] = useState(isDay);
  const [drag, setDrag] = useState<{ id: string; x: number; y: number; moved: boolean } | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);

  const ids = useMemo(() => items.map((i) => i.agent.id), [items]);
  const places = useMemo(() => placesFor(ids, saved), [ids, saved]);

  // Agente novo ganhou lugar: fica guardado, para os outros não mudarem quando alguém sair.
  useEffect(() => {
    if (ids.some((id) => saved[id] !== places[id])) {
      const next = { ...saved, ...places };
      setSaved(next);
      savePlaces(next);
    }
  }, [ids, places, saved]);

  // Dia ou noite, conferido a cada minuto.
  useEffect(() => {
    const timer = window.setInterval(() => setDay(isDay()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // O desenho cobre a sala inteira (como object-fit: cover), centrado: o que sobra sai das bordas.
  const scale = size.w && size.h ? Math.max(size.w / SCENE_W, size.h / SCENE_H) : 0;
  const sw = SCENE_W * scale;
  const sh = SCENE_H * scale;
  const offset = { x: (size.w - sw) / 2, y: (size.h - sh) / 2 };
  const toScene = (event: { clientX: number; clientY: number }) => {
    const rect = box.current!.getBoundingClientRect();
    return { x: ((event.clientX - rect.left - offset.x) / sw) * 100, y: ((event.clientY - rect.top - offset.y) / sh) * 100 };
  };

  // Sprite própria (corpo inteiro) na escala dos móveis: 15% da altura do desenho, pouco menos que
  // duas cadeiras da mesa redonda (com 20% ela ficava do tamanho de três). O busto padrão, menor.
  const full = Math.max(56, Math.round(sh * 0.15));
  const bust = Math.max(32, Math.round(sh * 0.075));

  /** O ponto dentro do pedaço da sala que aparece (o desenho cobre a sala e pode sobrar das bordas),
   * com espaço para a sprite inteira acima dos pés e o nome embaixo. */
  const inView = (point: Point, px: number): Point => {
    const side = Math.max(24, px * 0.3);
    const x0 = ((-offset.x + side) / sw) * 100;
    const x1 = ((size.w - offset.x - side) / sw) * 100;
    const y0 = ((-offset.y + px + 6) / sh) * 100;
    const y1 = ((size.h - offset.y - 24) / sh) * 100;
    return { x: Math.min(Math.max(point.x, x0), x1), y: Math.min(Math.max(point.y, y0), y1) };
  };

  const drop = (id: string, point: Point) => {
    // Perto de uma mesa, encaixa nela (ocupada, os dois trocam); longe de todas, fica onde soltou.
    const desk = deskNear(point);
    const from = places[id];
    const next: Record<string, Place> = { ...saved, ...places };
    if (desk < 0) {
      next[id] = { x: Math.round(point.x * 100) / 100, y: Math.round(point.y * 100) / 100 };
    } else {
      next[id] = desk;
      const other = Object.keys(places).find((key) => key !== id && places[key] === desk);
      if (other) next[other] = from;
    }
    setSaved(next);
    savePlaces(next);
  };

  return (
    <div className="scene" ref={box} data-period={day ? "dia" : "noite"}>
      {scale > 0 && (
        <video
          key={day ? "dia" : "noite"}
          className="scene-video"
          src={day ? sceneDay : sceneNight}
          autoPlay
          muted
          loop
          playsInline
          style={{ left: offset.x, top: offset.y, width: sw, height: sh }}
        />
      )}
      {scale > 0 &&
        items.map((item) => {
          const id = item.agent.id;
          const home = placePoint(places[id] ?? 0);
          const dragging = drag?.id === id && drag.moved;
          const on = id === selected;
          const px = item.agent.sprite ? full : bust;
          const point = inView(dragging ? { x: drag.x, y: drag.y } : home, px);
          // Corpo inteiro numa mesa: as pernas ficam atrás do móvel (escondidas), como quem trabalha nela.
          const seated = !!home.mesa && item.agent.sprite && !dragging;
          const hidden = seated ? Math.round(px * 0.3) : 0;
          return (
            <button
              key={id}
              type="button"
              className="scene-agent"
              data-on={on ? "true" : undefined}
              data-dragging={dragging ? "true" : undefined}
              style={{
                left: offset.x + (point.x / 100) * sw,
                top: offset.y + (point.y / 100) * sh,
                zIndex: dragging ? 999 : Math.round(point.y * 10),
                ["--h" as string]: `${px - hidden}px`,
              }}
              aria-pressed={on}
              aria-label={`${item.agent.name}, ${item.status}. Ver agente`}
              title={`${item.agent.name} · ${item.status} · arraste para mudar de lugar`}
              onPointerDown={(event) => {
                if (event.button !== 0) return;
                start.current = { x: event.clientX, y: event.clientY };
                (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
                setDrag({ id, ...toScene(event), moved: false });
              }}
              onPointerMove={(event) => {
                if (!drag || drag.id !== id || !start.current) return;
                const movedNow = drag.moved || Math.hypot(event.clientX - start.current.x, event.clientY - start.current.y) > 5;
                setDrag({ id, ...toScene(event), moved: movedNow });
              }}
              onPointerUp={(event) => {
                const current = drag;
                setDrag(null);
                start.current = null;
                if (!current || current.id !== id) return;
                if (current.moved) drop(id, inView(toScene(event), px));
                else onSelect(id);
              }}
              onPointerCancel={() => {
                setDrag(null);
                start.current = null;
              }}
              onDoubleClick={() => onOpen(item.agent)}
            >
              {(item.loud || on || item.state === "working") && (
                <span className="scene-bubble" data-loud={item.loud ? "true" : undefined} style={item.loud ? { background: item.color } : undefined}>
                  {item.bubble}
                </span>
              )}
              <span className="scene-sprite" style={seated ? { bottom: -hidden, clipPath: `inset(0 0 ${hidden}px 0)` } : undefined}>
                <AgentSprite agent={item.agent} client={client} size={px} state={item.state} />
              </span>
              <span className="scene-name">{item.agent.name}</span>
            </button>
          );
        })}
    </div>
  );
}
