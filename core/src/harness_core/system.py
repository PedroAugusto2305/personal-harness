"""Peças de sistema da v0.9.2: Mac acordado, aviso do macOS, recursos e Skills.

- Mac acordado: um `caffeinate -i` que vive enquanto o ajuste pede (sempre, ou só com
  agente trabalhando ou automação rodando) e morre junto com o núcleo (`-w <pid>`).
- Aviso do macOS: quando nenhuma janela da MÊTIS está aberta, o próprio núcleo avisa: pelo
  executável do app (`--aviso`, com o ícone da MÊTIS, v0.9.9) ou, sem ele, pelo osascript
  (com o texto passado como argumento, nunca dentro do script).
- Recursos: memória e CPU do núcleo e de cada sessão (o processo e os filhos dele), por `ps`.
- Skills: as do usuário (~/.claude/skills, também das outras contas e ~/.codex/skills) e as
  do projeto (<pasta>/.claude/skills), com nome e descrição tirados do SKILL.md.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Iterable


class Awake:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None

    @property
    def active(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def apply(self, want: bool) -> bool:
        """Liga ou desliga o caffeinate; devolve se mudou."""
        if want and not self.active:
            try:
                self.proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                self.proc = None
                return False
            return True
        if not want and self.active:
            assert self.proc is not None
            self.proc.terminate()
            self.proc = None
            return True
        return False

    def stop(self) -> None:
        self.apply(False)


def wants_awake(mode: str, working_sessions: int, running_automations: int) -> bool:
    if mode == "sempre":
        return True
    if mode == "agente":
        return working_sessions > 0 or running_automations > 0
    return False


# v0.9.9: o executável da MÊTIS (dentro do .app), registrado pela janela. Com ele o aviso sai
# pelo próprio app (`--aviso`), com o ícone e o nome da MÊTIS; sem ele, pelo osascript.
_notifier = {"exe": ""}


def set_notifier(exe: str) -> bool:
    """Guarda o executável do app, se for mesmo um `<Nome>.app/Contents/MacOS/<bin>`; "" apaga."""
    path = Path(exe) if exe else None
    ok = bool(
        path
        and path.is_absolute()
        and path.is_file()
        and path.parent.name == "MacOS"
        and path.parent.parent.name == "Contents"
        and path.parent.parent.parent.suffix == ".app"
    )
    _notifier["exe"] = str(path) if ok else ""
    return ok


def notifier() -> str:
    return _notifier["exe"]


def _osascript_notify(title: str, text: str, sound: bool) -> None:
    script = [
        "on run argv",
        'display notification (item 2 of argv) with title (item 1 of argv)' + (' sound name "Glass"' if sound else ""),
        "end run",
    ]
    args = ["osascript"]
    for line in script:
        args += ["-e", line]
    try:
        subprocess.Popen([*args, title[:120], text[:240]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def _app_notify(exe: str, payload: dict, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool:
    """O app avisa e sai (0 = o macOS aceitou; 2 fora do .app, 3 sem permissão, 4 erro)."""
    try:
        done = run([exe, "--aviso", json.dumps(payload, ensure_ascii=False)], capture_output=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def mac_notify(title: str, text: str, sound: bool = True, target: str = "", group: str = "") -> None:
    """Aviso do macOS (Central de Notificações). Pelo app da MÊTIS quando a janela registrou o
    executável; senão pelo osascript, com título e texto como argumentos do script. Não trava
    quem chama: o aviso sai numa thread."""
    exe = _notifier["exe"]
    payload = {"titulo": title[:120], "texto": text[:300], "som": sound, "alvo": target, "grupo": group}

    def send() -> None:
        if exe and _app_notify(exe, payload):
            return
        _osascript_notify(title, text, sound)

    threading.Thread(target=send, name="aviso-mac", daemon=True).start()


def process_table(run: Callable[[list[str]], str] | None = None) -> dict[int, tuple[int, float, float, str]]:
    """pid → (ppid, memória em MB, CPU %, comando)."""
    run = run or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=5).stdout)
    table = {}
    for line in run(["ps", "-A", "-o", "pid=,ppid=,rss=,%cpu=,comm="]).splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        table[int(parts[0])] = (int(parts[1]), int(parts[2]) / 1024, float(parts[3].replace(",", ".")), parts[4] if len(parts) > 4 else "")
    return table


def tree_usage(table: dict[int, tuple[int, float, float, str]], root: int) -> dict:
    """Soma da memória e da CPU do processo e de todos os descendentes."""
    children: dict[int, list[int]] = {}
    for pid, (ppid, *_rest) in table.items():
        children.setdefault(ppid, []).append(pid)
    total_mb = total_cpu = 0.0
    count = 0
    todo = [root]
    names = []
    while todo:
        pid = todo.pop()
        if pid not in table:
            continue
        _ppid, mb, cpu, comm = table[pid]
        total_mb += mb
        total_cpu += cpu
        count += 1
        if comm and len(names) < 6:
            names.append(Path(comm).name)
        todo += children.get(pid, [])
    return {"mb": round(total_mb), "cpu": round(total_cpu, 1), "processos": count, "comandos": names}


FRONTMATTER = re.compile(r"\A---\n(.*?)\n---", re.S)


def frontmatter(text: str) -> dict[str, str]:
    """As chaves de primeiro nível do frontmatter, inclusive as em bloco (`description: >` ou `|`)."""
    meta: dict[str, str] = {}
    match = FRONTMATTER.match(text)
    if not match:
        return meta
    key = None
    block: list[str] | None = None
    for line in match.group(1).splitlines():
        if block is not None and (line.startswith((" ", "\t")) or not line.strip()):
            block.append(line.strip())
            continue
        if block is not None and key:
            meta[key] = " ".join(part for part in block if part)
        block = None
        if ":" in line and not line.startswith(" "):
            key, value = (part.strip() for part in line.split(":", 1))
            if value in (">", "|", ">-", "|-", ">+", "|+"):
                block = []
            else:
                meta[key] = value.strip('"').strip("'")
    if block is not None and key:
        meta[key] = " ".join(part for part in block if part)
    return meta


def _skill(path: Path, origin: str) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:6000]
    except OSError:
        return None
    meta = frontmatter(text)
    return {
        "nome": meta.get("name") or path.parent.name,
        "descricao": (meta.get("description") or "").replace("\\n", " ")[:400],
        "origem": origin,
        "pasta": str(path.parent),
        "arquivo": str(path),
    }


def list_skills(user_dirs: Iterable[Path], project_dir: str | None = None) -> list[dict]:
    found, seen = [], set()
    sources = [(d, "usuário") for d in user_dirs]
    if project_dir:
        sources.append((Path(project_dir) / ".claude" / "skills", "projeto"))
    for folder, origin in sources:
        if not folder.is_dir():
            continue
        for skill_file in sorted(folder.glob("*/SKILL.md")):
            real = skill_file.resolve()
            if real in seen:
                continue
            seen.add(real)
            item = _skill(skill_file, origin)
            if item:
                found.append(item)
    return found


# --- editores externos (v0.9.6) ------------------------------------------------------

EDITORS = {
    "code": ("Visual Studio Code", "Visual Studio Code.app"),
    "cursor": ("Cursor", "Cursor.app"),
    "zed": ("Zed", "Zed.app"),
    "sublime": ("Sublime Text", "Sublime Text.app"),
    "xcode": ("Xcode", "Xcode.app"),
}


def app_dirs() -> list[Path]:
    return [Path("/Applications"), Path.home() / "Applications"]


def find_editor(editor_id: str, dirs: Iterable[Path] | None = None) -> Path | None:
    entry = EDITORS.get(editor_id)
    if entry is None:
        return None
    for folder in dirs if dirs is not None else app_dirs():
        candidate = folder / entry[1]
        if candidate.is_dir():
            return candidate
    return None


def list_editors(dirs: Iterable[Path] | None = None) -> list[dict]:
    """Os editores conhecidos que estão instalados, para o "Abrir em"."""
    folders = list(dirs) if dirs is not None else app_dirs()
    return [{"id": key, "nome": name} for key, (name, _) in EDITORS.items() if find_editor(key, folders)]


def open_in(editor_id: str, path: str, dirs: Iterable[Path] | None = None, run: Callable[[list[str]], object] | None = None) -> None:
    """Abre a pasta ou o arquivo no editor (`open -a`), sem shell."""
    app = find_editor(editor_id, dirs)
    if app is None:
        raise ValueError(f"editor não instalado: {editor_id}")
    target = Path(path).expanduser()
    if not target.exists():
        raise ValueError(f"não existe: {path}")
    command = ["open", "-a", str(app), str(target)]
    if run is not None:
        run(command)
    else:
        subprocess.run(command, check=True, timeout=15)
