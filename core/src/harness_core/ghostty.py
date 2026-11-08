"""Temas do Ghostty para o terminal da MÊTIS (v0.9.3).

O Pedro usa no Orca o tema de terminal "Ghostty Default Style Dark", e este Mac nem tem o
Ghostty: por isso o tema vem embutido aqui, escrito no próprio formato do Ghostty, e passa
pelo mesmo leitor dos temas de fora. Com o Ghostty instalado, a MÊTIS também lista os temas
dele (os do app e os do usuário) e o que o config dele usa; dá ainda para colar um tema.

Formato (o mesmo do config): linhas "chave = valor", # comenta; palette = N=#rrggbb (0..15),
background, foreground, cursor-color, cursor-text, selection-background, selection-foreground.
A saída é o ITheme do xterm.js, que a interface aplica direto.
"""

from __future__ import annotations

import re
from pathlib import Path

BUILTIN_NAME = "Ghostty Default Style Dark"
CONFIG_THEME = "Configuração do Ghostty"
MAX_BYTES = 200 * 1024

BUILTIN: dict[str, str] = {
    BUILTIN_NAME: """\
# O padrão escuro do Ghostty, como o Orca mostra.
background = #282c34
foreground = #ffffff
cursor-color = #ffffff
cursor-text = #282c34
selection-background = #5a7898
selection-foreground = #ffffff
palette = 0=#1d1f21
palette = 1=#cc6666
palette = 2=#b5bd68
palette = 3=#f0c674
palette = 4=#81a2be
palette = 5=#b294bb
palette = 6=#8abeb7
palette = 7=#c5c8c6
palette = 8=#666666
palette = 9=#d54e53
palette = 10=#b9ca4a
palette = 11=#e7c547
palette = 12=#7aa6da
palette = 13=#c397d8
palette = 14=#70c0b1
palette = 15=#eaeaea
""",
}

ANSI = (
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
    "brightBlack", "brightRed", "brightGreen", "brightYellow", "brightBlue", "brightMagenta", "brightCyan", "brightWhite",
)
KEYS = {
    "background": "background",
    "foreground": "foreground",
    "cursor-color": "cursor",
    "cursor-text": "cursorAccent",
    "selection-background": "selectionBackground",
    "selection-foreground": "selectionForeground",
}
HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


class GhosttyError(ValueError):
    pass


class ThemeNotFound(KeyError):
    pass


def theme_dirs() -> list[tuple[Path, str]]:
    """Pastas de temas, na ordem de busca: a primeira que tiver o nome ganha."""
    home = Path.home()
    return [
        (home / ".config" / "ghostty" / "themes", "usuario"),
        (home / "Library" / "Application Support" / "com.mitchellh.ghostty" / "themes", "usuario"),
        (Path("/Applications/Ghostty.app/Contents/Resources/ghostty/themes"), "ghostty"),
        (home / "Applications" / "Ghostty.app" / "Contents" / "Resources" / "ghostty" / "themes", "ghostty"),
    ]


def config_files() -> list[Path]:
    """Onde o Ghostty procura o config; vale o primeiro que existir."""
    home = Path.home()
    support = home / "Library" / "Application Support" / "com.mitchellh.ghostty"
    return [
        home / ".config" / "ghostty" / "config",
        home / ".config" / "ghostty" / "config.ghostty",
        support / "config",
        support / "config.ghostty",
    ]


def _color(value: str) -> str | None:
    match = HEX.match(value.strip())
    return f"#{match.group(1).lower()}" if match else None


def read_entries(text: str) -> tuple[dict[str, str], str | None]:
    """As cores do texto (já com os nomes do xterm) e o valor de "theme", se houver."""
    colors: dict[str, str] = {}
    theme: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        value = value.strip().strip('"').strip("'")
        if key == "theme":
            theme = value or None
        elif key == "palette":
            index, _, color = value.partition("=")
            parsed = _color(color)
            if index.strip().isdigit() and 0 <= int(index) <= 15 and parsed:
                colors[ANSI[int(index)]] = parsed
        elif key in KEYS:
            parsed = _color(value)
            if parsed:
                colors[KEYS[key]] = parsed
    return colors, theme


