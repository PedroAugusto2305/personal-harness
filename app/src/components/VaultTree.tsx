import { useEffect, useMemo, useRef, useState } from "react";
import type { CoreClient } from "../lib/core";
import type { VaultNode } from "../types";

/**
 * Árvore do vault (v0.9.9), como a barra de arquivos do Obsidian: pastas que abrem e fecham
 * (lembradas por tela) e notas que abrem ao clicar. A nota aberta fica marcada e as pastas
 * dela se abrem sozinhas.
 */

interface Props {
  client: CoreClient | null;
  tick: number;
  /** Caminho da nota aberta (relativo ao vault). */
  current: string | null;
  onOpen: (path: string) => void;
  /** Chave para lembrar as pastas abertas (cada tela a sua). */
  storageKey: string;
  /** Pastas abertas na primeira vez. */
  initialOpen?: string[];
  /** Esconde estes caminhos de topo (ex.: o Estudo esconde 03-RECURSOS). */
  hide?: string[];
}

function readOpen(key: string, fallback: string[]): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    return new Set(raw ? (JSON.parse(raw) as string[]) : fallback);
  } catch {
    return new Set(fallback);
  }
}

const ancestors = (path: string) => {
  const parts = path.split("/");
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
};

export function VaultTree({ client, tick, current, onOpen, storageKey, initialOpen = ["01-PROJETOS"], hide = [] }: Props) {
  const [tree, setTree] = useState<VaultNode[] | null>(null);
  const [open, setOpen] = useState<Set<string>>(() => readOpen(storageKey, initialOpen));

  // A primeira leitura é na hora; depois, uma rajada de mudanças no Brain (cada tarefa movida
  // avisa) vira uma leitura só, 1,5 s depois da última.
  const loaded = useRef(false);
  useEffect(() => {
    if (!client) return;
    let alive = true;
    const read = () =>
      client
        .brainTree()
        .then((t) => alive && setTree(t))
        .catch(() => alive && setTree([]));
    const timer = window.setTimeout(read, loaded.current ? 1500 : 0);
    loaded.current = true;
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [client, tick]);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify([...open]));
    } catch {
      // sem armazenamento: só não lembra
    }
  }, [open, storageKey]);

  // A nota aberta: as pastas dela abrem.
  useEffect(() => {
    if (!current) return;
    setOpen((prev) => {
      const missing = ancestors(current).filter((a) => !prev.has(a));
      return missing.length ? new Set([...prev, ...missing]) : prev;
    });
  }, [current]);

  const visible = useMemo(() => (tree ?? []).filter((n) => !hide.includes(n.caminho)), [tree, hide]);
  const toggle = (path: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const render = (nodes: VaultNode[], depth: number): React.ReactNode =>
    nodes.map((node) => {
      const pad = { paddingLeft: 8 + depth * 14 };
      if (node.tipo === "pasta") {
        const isOpen = open.has(node.caminho);
        return (
          <div key={node.caminho} role="group">
            <button type="button" className="vt-row vt-folder" style={pad} aria-expanded={isOpen} onClick={() => toggle(node.caminho)} title={node.caminho}>
              <span className="vt-chev" aria-hidden="true">
                {isOpen ? "⌄" : "›"}
              </span>
              <span className="vt-name">{node.nome}</span>
            </button>
            {isOpen && node.filhos && render(node.filhos, depth + 1)}
          </div>
        );
      }
      return (
        <button
          key={node.caminho}
          type="button"
          className="vt-row vt-note"
          style={pad}
          aria-current={node.caminho === current ? "true" : undefined}
          onClick={() => onOpen(node.caminho)}
          title={node.caminho}
        >
          <span className="vt-chev" aria-hidden="true" />
          <span className="vt-name">{node.nome}</span>
        </button>
      );
    });

  return (
    <nav className="vt" aria-label="Arquivos do Brain">
      {tree === null ? <span className="vt-empty">lendo o vault…</span> : visible.length ? render(visible, 0) : <span className="vt-empty">Vault vazio ou fora do lugar.</span>}
    </nav>
  );
}
