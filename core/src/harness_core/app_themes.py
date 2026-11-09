"""Temas da tela da MÊTIS (v0.9.8): criados por prompt ou importados do VS Code e do Obsidian.

Um tema é o conjunto de cores da interface (os mesmos papéis dos temas embutidos em
`app/src/styles.css`) e, quando a fonte tem, as cores do terminal. Fica em
~/.harness/temas/<id>.json:

    {"id", "nome", "base": "escuro"|"claro", "cores": {bar, side, bg, …}, "terminal": {…}|null,
     "origem": "prompt"|"vscode"|"obsidian", "fonte": str, "criado": iso, "ajustes": [str]}

Toda entrada passa por `ajustar`, que confere o contraste (WCAG) e mexe só na luminosidade
da cor que falha, anotando o que mudou.
"""

from __future__ import annotations

import colorsys
import contextlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .accounts import slugify

TOKENS = ("bar", "side", "bg", "elev", "line", "line2", "term", "tx", "mut", "fnt", "acc", "acct", "onacc", "run", "wait", "warn", "err", "sel")
ANSI = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
TERMINAL_KEYS = (
    "background",
    "foreground",
    "cursor",
    "cursorAccent",
    "selectionBackground",
    *ANSI,
    *("bright" + name.capitalize() for name in ANSI),
)
BASES = ("escuro", "claro")
ORIGINS = ("prompt", "vscode", "obsidian")
MAX_NAME = 60
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")

ROLES = {
    "bar": "barra de título e trilho de ícones (a faixa mais escura num tema escuro)",
    "side": "barra lateral e painéis",
    "bg": "fundo principal",
    "elev": "cartões e campos elevados sobre o fundo",
    "line": "borda fraca",
    "line2": "borda forte",
    "term": "fundo do terminal e do editor",
    "tx": "texto principal",
    "mut": "texto secundário",
    "fnt": "texto apagado e números de linha",
    "acc": "destaque: botão principal e foco",
    "acct": "texto em destaque e links",
    "onacc": "texto escrito sobre o destaque",
    "run": "agente trabalhando (um ciano, por exemplo)",
    "wait": "agente esperando você (um roxo, por exemplo)",
    "warn": "atenção (um rosa ou laranja)",
    "err": "erro (um vermelho)",
    "sel": "fundo da seleção de texto",
}


class ThemeError(ValueError):
    """Entrada inválida (400)."""


class ThemeGenError(RuntimeError):
    """O gerador (o Claude) devolveu algo que não vira tema (502)."""


class SourceNotFound(LookupError):
    pass


# --- cores -------------------------------------------------------------------------

RGB = tuple[float, float, float]
NAMED = {"white": "#ffffff", "black": "#000000", "transparent": "#00000000"}


def parse_hex(value: str) -> tuple[RGB, float] | None:
    match = re.fullmatch(r"#?([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", value.strip())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) in (3, 4):
        digits = "".join(c * 2 for c in digits)
    rgb = (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
    alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
    return (float(rgb[0]), float(rgb[1]), float(rgb[2])), alpha


def to_hex(rgb: RGB) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def rgb_of(color: str) -> RGB:
    parsed = parse_hex(color)
    if parsed is None:
        raise ThemeError(f"cor inválida: {color}")
    return parsed[0]


def blend(rgb: RGB, alpha: float, under: RGB) -> RGB:
    return (rgb[0] * alpha + under[0] * (1 - alpha), rgb[1] * alpha + under[1] * (1 - alpha), rgb[2] * alpha + under[2] * (1 - alpha))


def mix(a: str, b: str, t: float) -> str:
    """t = 0 é a, t = 1 é b."""
    return to_hex(blend(rgb_of(b), t, rgb_of(a)))


def luminance(color: str) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb_of(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _hls(color: str) -> tuple[float, float, float]:
    r, g, b = rgb_of(color)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)


def with_lightness(color: str, lightness: float) -> str:
    h, _, s = _hls(color)
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, lightness)), s)
    return to_hex((r * 255, g * 255, b * 255))


def lighten(color: str, amount: float) -> str:
    """amount > 0 clareia, < 0 escurece (na luminosidade do HSL)."""
    return with_lightness(color, _hls(color)[1] + amount)


def best_on(color: str, dark: str = "#14151b", light: str = "#ffffff") -> str:
    return dark if contrast(dark, color) >= contrast(light, color) else light