def to_xterm(colors: dict[str, str]) -> dict[str, str]:
    """Completa o cursor (cor do texto) e o texto sob o cursor (fundo), quando faltam."""
    if not colors:
        raise GhosttyError("o tema não tem nenhuma cor (background, foreground ou palette)")
    out = dict(colors)
    if "cursor" not in out and "foreground" in out:
        out["cursor"] = out["foreground"]
    if "cursorAccent" not in out and "background" in out:
        out["cursorAccent"] = out["background"]
    return out


def parse_theme(text: str) -> dict[str, str]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise GhosttyError("o tema passa de 200 KB")
    return to_xterm(read_entries(text)[0])


def pick_theme(value: str | None) -> str | None:
    """"theme = light:A,dark:B" → B (o escuro); só light → A; nome simples → ele mesmo."""
    if not value:
        return None
    if ":" not in value or value.startswith(("/", "~")):
        return value
    parts = {}
    for piece in value.split(","):
        mode, _, name = piece.partition(":")
        if name.strip():
            parts[mode.strip().lower()] = name.strip()
    return parts.get("dark") or parts.get("light")


def find_config() -> Path | None:
    for path in config_files():
        if path.is_file():
            return path
    return None


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_BYTES:
            raise GhosttyError(f"{path.name} passa de 200 KB")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise GhosttyError(f"não deu para ler {path}: {exc}") from exc


def config_info() -> dict | None:
    path = find_config()
    if not path:
        return None
    try:
        colors, theme = read_entries(_read(path))
    except GhosttyError:
        return None
    return {"arquivo": str(path), "tema": pick_theme(theme), "cores_proprias": bool(colors)}


def _theme_file(name: str) -> Path | None:
    for folder, _origin in theme_dirs():
        path = folder / name
        if path.is_file():
            return path
    return None


def list_themes() -> list[dict]:
    """O embutido primeiro, o do config (se tiver cores próprias) e o resto por nome, sem repetir."""
    seen: dict[str, str] = {}
    for folder, origin in theme_dirs():
        try:
            names = [p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
        except OSError:
            continue
        for name in names:
            seen.setdefault(name, origin)
    head = [{"nome": name, "origem": "metis"} for name in BUILTIN]
    info = config_info()
    if info and info["cores_proprias"]:
        head.append({"nome": CONFIG_THEME, "origem": "usuario"})
    taken = {item["nome"] for item in head}
    rest = sorted((n for n in seen if n not in taken), key=str.casefold)
    return head + [{"nome": name, "origem": seen[name]} for name in rest]


def _load_named(name: str) -> dict[str, str]:
    """As cores cruas de um tema pelo nome (ou caminho, quando vem do config)."""
    if name in BUILTIN:
        return read_entries(BUILTIN[name])[0]
    if name.startswith(("/", "~")):
        path = Path(name).expanduser()
        if not path.is_file():
            raise ThemeNotFound(name)
        return read_entries(_read(path))[0]
    path = _theme_file(name)
    if not path:
        raise ThemeNotFound(name)
    return read_entries(_read(path))[0]


def load_theme(name: str) -> dict[str, str]:
    """O ITheme de um tema da lista; "Configuração do Ghostty" = tema do config com as cores dele por cima."""
    name = (name or "").strip()
    if not name or "/" in name or ".." in name or name.startswith("."):
        raise GhosttyError("nome de tema inválido")
    if name == CONFIG_THEME:
        path = find_config()
        if not path:
            raise ThemeNotFound(name)
        colors, theme = read_entries(_read(path))
        base: dict[str, str] = {}
        chosen = pick_theme(theme)
        if chosen:
            try:
                base = _load_named(chosen)
            except ThemeNotFound:
                base = {}
        merged = {**base, **colors}
        if not merged:
            raise ThemeNotFound(name)
        return to_xterm(merged)
    return to_xterm(_load_named(name))
