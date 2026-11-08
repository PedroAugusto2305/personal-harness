"""Quadros (v0.9.1): quadros livres por projeto, guardados como .canvas do Obsidian no vault.

Formato JSON Canvas 1.0 (jsoncanvas.org), o mesmo do Canvas do Obsidian: `nodes` (text, file,
link, group) e `edges`. O quadro mora na pasta do projeto no Brain
(01-PROJETOS/<Projeto>/quadros/<nome>.canvas) e abre no Obsidian também. Os cartões da MÊTIS
(sessão, tarefa do kanban) são nós "text" com um comentário `%%metis {...}%%` no fim, que o
Obsidian esconde e guarda ao salvar.

Salvar confere o mtime que a tela conhece: se o Obsidian salvou depois, a gravação é recusada
(BoardConflict) e a tela recarrega, para nunca apagar o que o Pedro mexeu por lá.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .brain_index import BrainIndex
from .vault import PROJECTS_DIR, Vault, VaultError, write_atomic

NODE_TYPES = ("text", "file", "link", "group")
SIDES = ("top", "right", "bottom", "left")
ENDS = ("none", "arrow")
BAD_NAME = re.compile(r'[\\/:*?"<>|#^\[\]]')
MAX_NODES = 2000


class BoardError(ValueError):
    pass


class BoardConflict(BoardError):
    pass


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize(canvas: Any) -> dict:
    """Confere a forma do JSON Canvas e devolve só o que vale (o resto do Obsidian é mantido)."""
    if not isinstance(canvas, dict):
        raise BoardError("o quadro precisa ser um objeto com nodes e edges")
    nodes, ids = [], set()
    for raw in canvas.get("nodes") or []:
        if not isinstance(raw, dict) or raw.get("type") not in NODE_TYPES:
            continue
        node_id = str(raw.get("id") or "")
        if not node_id or node_id in ids:
            continue
        ids.add(node_id)
        node = dict(raw)  # propriedades que a MÊTIS não conhece seguem como estão
        node.update(
            id=node_id,
            x=round(_num(raw.get("x"))),
            y=round(_num(raw.get("y"))),
            width=max(40, round(_num(raw.get("width"), 260))),
            height=max(30, round(_num(raw.get("height"), 120))),
        )
        if node["type"] == "file" and not str(node.get("file") or "").strip():
            raise BoardError(f"o cartão {node_id} aponta para uma nota sem caminho")
        if node["type"] == "link" and not str(node.get("url") or "").strip():
            raise BoardError(f"o cartão {node_id} é um link sem endereço")
        nodes.append(node)
    if len(nodes) > MAX_NODES:
        raise BoardError(f"um quadro aceita até {MAX_NODES} cartões")
    edges, edge_ids = [], set()
    for raw in canvas.get("edges") or []:
        if not isinstance(raw, dict):
            continue
        edge_id = str(raw.get("id") or "")
        if not edge_id or edge_id in edge_ids or raw.get("fromNode") not in ids or raw.get("toNode") not in ids:
            continue  # ligação para cartão que não existe mais: some sem barulho
        edge_ids.add(edge_id)
        edge = dict(raw)
        for key, allowed in (("fromSide", SIDES), ("toSide", SIDES), ("fromEnd", ENDS), ("toEnd", ENDS)):
            if key in edge and edge[key] not in allowed:
                edge.pop(key)
        edges.append(edge)
    extra = {k: v for k, v in canvas.items() if k not in ("nodes", "edges")}
    return {"nodes": nodes, "edges": edges, **extra}


class BoardStore:
    def __init__(self, vault: Vault, brain: BrainIndex) -> None:
        self.vault = vault
        self.brain = brain

    @property
    def base(self) -> Path:
        return self.vault.root / PROJECTS_DIR

    def _path(self, rel: str) -> Path:
        if not rel.endswith(".canvas"):
            raise BoardError("quadro é um arquivo .canvas")
        if Path(rel).parts[:1] != (PROJECTS_DIR,):
            raise BoardError("quadros moram na pasta de um projeto (01-PROJETOS)")
        root = self.vault.root.resolve()
        path = (root / rel).resolve()
        if not str(path).startswith(str(root) + "/"):
            raise BoardError(f"quadro fora do vault: {rel}")
        return path

    def _summary(self, path: Path, canvas: dict | None = None) -> dict:
        rel = path.resolve().relative_to(self.vault.root.resolve()).as_posix()
        parts = Path(rel).parts
        project = parts[1] if len(parts) > 2 else None
        if canvas is None:
            try:
                canvas = json.loads(path.read_text(encoding="utf-8") or "{}")
            except (OSError, ValueError):
                canvas = {}
        nodes = canvas.get("nodes") if isinstance(canvas, dict) else None
        return {"path": rel, "nome": path.stem, "projeto": project, "itens": len(nodes or []), "alterado": path.stat().st_mtime}

    def list(self) -> list[dict]:
        if not self.base.is_dir():
            return []
        items = [self._summary(p) for p in self.base.rglob("*.canvas") if not any(part.startswith(".") for part in p.parts)]
        return sorted(items, key=lambda b: ((b["projeto"] or "").lower(), b["nome"].lower()))

    def create(self, project: str, name: str) -> dict:
        name = " ".join(BAD_NAME.sub(" ", name).split()).strip(" .")
        if not name:
            raise BoardError("dê um nome ao quadro")
        if not self.vault.available:
            raise BoardError("o vault do Brain não está disponível")
        try:
            note = self.vault.project(project)
            folder = note.path.parent
        except VaultError as exc:
            raise BoardError(str(exc)) from exc
        target = folder / "quadros" / f"{name}.canvas"
        if target.exists():
            raise BoardError(f"já existe um quadro {name} em {project}")
        target.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(target, json.dumps({"nodes": [], "edges": []}, ensure_ascii=False, indent="\t") + "\n")
        return self._summary(target)

    def notes_for(self, canvas: dict) -> dict[str, dict | None]:
        paths = [n["file"] for n in canvas["nodes"] if n["type"] == "file" and str(n.get("file", "")).endswith(".md")]
        return self.brain.notes_by_path(paths)

    def read(self, rel: str) -> dict:
        path = self._path(rel)
        if not path.exists():
            raise BoardError("quadro não encontrado")
        try:
            raw = json.loads(path.read_text(encoding="utf-8") or "{}")
        except ValueError as exc:
            raise BoardError(f"{path.name} não é um JSON Canvas válido: {exc}") from exc
        canvas = normalize(raw)
        return {**self._summary(path, canvas), "canvas": canvas, "notas": self.notes_for(canvas)}

    def save(self, rel: str, canvas: Any, base: float) -> dict:
        path = self._path(rel)
        if not path.exists():
            raise BoardError("quadro não encontrado")
        current = path.stat().st_mtime
        if base and current > base + 0.001:
            raise BoardConflict("o quadro mudou no Obsidian depois que a tela abriu; recarregue")
        data = normalize(canvas)
        write_atomic(path, json.dumps(data, ensure_ascii=False, indent="\t") + "\n")
        return {"alterado": path.stat().st_mtime, "notas": self.notes_for(data)}