def normalize(color: Any) -> str | None:
    """#abc, #aabbcc ou nome simples → #aabbcc. Alfa é ignorado (use `solid`)."""
    if not isinstance(color, str):
        return None
    color = NAMED.get(color.strip().lower(), color)
    parsed = parse_hex(color)
    return to_hex(parsed[0]) if parsed else None


def solid(color: str | None, under: str) -> str | None:
    """Cor com alfa (#rrggbbaa) misturada sobre o fundo."""
    if not color:
        return None
    color = NAMED.get(color.strip().lower(), color)
    parsed = parse_hex(color)
    if parsed is None:
        return None
    rgb, alpha = parsed
    return to_hex(blend(rgb, alpha, rgb_of(under)) if alpha < 1 else rgb)


# --- montar e ajustar -----------------------------------------------------------------

DEFAULT_STATUS = {
    "escuro": {"run": "#8be9fd", "wait": "#bd93f9", "warn": "#ff79c6", "err": "#ff5555", "acc": "#82a0ff", "tx": "#f8f8f2"},
    "claro": {"run": "#0b7a8a", "wait": "#7c4dcc", "warn": "#c2367a", "err": "#d12f2f", "acc": "#4a63d6", "tx": "#1f2330"},
}


def complete(colors: dict[str, Any], base: str) -> dict[str, str]:
    """Todas as cores, derivando as que faltam do fundo, do texto e do destaque."""
    dark = base == "escuro"
    found = {key: normalize(colors.get(key)) for key in TOKENS}
    bg = found["bg"]
    if not bg:
        raise ThemeError("falta a cor de fundo (bg)")
    defaults = DEFAULT_STATUS[base]
    tx = found["tx"] or defaults["tx"]
    acc = found["acc"] or defaults["acc"]
    side = found["side"] or lighten(bg, -0.03)
    out = {
        "bg": bg,
        "tx": tx,
        "acc": acc,
        "side": side,
        "bar": found["bar"] or lighten(side, -0.03),
        "elev": found["elev"] or (lighten(bg, 0.05) if dark else mix(bg, tx, 0.05)),
        "line": found["line"] or mix(bg, tx, 0.12),
        "line2": found["line2"] or mix(bg, tx, 0.2),
        "term": found["term"] or lighten(bg, -0.02),
        "mut": found["mut"] or mix(tx, bg, 0.3),
        "fnt": found["fnt"] or mix(tx, bg, 0.5),
        "acct": found["acct"] or lighten(acc, 0.1 if dark else -0.1),
        "run": found["run"] or defaults["run"],
        "wait": found["wait"] or defaults["wait"],
        "warn": found["warn"] or defaults["warn"],
        "err": found["err"] or defaults["err"],
        "sel": found["sel"] or mix(bg, acc, 0.3),
    }
    out["onacc"] = found["onacc"] or best_on(acc, dark=out["bar"] if dark else "#14151b")
    return {key: out[key] for key in TOKENS}


def _push(color: str, bg: str, minimum: float) -> str:
    """A mesma cor, só mais clara ou mais escura, até dar o contraste com o fundo."""
    start = _hls(color)[1]
    best = color
    directions = (1, -1) if luminance(bg) < 0.18 else (-1, 1)
    for direction in directions:
        lightness = start
        candidate = color
        while 0.0 <= lightness <= 1.0:
            candidate = with_lightness(color, lightness)
            if contrast(candidate, bg) >= minimum:
                return candidate
            lightness += 0.02 * direction
        if contrast(candidate, bg) > contrast(best, bg):
            best = candidate
    return best


CHECKS = (
    ("tx", 7.0, "texto"),
    ("mut", 4.5, "texto secundário"),
    ("fnt", 3.0, "texto apagado"),
    ("acc", 3.0, "destaque"),
    ("run", 3.0, "cor de trabalhando"),
    ("wait", 3.0, "cor de esperando você"),
    ("warn", 3.0, "cor de atenção"),
    ("err", 3.0, "cor de erro"),
)


def adjust(theme: dict) -> dict:
    """`ajustar`: contraste mínimo de cada papel contra o fundo; anota cada mudança."""
    colors = dict(theme["cores"])
    notes: list[str] = []
    bg = colors["bg"]
    for key, minimum, label in CHECKS:
        if contrast(colors[key], bg) >= minimum:
            continue
        fixed = _push(colors[key], bg, minimum)
        if fixed != colors[key]:
            verb = "clareado" if luminance(fixed) > luminance(colors[key]) else "escurecido"
            if label.startswith("cor "):
                verb = verb[:-1] + "a"
            notes.append(f"{label} {verb} para dar contraste")
            colors[key] = fixed
    if contrast(colors["onacc"], colors["acc"]) < 4.5:
        dark_choice = colors["bar"] if theme.get("base") == "escuro" and luminance(colors["bar"]) < 0.05 else "#14151b"
        choice = best_on(colors["acc"], dark=dark_choice)
        if choice != colors["onacc"]:
            notes.append("texto sobre o destaque trocado para dar contraste")
            colors["onacc"] = choice
    return {**theme, "cores": colors, "ajustes": [*theme.get("ajustes", []), *notes]}


