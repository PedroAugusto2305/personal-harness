import type { CoreClient } from "../lib/core";
import type { Agent } from "../types";

/** Hash simples e estável do nome, para o desenho padrão não mudar entre aberturas. */
function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/**
 * Sprite padrão em pixel art 8×8, simétrica, na cor do agente. Vale até você trocar por
 * uma sua (PNG) no editor do agente; a geração pelo Codex chega com a tela de Agentes completa.
 */
export function PixelAvatar({ seed, color, size = 32 }: { seed: string; color: string; size?: number }) {
  const bits = hash(seed);
  const cells: [number, number][] = [];
  for (let y = 0; y < 8; y++) {
    for (let x = 0; x < 4; x++) {
      const on = (bits >>> ((y * 4 + x) % 32)) & 1;
      const ring = y === 0 || y === 7 || x === 0;
      if (on && !(ring && (y + x) % 2)) {
        cells.push([x, y], [7 - x, y]);
      }
    }
  }
  return (
    <svg className="pixel" width={size} height={size} viewBox="-1 -1 10 10" shapeRendering="crispEdges" aria-hidden="true">
      <rect x="-1" y="-1" width="10" height="10" rx="1.6" fill={`color-mix(in srgb, ${color} 16%, transparent)`} />
      {cells.map(([x, y]) => (
        <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill={color} />
      ))}
      <rect x="2" y="3" width="1" height="1" fill="var(--bg)" />
      <rect x="5" y="3" width="1" height="1" fill="var(--bg)" />
    </svg>
  );
}

export function AgentSprite({ agent, client, size = 32 }: { agent: Agent; client: CoreClient | null; size?: number }) {
  if (agent.sprite && client) {
    return (
      <img
        className="pixel sprite-img"
        src={client.spriteUrl(agent.id, agent.updated_at)}
        width={size}
        height={size}
        alt=""
        draggable={false}
      />
    );
  }
  return <PixelAvatar seed={agent.id + agent.name} color={agent.color} size={size} />;
}
