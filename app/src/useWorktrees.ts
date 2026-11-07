import { useCallback, useEffect, useState } from "react";
import type { CoreClient } from "./lib/core";
import type { Project, Session, Worktree } from "./types";

const POLL_MS = 15000;

/** Worktrees de cada projeto, com o número de mudanças e o quanto está à frente ou atrás. */
export function useWorktrees(client: CoreClient | null, projects: Project[], tick: number) {
  const [byProject, setByProject] = useState<Record<string, Worktree[]>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const ids = projects.map((p) => p.id).join(",");

  const refresh = useCallback(async () => {
    if (!client) return;
    const results = await Promise.all(
      projects.map(async (project) => {
        try {
          return [project.id, await client.worktrees(project.id), null] as [string, Worktree[], string | null];
        } catch (cause) {
          return [project.id, [], cause instanceof Error ? cause.message : String(cause)] as [string, Worktree[], string | null];
        }
      }),
    );
    setByProject(Object.fromEntries(results.map(([id, list]) => [id, list])));
    setErrors(Object.fromEntries(results.filter(([, , e]) => e).map(([id, , e]) => [id, e!])));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, ids]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh, tick]);

  return { byProject, errors, refresh };
}

export interface Place {
  project: Project;
  worktree: Worktree;
}

/** A worktree que contém a pasta (a mais funda, se uma estiver dentro da outra). */
export function placeOf(path: string, projects: Project[], byProject: Record<string, Worktree[]>): Place | null {
  let best: Place | null = null;
  for (const project of projects) {
    for (const worktree of byProject[project.id] ?? []) {
      const root = worktree.path.replace(/\/$/, "");
      if (path === root || path.startsWith(`${root}/`)) {
        if (!best || root.length > best.worktree.path.length) best = { project, worktree };
      }
    }
  }
  return best;
}

export function sessionsIn(path: string, sessions: Session[], projects: Project[], byProject: Record<string, Worktree[]>): Session[] {
  return sessions.filter((s) => placeOf(s.cwd, projects, byProject)?.worktree.path === path);
}

export function worktreeLabel(worktree: Worktree): string {
  return worktree.branch ?? worktree.path.split("/").pop() ?? worktree.path;
}