def build(name: Any, base: Any, colors: Any, *, origin: str, source: str, terminal: Any = None) -> dict:
    if base not in BASES:
        raise ThemeError("base precisa ser escuro ou claro")
    if not isinstance(colors, dict):
        raise ThemeError("faltam as cores")
    name = " ".join(str(name or "").split())[:MAX_NAME] or "Tema sem nome"
    cores = complete(colors, base)
    term = None
    if isinstance(terminal, dict):
        term = {key: value for key in TERMINAL_KEYS if (value := solid(terminal.get(key), cores["term"]))}
        term = term or None
    return {
        "id": "",
        "nome": name,
        "base": base,
        "cores": cores,
        "terminal": term,
        "origem": origin,
        "fonte": str(source)[:400],
        "criado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ajustes": [],
    }


# --- armazenamento ------------------------------------------------------------------


class ThemeStore:
    def __init__(self, home: Path) -> None:
        self.folder = home / "temas"

    def list(self) -> list[dict]:
        if not self.folder.is_dir():
            return []
        themes = []
        for path in self.folder.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and isinstance(data.get("cores"), dict) and data.get("id") == path.stem:
                themes.append(data)
        return sorted(themes, key=lambda t: str(t.get("criado", "")), reverse=True)

    def get(self, theme_id: str) -> dict | None:
        if not ID.fullmatch(theme_id):
            return None
        return next((t for t in self.list() if t["id"] == theme_id), None)

    def save(self, theme: dict) -> dict:
        self.folder.mkdir(parents=True, exist_ok=True)
        base = slugify(theme["nome"])[:40].strip("-") or "tema"
        theme_id = f"{base}-{secrets.token_hex(3)}"
        while (self.folder / f"{theme_id}.json").exists():
            theme_id = f"{base}-{secrets.token_hex(3)}"
        theme = {**theme, "id": theme_id}
        fd, tmp = tempfile.mkstemp(prefix=".tema-", suffix=".json", dir=self.folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(theme, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.folder / f"{theme_id}.json")
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        return theme

    def delete(self, theme_id: str) -> bool:
        if not ID.fullmatch(theme_id):
            return False
        path = self.folder / f"{theme_id}.json"
        if not path.is_file():
            return False
        path.unlink()
        return True


# --- por prompt ----------------------------------------------------------------------

PROMPT = """Você cria temas de cores para a MÊTIS, um app de terminais e agentes para Mac.

Pedido do Pedro: {description}

Responda SÓ com um objeto JSON, sem texto em volta, neste formato:
{{"nome": "nome curto do tema em português", "base": "escuro" ou "claro", "cores": {{{keys}}}}}

Cada cor é "#rrggbb". O papel de cada uma:
{roles}

Regras: o texto (tx) precisa de contraste forte com o fundo (bg) e com o terminal (term); mut e fnt
são versões mais apagadas do texto, ainda legíveis; run, wait, warn e err precisam se destacar do fundo;
onacc precisa ser legível sobre acc. Num tema escuro, bar é a faixa mais escura e elev um pouco mais
clara que o fundo.
"""


def prompt_for(description: str) -> str:
    keys = ", ".join(f'"{key}": "#rrggbb"' for key in TOKENS)
    roles = "\n".join(f"- {key}: {text}" for key, text in ROLES.items())
    return PROMPT.format(description=description, keys=keys, roles=roles)


def from_prompt(description: Any, ask: Callable[[str], dict]) -> dict:
    """Tema a partir de uma frase: `ask` manda o prompt ao Claude e devolve o objeto JSON."""
    description = " ".join(str(description or "").split())
    if not 3 <= len(description) <= 400:
        raise ThemeError("descreva o tema em 3 a 400 caracteres")
    answer = ask(prompt_for(description))
    if not isinstance(answer, dict) or not isinstance(answer.get("cores"), dict):
        raise ThemeGenError("o Claude não devolveu as cores do tema; tente descrever de novo")
    base = answer.get("base") if answer.get("base") in BASES else None
    if base is None:
        bg = normalize(answer["cores"].get("bg"))
        base = "claro" if bg and luminance(bg) > 0.4 else "escuro"
    try:
        theme = build(answer.get("nome"), base, answer["cores"], origin="prompt", source=description)
    except ThemeError as exc:
        raise ThemeGenError(f"o Claude devolveu um tema incompleto: {exc}") from exc
    return adjust(theme)


# --- VS Code -------------------------------------------------------------------------

#: (nome do app, extensões embutidas, extensões do usuário, settings.json do usuário)
VSCODE_APPS: list[tuple[str, Path, Path, Path]] = [
    (
        "VS Code",
        Path("/Applications/Visual Studio Code.app/Contents/Resources/app/extensions"),
        Path.home() / ".vscode" / "extensions",
        Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json",
    ),
    (
        "Cursor",
        Path("/Applications/Cursor.app/Contents/Resources/app/extensions"),
        Path.home() / ".cursor" / "extensions",
        Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "settings.json",
    ),
]

# O que o VS Code usa quando o tema não diz (o código dele tem esses padrões, não o JSON).
VSCODE_DEFAULTS = {
    "escuro": {
        "editor.background": "#1e1e1e",
        "editor.foreground": "#d4d4d4",
        "sideBar.background": "#252526",
        "activityBar.background": "#333333",
        "titleBar.activeBackground": "#3c3c3c",
        "editorWidget.background": "#252526",
        "button.background": "#0e639c",
        "button.foreground": "#ffffff",
        "textLink.foreground": "#3794ff",
        "errorForeground": "#f48771",
        "editor.selectionBackground": "#264f78",
        "terminal.ansiCyan": "#11a8cd",
        "terminal.ansiMagenta": "#bc3fbc",
        "terminal.ansiYellow": "#e5e510",
    },
    "claro": {
        "editor.background": "#ffffff",
        "editor.foreground": "#000000",
        "sideBar.background": "#f3f3f3",
        "activityBar.background": "#2c2c2c",
        "titleBar.activeBackground": "#dddddd",
        "editorWidget.background": "#f3f3f3",
        "button.background": "#007acc",
        "button.foreground": "#ffffff",
        "textLink.foreground": "#006ab1",
        "errorForeground": "#a1260d",
        "editor.selectionBackground": "#add6ff",
        "terminal.ansiCyan": "#0598bc",
        "terminal.ansiMagenta": "#bc05bc",
        "terminal.ansiYellow": "#949800",
    },
}


def jsonc_loads(text: str) -> Any:
    """JSON com comentários (// e /* */) e vírgula sobrando, como os do VS Code."""
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(c)
            i += 1
    cleaned = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    return json.loads(cleaned)


def load_vscode_colors(path: Path, depth: int = 0) -> dict[str, str]:
    """As `colors` do tema, com as do `include` por baixo (tokenColors não interessam)."""
    try:
        data = jsonc_loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ThemeError(f"tema do VS Code ilegível: {path.name}") from exc
    if not isinstance(data, dict):
        raise ThemeError(f"tema do VS Code ilegível: {path.name}")
    colors: dict[str, str] = {}
    include = data.get("include")
    if isinstance(include, str) and depth < 5:
        with contextlib.suppress(ThemeError):
            colors.update(load_vscode_colors((path.parent / include).resolve(), depth + 1))
    own = data.get("colors")
    if isinstance(own, dict):
        colors.update({k: v for k, v in own.items() if isinstance(v, str)})
    return colors


def from_vscode(colors: dict[str, str], base: str) -> tuple[dict[str, str], dict | None]:
    """Cores do VS Code → (cores da MÊTIS, terminal ou None)."""
    merged = {**VSCODE_DEFAULTS[base], **colors}
    bg = solid(merged.get("editor.background"), "#000000") or VSCODE_DEFAULTS[base]["editor.background"]

    def pick(*keys: str) -> str | None:
        for key in keys:
            value = solid(merged.get(key), bg)
            if value:
                return value
        return None

    tx = pick("editor.foreground", "foreground") or DEFAULT_STATUS[base]["tx"]
    acc = pick("button.background", "focusBorder", "textLink.foreground") or DEFAULT_STATUS[base]["acc"]
    out = {
        "bg": bg,
        "side": pick("sideBar.background"),
        "bar": pick("titleBar.activeBackground", "activityBar.background"),
        "elev": pick("editorWidget.background", "dropdown.background") or lighten(bg, 0.05 if base == "escuro" else -0.04),
        "line": pick("panel.border", "editorGroup.border", "sideBar.border") or mix(bg, tx, 0.12),
        "line2": mix(bg, tx, 0.2),
        "term": pick("terminal.background") or bg,
        "tx": tx,
        "mut": pick("descriptionForeground") or mix(tx, bg, 0.3),
        "fnt": pick("editorLineNumber.foreground") or mix(tx, bg, 0.5),
        "acc": acc,
        "acct": pick("textLink.foreground") or lighten(acc, 0.1 if base == "escuro" else -0.1),
        "onacc": pick("button.foreground") or best_on(acc),
        "run": pick("terminal.ansiCyan"),
        "wait": pick("terminal.ansiMagenta"),
        "warn": pick("terminal.ansiYellow"),
        "err": pick("errorForeground", "terminal.ansiRed"),
        "sel": pick("editor.selectionBackground"),
    }
    terminal: dict[str, str] = {}
    for name in ANSI:
        for key, target in ((f"terminal.ansi{name.capitalize()}", name), (f"terminal.ansiBright{name.capitalize()}", "bright" + name.capitalize())):
            value = solid(colors.get(key), bg)
            if value:
                terminal[target] = value
    if not terminal:
        return {k: v for k, v in out.items() if v}, None
    term_bg = solid(colors.get("terminal.background"), bg) or out["term"]
    terminal["background"] = term_bg
    terminal["foreground"] = solid(colors.get("terminal.foreground"), term_bg) or tx
    terminal["cursor"] = solid(colors.get("terminalCursor.foreground"), term_bg) or tx
    if colors.get("terminal.selectionBackground"):
        terminal["selectionBackground"] = solid(colors["terminal.selectionBackground"], term_bg) or ""
    return {k: v for k, v in out.items() if v}, {k: v for k, v in terminal.items() if v}


def _nls_label(label: str, folder: Path) -> str:
    if not (label.startswith("%") and label.endswith("%")):
        return label
    try:
        strings = jsonc_loads((folder / "package.nls.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return label.strip("%")
    value = strings.get(label.strip("%")) if isinstance(strings, dict) else None
    if isinstance(value, dict):
        value = value.get("message")
    return value if isinstance(value, str) else label.strip("%")


def _vscode_sources() -> list[dict]:
    sources: list[dict] = []
    seen: set[str] = set()
    for app, builtin, user, settings_path in VSCODE_APPS:
        try:
            in_use = jsonc_loads(settings_path.read_text(encoding="utf-8-sig")).get("workbench.colorTheme")
        except (OSError, ValueError, AttributeError):
            in_use = None
        for root, user_ext in ((builtin, False), (user, True)):
            if not root.is_dir():
                continue
            for folder in sorted(root.iterdir()):
                package = folder / "package.json"
                if not package.is_file():
                    continue
                try:
                    data = jsonc_loads(package.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    continue
                themes = (data.get("contributes") or {}).get("themes") if isinstance(data, dict) else None
                if not isinstance(themes, list):
                    continue
                for entry in themes:
                    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                        continue
                    path = (folder / entry["path"]).resolve()
                    if path.suffix.lower() != ".json" or not path.is_file() or str(path) in seen:
                        continue
                    seen.add(str(path))
                    label = _nls_label(str(entry.get("label") or entry.get("id") or path.stem), folder)
                    ui = str(entry.get("uiTheme") or "vs-dark")
                    sources.append({
                        "id": f"vscode:{path}",
                        "origem": "vscode",
                        "nome": label,
                        "base": "claro" if ui in ("vs", "hc-light") else "escuro",
                        "onde": f"{app} · {folder.name}" if user_ext else app,
                        "em_uso": bool(in_use) and in_use in (label, entry.get("id")),
                    })  # fmt: skip
    return sources


# --- Obsidian ------------------------------------------------------------------------

OBSIDIAN_CONFIG = Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"

# O tema padrão do Obsidian 1.x, no mesmo formato de um tema da comunidade (passa pelo mesmo leitor).
OBSIDIAN_DEFAULT_CSS = """
body {
  --accent-h: 254;
  --accent-s: 80%;
  --accent-l: 68%;
}
.theme-dark {
  --color-base-00: #1e1e1e; --color-base-10: #242424; --color-base-20: #262626; --color-base-30: #363636;
  --color-base-35: #3f3f3f; --color-base-50: #666666; --color-base-70: #b3b3b3; --color-base-100: #dadada;
  --color-red: #fb464c; --color-orange: #e9973f; --color-cyan: #53dfdd; --color-purple: #a882ff; --color-pink: #fa99cd;
  --color-accent: hsl(var(--accent-h), var(--accent-s), var(--accent-l));
  --background-primary: var(--color-base-00);
  --background-primary-alt: var(--color-base-10);
  --background-secondary: var(--color-base-20);
  --background-secondary-alt: var(--color-base-10);
  --titlebar-background: var(--color-base-10);
  --background-modifier-border: var(--color-base-30);
  --background-modifier-border-hover: var(--color-base-35);
  --text-normal: var(--color-base-100);
  --text-muted: var(--color-base-70);
  --text-faint: var(--color-base-50);
  --interactive-accent: var(--color-accent);
  --text-accent: hsl(var(--accent-h), var(--accent-s), calc(var(--accent-l) + 6%));
  --text-on-accent: #ffffff;
  --text-error: var(--color-red);
  --text-selection: hsla(var(--accent-h), 50%, 40%, 0.45);
}
.theme-light {
  --color-base-00: #ffffff; --color-base-10: #fafafa; --color-base-20: #f6f6f6; --color-base-30: #e0e0e0;
  --color-base-35: #d4d4d4; --color-base-50: #ababab; --color-base-70: #5a5a5a; --color-base-100: #222222;
  --color-red: #e93147; --color-orange: #ec7500; --color-cyan: #00bfbc; --color-purple: #7852ee; --color-pink: #d53984;
  --color-accent: hsl(var(--accent-h), var(--accent-s), calc(var(--accent-l) - 4%));
  --background-primary: var(--color-base-00);
  --background-primary-alt: var(--color-base-10);
  --background-secondary: var(--color-base-20);
  --background-secondary-alt: var(--color-base-10);
  --titlebar-background: var(--color-base-20);
  --background-modifier-border: var(--color-base-30);
  --background-modifier-border-hover: var(--color-base-35);
  --text-normal: var(--color-base-100);
  --text-muted: var(--color-base-70);
  --text-faint: var(--color-base-50);
  --interactive-accent: var(--color-accent);
  --text-accent: var(--color-accent);
  --text-on-accent: #ffffff;
  --text-error: var(--color-red);
  --text-selection: hsla(var(--accent-h), 80%, 75%, 0.4);
}
"""

VARIANT_CLASS = {"escuro": "theme-dark", "claro": "theme-light"}


def _strip_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _kind(selector: str) -> set[str]:
    """Que bloco é: base (:root, body, html) ou de uma variante (.theme-dark, body.theme-light…)."""
    kinds: set[str] = set()
    for part in selector.split(","):
        part = " ".join(part.split())
        if part in (":root", "body", "html"):
            kinds.add("base")
        for variant, css_class in VARIANT_CLASS.items():
            if re.fullmatch(rf"(?:html\s+)?(?:body)?[\w\-.]*\.{css_class}(?![\w-])[\w\-.:()]*", part):
                kinds.add(variant)
    return kinds


def css_blocks(text: str) -> dict[str, dict[str, str]]:
    """Variáveis por bloco: {"base": {...}, "escuro": {...}, "claro": {...}} (a última vence)."""
    found: dict[str, dict[str, str]] = {"base": {}, "escuro": {}, "claro": {}}
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_css_comments(text)):
        selector = match.group(1).rsplit(";", 1)[-1].strip()
        kinds = _kind(selector)
        if not kinds:
            continue
        for declaration in match.group(2).split(";"):
            name, sep, value = declaration.partition(":")
            name = name.strip()
            if not sep or not name.startswith("--"):
                continue
            value = re.sub(r"\s*!important\s*$", "", value.strip())
            for kind in kinds:
                found[kind][name] = value
    return found


def _matching(text: str, open_at: int) -> int:
    """Índice do ")" que fecha o "(" em open_at (ou -1)."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def resolve_vars(value: str, variables: dict[str, str], depth: int = 0) -> str:
    if depth > 20:
        return value
    while True:
        start = value.find("var(")
        if start == -1:
            return value
        end = _matching(value, start + 3)
        if end == -1:
            return value
        inner = value[start + 4 : end]
        name, _, fallback = inner.partition(",")
        name = name.strip()
        if name in variables:
            replacement = resolve_vars(variables[name], variables, depth + 1)
        else:
            replacement = resolve_vars(fallback.strip(), variables, depth + 1)
        value = value[:start] + replacement + value[end + 1 :]


_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?|\.\d+)(%|deg|px)?|([()+\-*/]))")


def _calc(expression: str) -> str | None:
    tokens: list[tuple[str, Any]] = []
    pos = 0
    while pos < len(expression):
        if expression[pos:].strip() == "":
            break
        match = _TOKEN.match(expression, pos)
        if not match:
            return None
        if match.group(1) is not None:
            tokens.append(("num", (float(match.group(1)), match.group(2) or "")))
        else:
            tokens.append(("op", match.group(3)))
        pos = match.end()
    index = 0

    def peek() -> tuple[str, Any] | None:
        return tokens[index] if index < len(tokens) else None

    def take() -> tuple[str, Any]:
        nonlocal index
        index += 1
        return tokens[index - 1]

    def factor() -> tuple[float, str]:
        token = take()
        if token == ("op", "-"):
            number, unit = factor()
            return -number, unit
        if token == ("op", "("):
            value = expr()
            if take() != ("op", ")"):
                raise ValueError
            return value
        if token[0] != "num":
            raise ValueError
        return token[1]

    def term() -> tuple[float, str]:
        number, unit = factor()
        while peek() in (("op", "*"), ("op", "/")):
            op = take()[1]
            other, other_unit = factor()
            number = number * other if op == "*" else number / other
            unit = unit or other_unit
        return number, unit

    def expr() -> tuple[float, str]:
        number, unit = term()
        while peek() in (("op", "+"), ("op", "-")):
            op = take()[1]
            other, other_unit = term()
            number = number + other if op == "+" else number - other
            unit = unit or other_unit
        return number, unit

    try:
        number, unit = expr()
    except (ValueError, IndexError, ZeroDivisionError):
        return None
    if index != len(tokens):
        return None
    return f"{round(number, 4):g}{unit}"


def eval_calcs(value: str) -> str:
    for _ in range(20):
        start = value.rfind("calc(")
        if start == -1:
            return value
        end = _matching(value, start + 4)
        if end == -1:
            return value
        result = _calc(value[start + 5 : end])
        if result is None:
            return value
        value = value[:start] + result + value[end + 1 :]
    return value


def _number(text: str, scale: float = 1.0) -> float:
    text = text.strip()
    if text.endswith("%"):
        return float(text[:-1]) / 100 * scale
    if text.endswith("deg"):
        return float(text[:-3])
    return float(text)


def parse_css_color(value: str) -> tuple[RGB, float] | None:
    value = value.strip()
    if value.lower() in NAMED:
        value = NAMED[value.lower()]
    if value.startswith("#"):
        return parse_hex(value)
    match = re.fullmatch(r"(rgba?|hsla?)\((.*)\)", value, re.S | re.I)
    if not match:
        return None
    kind = match.group(1).lower()
    body = match.group(2).replace("/", " / ")
    parts = [p for p in re.split(r"[\s,]+", body.strip()) if p]
    alpha = 1.0
    if "/" in parts:
        cut = parts.index("/")
        alpha_part = parts[cut + 1 :]
        parts = parts[:cut]
        if alpha_part:
            try:
                alpha = _number(alpha_part[0])
            except ValueError:
                return None
    elif len(parts) == 4:
        try:
            alpha = _number(parts.pop())
        except ValueError:
            return None
    if len(parts) != 3:
        return None
    try:
        if kind.startswith("rgb"):
            rgb = tuple(_number(p, 255) for p in parts)
        else:
            h = _number(parts[0]) % 360 / 360
            s = _number(parts[1] if parts[1].endswith("%") else parts[1] + "%")
            light = _number(parts[2] if parts[2].endswith("%") else parts[2] + "%")
            r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, light)), max(0.0, min(1.0, s)))
            rgb = (r * 255, g * 255, b * 255)
    except ValueError:
        return None
    return (float(rgb[0]), float(rgb[1]), float(rgb[2])), max(0.0, min(1.0, alpha))


def css_color(name: str, variables: dict[str, str], under: str | None) -> str | None:
    raw = variables.get(name)
    if raw is None:
        return None
    parsed = parse_css_color(eval_calcs(resolve_vars(raw, variables)))
    if parsed is None:
        return None
    rgb, alpha = parsed
    if alpha < 1 and under:
        rgb = blend(rgb, alpha, rgb_of(under))
    return to_hex(rgb)


def obsidian_variables(css: str, variant: str) -> dict[str, str]:
    """As variáveis da variante: as do Obsidian padrão por baixo, depois as do tema."""
    default = css_blocks(OBSIDIAN_DEFAULT_CSS)
    theme = css_blocks(css)
    return {**default["base"], **default[variant], **theme["base"], **theme[variant]}


def from_obsidian(variables: dict[str, str], base: str) -> dict[str, str]:
    def get(*names: str, under: str | None = None) -> str | None:
        for name in names:
            color = css_color(name, variables, under)
            if color:
                return color
        return None

    bg = get("--background-primary") or ("#1e1e1e" if base == "escuro" else "#ffffff")
    tx = get("--text-normal", under=bg) or DEFAULT_STATUS[base]["tx"]
    side = get("--background-secondary", under=bg)
    out = {
        "bg": bg,
        "side": side,
        "bar": get("--titlebar-background", "--background-secondary-alt", under=bg) or side,
        "elev": get("--background-primary-alt", "--background-modifier-hover", under=bg),
        "line": get("--background-modifier-border", under=bg) or mix(bg, tx, 0.12),
        "line2": get("--background-modifier-border-hover", under=bg) or mix(bg, tx, 0.2),
        "term": bg,
        "tx": tx,
        "mut": get("--text-muted", under=bg),
        "fnt": get("--text-faint", under=bg),
        "acc": get("--interactive-accent", "--color-accent", under=bg),
        "acct": get("--text-accent", under=bg),
        "onacc": get("--text-on-accent", under=bg),
        "err": get("--text-error", "--color-red", under=bg),
        "run": get("--color-cyan", under=bg),
        "wait": get("--color-purple", under=bg),
        "warn": get("--color-pink", "--color-orange", under=bg),
        "sel": get("--text-selection", under=bg),
    }
    return {k: v for k, v in out.items() if v}


def _obsidian_vaults() -> list[Path]:
    try:
        data = json.loads(OBSIDIAN_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    vaults = data.get("vaults") if isinstance(data, dict) else None
    if not isinstance(vaults, dict):
        return []
    paths = [Path(v["path"]) for v in vaults.values() if isinstance(v, dict) and isinstance(v.get("path"), str)]
    return [p for p in paths if p.is_dir()]


def _obsidian_sources() -> list[dict]:
    sources: list[dict] = []
    default_in_use: set[str] = set()
    vaults = _obsidian_vaults()
    for vault in vaults:
        try:
            appearance = json.loads((vault / ".obsidian" / "appearance.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            appearance = {}
        appearance = appearance if isinstance(appearance, dict) else {}
        current = appearance.get("cssTheme") or ""
        if not current:
            default_in_use.add("claro" if appearance.get("theme") == "moonstone" else "escuro")
        folder = vault / ".obsidian" / "themes"
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if entry.is_dir() and (entry / "theme.css").is_file():
                name, css_path = entry.name, entry / "theme.css"
            elif entry.is_file() and entry.suffix.lower() == ".css":
                name, css_path = entry.stem, entry
            else:
                continue
            try:
                blocks = css_blocks(css_path.read_text(encoding="utf-8"))
            except OSError:
                continue
            variants = [v for v in BASES if blocks[v]] or (list(BASES) if blocks["base"] else [])
            for variant in variants:
                sources.append({
                    "id": f"obsidian:{css_path}#{variant}",
                    "origem": "obsidian",
                    "nome": name,
                    "base": variant,
                    "onde": f"Obsidian · cofre {vault.name}",
                    "em_uso": name == current,
                })  # fmt: skip
    for variant in BASES:
        sources.append({
            "id": f"obsidian:padrao#{variant}",
            "origem": "obsidian",
            "nome": "Obsidian (padrão)",
            "base": variant,
            "onde": "Obsidian",
            "em_uso": variant in default_in_use,
        })  # fmt: skip
    return sources


# --- importar -----------------------------------------------------------------------


def list_sources() -> list[dict]:
    return _vscode_sources() + _obsidian_sources()


def import_source(source_id: Any) -> dict:
    """Converte uma fonte da lista em tema (ajustado, sem id: quem grava é o ThemeStore)."""
    if not isinstance(source_id, str) or not source_id:
        raise ThemeError("diga qual tema importar")
    source = next((s for s in list_sources() if s["id"] == source_id), None)
    if source is None:
        raise SourceNotFound(f"tema não encontrado: {source_id}")
    base = source["base"]
    label = f"{source['onde']} · {source['nome']}"
    if source["origem"] == "vscode":
        colors, terminal = from_vscode(load_vscode_colors(Path(source_id.removeprefix("vscode:"))), base)
        theme = build(source["nome"], base, colors, origin="vscode", source=label, terminal=terminal)
    else:
        location = source_id.removeprefix("obsidian:").rsplit("#", 1)[0]
        css = "" if location == "padrao" else Path(location).read_text(encoding="utf-8")
        colors = from_obsidian(obsidian_variables(css, base), base)
        theme = build(f"{source['nome']} · {base}", base, colors, origin="obsidian", source=label)
    return adjust(theme)
