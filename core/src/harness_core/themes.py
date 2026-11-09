"""Temas de terminal de outros apps (v0.9.8): Ghostty, Kitty e Warp, num ITheme do xterm.

O Ghostty continua no ghostty.py (o embutido e o config dele). Aqui entram os outros dois
formatos e a lista junta, para a tela de Aparência importar de qualquer um, e o leitor de
texto colado, que descobre o formato sozinho.

- Kitty (.conf): linhas "chave valor": color0..color15, background, foreground, cursor,
  cursor_text_color, selection_background, selection_foreground. Temas em
  ~/.config/kitty/themes/*.conf e o tema em uso em ~/.config/kitty/current-theme.conf.
- Warp (YAML): background, foreground, accent (vira o cursor) e terminal_colors com normal e
  bright, cada um com black, red, green, yellow, blue, magenta, cyan e white. Temas em
  ~/.warp/themes/**/*.yaml. O YAML desses temas é simples: um leitor pequeno basta.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import ghostty
from .ghostty import ANSI, GhosttyError, ThemeNotFound, _color, to_xterm

FORMATS = ("ghostty", "kitty", "warp")
KITTY_CURRENT = "Kitty em uso"
NAMES = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
KITTY_KEYS = {
    "background": "background",
    "foreground": "foreground",
    "cursor": "cursor",
    "cursor_text_color": "cursorAccent",
    "selection_background": "selectionBackground",
    "selection_foreground": "selectionForeground",
}


def kitty_theme_dirs() -> list[Path]:
    return [Path.home() / ".config" / "kitty" / "themes"]


def kitty_current_files() -> list[Path]:
    return [Path.home() / ".config" / "kitty" / "current-theme.conf"]


def warp_theme_dirs() -> list[Path]:
    return [Path.home() / ".warp" / "themes"]


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > ghostty.MAX_BYTES:
            raise GhosttyError("o tema passa de 200 KB")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ThemeNotFound(path.name) from exc


# --- leitores ------------------------------------------------------------------------------


def read_kitty(text: str) -> dict[str, str]:
    colors: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        key, value = parts[0], parts[1].strip()
        parsed = _color(value)
        if not parsed:
            continue
        match = re.fullmatch(r"color(\d{1,2})", key)
        if match and int(match.group(1)) <= 15:
            colors[ANSI[int(match.group(1))]] = parsed
        elif key in KITTY_KEYS:
            colors[KITTY_KEYS[key]] = parsed
    return colors


def _mini_yaml(text: str) -> dict:
    """Chave: valor com indentação (o bastante para os temas do Warp), sem listas."""
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, sep, value = raw.strip().partition(":")
        if not sep:
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root
        value = value.strip()
        if value[:1] in ("'", '"'):
            value = value[1:].split(value[0], 1)[0]
        else:
            value = value.split(" #", 1)[0].strip()
        if value:
            parent[key.strip()] = value
        else:
            child: dict = {}
            parent[key.strip()] = child
            stack.append((indent, child))
    return root


def read_warp(text: str) -> dict[str, str]:
    data = _mini_yaml(text)
    colors: dict[str, str] = {}
    for key, target in (("background", "background"), ("foreground", "foreground"), ("accent", "cursor")):
        parsed = _color(str(data.get(key, "")))
        if parsed:
            colors[target] = parsed
    terminal = data.get("terminal_colors") if isinstance(data.get("terminal_colors"), dict) else {}
    for group, prefix in (("normal", ""), ("bright", "bright")):
        block = terminal.get(group) if isinstance(terminal.get(group), dict) else {}
        for name in NAMES:
            parsed = _color(str(block.get(name, "")))
            if parsed:
                target = name if not prefix else f"bright{name.capitalize()}"
                colors[target] = parsed
    return colors


def detect(text: str) -> str:
    """O formato de um tema colado: o do Ghostty tem "palette =", o do Warp "terminal_colors:",
    o do Kitty linhas "colorN #..." ou "foreground #..." sem sinal de igual."""
    if re.search(r"^\s*palette\s*=", text, re.M):
        return "ghostty"
    if re.search(r"^\s*terminal_colors\s*:", text, re.M):
        return "warp"
    if re.search(r"^\s*(color\d{1,2}|foreground|background|cursor)\s+#?[0-9a-fA-F]{6}\b", text, re.M):
        return "kitty"
    return "ghostty"


def parse(text: str, fmt: str | None = None) -> tuple[str, dict[str, str]]:
    """(formato, ITheme) de um tema em qualquer dos três formatos."""
    if len(text.encode("utf-8")) > ghostty.MAX_BYTES:
        raise GhosttyError("o tema passa de 200 KB")
    fmt = fmt or detect(text)
    if fmt == "kitty":
        return fmt, to_xterm(read_kitty(text))
    if fmt == "warp":
        return fmt, to_xterm(read_warp(text))
    return "ghostty", to_xterm(ghostty.read_entries(text)[0])


# --- lista e leitura por nome ------------------------------------------------------------------


def _kitty_files() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for current in kitty_current_files():
        if current.is_file():
            found.setdefault(KITTY_CURRENT, current)
    for folder in kitty_theme_dirs():
        try:
            for path in sorted(folder.glob("*.conf")):
                found.setdefault(path.stem, path)
        except OSError:
            continue
    return found


def _warp_files() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for folder in warp_theme_dirs():
        try:
            for path in sorted(folder.rglob("*.yaml")) + sorted(folder.rglob("*.yml")):
                found.setdefault(path.stem, path)
        except OSError:
            continue
    return found


def list_all() -> list[dict]:
    """Os do Ghostty (como o /ghostty lista) e depois os do Kitty e do Warp, todos do usuário.
    Um nome que já apareceu ganha o formato entre parênteses."""
    items = [{**item, "formato": "ghostty"} for item in ghostty.list_themes()]
    taken = {item["nome"] for item in items}
    for fmt, files in (("kitty", _kitty_files()), ("warp", _warp_files())):
        for name in sorted(files, key=str.casefold):
            shown = name if name not in taken else f"{name} ({fmt})"
            taken.add(shown)
            items.append({"nome": shown, "origem": "usuario", "formato": fmt})
    return items


def load(name: str, fmt: str) -> dict[str, str]:
    """O ITheme de um tema da lista (aceita o nome com o formato entre parênteses)."""
    name = (name or "").strip()
    if fmt not in FORMATS:
        raise GhosttyError(f"formato de tema desconhecido: {fmt}")
    if fmt == "ghostty":
        return ghostty.load_theme(name)
    suffix = f" ({fmt})"
    raw = name[: -len(suffix)] if name.endswith(suffix) else name
    if not raw or "/" in raw or ".." in raw:
        raise GhosttyError("nome de tema inválido")
    files = _kitty_files() if fmt == "kitty" else _warp_files()
    path = files.get(raw)
    if path is None:
        raise ThemeNotFound(name)
    return parse(_read(path), fmt)[1]
