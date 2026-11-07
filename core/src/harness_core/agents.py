"""Agentes em arquivo: um `.md` por agente, com os campos no topo e o papel no corpo.

    ---
    nome: Aurora
    descricao: Coach de Estudo
    cli: claude
    modelo:
    conta:
    pasta: ~/Documents/Brain
    cor: "#AF52DE"
    ---
    Você é o coach de constância do Pedro...

Ficam em ~/.harness/agentes/. Tudo é editável, inclusive os importados, e a sprite é
um PNG em ~/.harness/agentes/sprites/<id>.png. Apagar manda o arquivo para .lixeira.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .accounts import slugify

CLIS = ("claude", "codex")
FIELDS = ("nome", "descricao", "cli", "modelo", "conta", "pasta", "cor", "origem")
MAX_SPRITE_BYTES = 2 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class AgentError(ValueError):
    pass


@dataclass
class Agent:
    id: str
    name: str
    description: str = ""
    cli: str = "claude"
    model: str = ""
    account: str = ""
    folder: str = ""
    color: str = "#82a0ff"
    origin: str = ""
    prompt: str = ""
    sprite: bool = False
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def parse_agent(text: str) -> tuple[dict[str, str], str]:
    """Campos do topo (uma linha cada, valor cru ou entre aspas) e o corpo."""
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            header = text[4:end]
            body = text[end + 4 :].lstrip("\n")
            for line in header.splitlines():
                key, sep, value = line.partition(":")
                if not sep:
                    continue
                value = value.strip()
                if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        value = value[1:-1]
                meta[key.strip()] = value
    return meta, body.rstrip() + ("\n" if body.strip() else "")


def render_agent(meta: dict[str, str], body: str) -> str:
    lines = ["---"]
    for key in FIELDS:
        value = str(meta.get(key, "") or "")
        needs_quotes = value != value.strip() or any(c in value for c in ':#"\n') or value.startswith(("'", "[", "{"))
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False) if needs_quotes else value}".rstrip())
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


class AgentStore:
    def __init__(self, home: Path) -> None:
        self.dir = home / "agentes"
        self.sprites = self.dir / "sprites"

    def _file(self, agent_id: str) -> Path:
        if not agent_id or agent_id != slugify(agent_id):
            raise AgentError(f"id de agente inválido: {agent_id}")
        return self.dir / f"{agent_id}.md"

    def _read(self, path: Path) -> Agent:
        meta, body = parse_agent(path.read_text(encoding="utf-8"))
        agent_id = path.stem
        sprite = self.sprites / f"{agent_id}.png"
        cli = meta.get("cli", "claude")
        return Agent(
            id=agent_id,
            name=meta.get("nome") or agent_id,
            description=meta.get("descricao", ""),
            cli=cli if cli in CLIS else "claude",
            model=meta.get("modelo", ""),
            account=meta.get("conta", ""),
            folder=meta.get("pasta", ""),
            color=meta.get("cor") or "#82a0ff",
            origin=meta.get("origem", ""),
            prompt=body.strip(),
            sprite=sprite.is_file(),
            # A sprite conta: trocar só a imagem também muda a versão (a URL da imagem usa isso).
            updated_at=max(path.stat().st_mtime, sprite.stat().st_mtime if sprite.is_file() else 0),
        )

    def list(self) -> list[dict]:
        if not self.dir.is_dir():
            return []
        agents = []
        for path in sorted(self.dir.glob("*.md")):
            try:
                agents.append(self._read(path).to_dict())
            except (OSError, UnicodeDecodeError):
                continue
        return sorted(agents, key=lambda a: a["name"].lower())

    def get(self, agent_id: str) -> Agent:
        path = self._file(agent_id)
        if not path.is_file():
            raise AgentError(f"agente não encontrado: {agent_id}")
        return self._read(path)

    def save(self, data: dict, agent_id: str | None = None) -> Agent:
        name = str(data.get("name", "")).strip()
        if not name:
            raise AgentError("o agente precisa de um nome")
        cli = data.get("cli", "claude")
        if cli not in CLIS:
            raise AgentError(f"CLI desconhecida: {cli}")
        if agent_id is None:
            base = slugify(name)
            agent_id, n = base, 2
            while self._file(agent_id).exists():
                agent_id, n = f"{base}-{n}", n + 1
        path = self._file(agent_id)
        previous = parse_agent(path.read_text(encoding="utf-8"))[0] if path.exists() else {}
        meta = {
            "nome": name,
            "descricao": str(data.get("description", "")).strip(),
            "cli": cli,
            "modelo": str(data.get("model", "")).strip(),
            "conta": str(data.get("account", "")).strip(),
            "pasta": str(data.get("folder", "")).strip(),
            "cor": str(data.get("color", "") or "#82a0ff").strip(),
            "origem": previous.get("origem", "") or str(data.get("origin", "")).strip(),
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(render_agent(meta, str(data.get("prompt", ""))), encoding="utf-8")
        tmp.replace(path)
        return self._read(path)

    def delete(self, agent_id: str) -> None:
        path = self._file(agent_id)
        if not path.is_file():
            raise AgentError(f"agente não encontrado: {agent_id}")
        trash = self.dir / ".lixeira"
        trash.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.move(str(path), trash / f"{agent_id}-{stamp}.md")
        sprite = self.sprites / f"{agent_id}.png"
        if sprite.exists():
            shutil.move(str(sprite), trash / f"{agent_id}-{stamp}.png")

    # --- sprite ------------------------------------------------------------

    def set_sprite(self, agent_id: str, png: bytes) -> None:
        self.get(agent_id)
        if not png.startswith(PNG_MAGIC):
            raise AgentError("a sprite precisa ser um PNG")
        if len(png) > MAX_SPRITE_BYTES:
            raise AgentError("sprite grande demais (máximo 2 MB)")
        self.sprites.mkdir(parents=True, exist_ok=True)
        (self.sprites / f"{agent_id}.png").write_bytes(png)

    def clear_sprite(self, agent_id: str) -> None:
        (self.sprites / f"{self.get(agent_id).id}.png").unlink(missing_ok=True)

    def sprite_path(self, agent_id: str) -> Path | None:
        path = self.sprites / f"{self.get(agent_id).id}.png"
        return path if path.is_file() else None

    # --- importação do Maestri ---------------------------------------------

    def import_maestri(self, roles_dir: Path, maestri_home: Path | None = None) -> list[Agent]:
        """Cada papel (`role.json`) vira um agente. O nome vem do terminal do Maestri que
        usa o papel (o codinome), e a pasta e a CLI também; sem terminal, fica o nome do papel."""
        terminals = _maestri_terminals(maestri_home or Path.home() / ".maestri")
        imported: list[Agent] = []
        existing = {a["origin"] for a in self.list() if a["origin"]}
        for role_file in sorted(roles_dir.glob("*/role.json")):
            try:
                role = json.loads(role_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            role_id = str(role.get("id", role_file.parent.name)).upper()
            origin = f"maestri:{role_id}"
            if origin in existing or not role.get("prompt"):
                continue
            terminal = terminals.get(role_id, {})
            command = str(terminal.get("command", "claude")).split()[0]
            agent = self.save(
                {
                    "name": terminal.get("name") or role.get("name"),
                    "description": role.get("name", ""),
                    "cli": command if command in CLIS else "claude",
                    "folder": terminal.get("workingDirectory") or str(roles_dir.parent.parent),
                    "color": role.get("color") or "#82a0ff",
                    "origin": origin,
                    "prompt": role["prompt"],
                }
            )
            imported.append(agent)
        return imported


def _maestri_terminals(maestri_home: Path) -> dict[str, dict]:
    found: dict[str, dict] = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            role_id = node.get("assignedRoleId")
            if role_id and node.get("name"):
                found.setdefault(str(role_id).upper(), node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for workspace in (maestri_home / "workspaces").glob("*/workspace.json"):
        try:
            walk(json.loads(workspace.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return found


def agent_args(agent: Agent) -> list[str]:
    """Argumentos extras da CLI para o papel e o modelo do agente."""
    args: list[str] = []
    if agent.cli == "claude":
        if agent.model:
            args += ["--model", agent.model]
        args += ["-n", agent.name]
        if agent.prompt:
            args += ["--append-system-prompt", agent.prompt]
    else:
        if agent.model:
            args += ["-m", agent.model]
        if agent.prompt:
            # O -c do Codex lê o valor como TOML; string JSON sem DEL é string TOML válida.
            text = json.dumps(agent.prompt.replace("\x7f", ""), ensure_ascii=False)
            args += ["-c", f"developer_instructions={text}"]
    return args
