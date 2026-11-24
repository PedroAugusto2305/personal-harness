"""O que ainda é do Maestri e fica de fora da MÊTIS (v1.6.0).

O Maestri não é mais usado: a MÊTIS trabalha só com os agentes criados nela e com os que
vieram do Maestri e foram migrados de propósito. Os arquivos do Maestri continuam onde estão
(`~/.maestri`, `.maestri/roles` no Brain e as skills que ele instalou); a MÊTIS só deixa de
ler e de acionar o que é dele.

- **Agente importado e não migrado:** o `.md` em `~/.harness/agentes/` com `origem: maestri:<id>`
  (a importação da v0.3). A galeria não lista e nada o abre (`agents.AgentStore`). O migrado
  perde a `origem` e guarda de onde veio em `migrado: maestri:<id>`: é um agente da MÊTIS como
  os outros.
- **Skills do Maestri** (`maestri`, `maestri-chat`…): falam com os agentes do canvas do Maestri
  pelo `maestri`, que não existe nos terminais da MÊTIS. Nas sessões da MÊTIS elas ficam
  desligadas: no Claude, negadas no `--settings` (continuam na lista dele, mas não rodam); no
  Codex, `enabled=false` no `skills.config` (somem). A barra do "/" também não as sugere.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable
from pathlib import Path

#: A origem que a importação do Maestri gravava (`maestri:<id do papel>`).
ORIGIN = "maestri:"
#: As skills que o Maestri instala nas CLIs. A lista fixa cobre também as pastas de outras
#: contas do Claude; a varredura das pastas pega uma skill nova que ele venha a pôr.
SKILLS = (
    "maestri",
    "maestri-chat",
    "maestri-computer",
    "maestri-manager",
    "maestri-portal",
    "maestri-portal-devices",
    "maestri-routines",
    "maestri-workspace",
)


def is_skill(name: str) -> bool:
    return name == "maestri" or name.startswith("maestri-")


def is_leftover(origin: str) -> bool:
    """Agente importado do Maestri que não foi migrado para a MÊTIS."""
    return (origin or "").startswith(ORIGIN)


def _found(folders: Iterable[Path]) -> list[Path]:
    """As pastas de skill do Maestri (com SKILL.md) dentro das pastas de skills dadas."""
    found: list[Path] = []
    for folder in folders:
        if not folder.is_dir():
            continue
        found += [skill.parent for skill in sorted(folder.glob("*/SKILL.md")) if is_skill(skill.parent.name)]
    return found


def claude_skills(folders: Iterable[Path] | None = None) -> list[str]:
    """Os nomes a negar no Claude: a lista fixa e as que estiverem nas pastas (padrão: ~/.claude/skills)."""
    folders = [Path.home() / ".claude" / "skills"] if folders is None else folders
    return sorted(set(SKILLS) | {path.name for path in _found(folders)})


def _toml(value) -> str:
    # Texto, número e sim/não em JSON são TOML válido (sem DEL no texto, como no agent_args).
    return json.dumps(value.replace("\x7f", "") if isinstance(value, str) else value, ensure_ascii=False)


def codex_args(folders: Iterable[Path], config_file: Path) -> list[str]:
    """`-c skills.config=[...]` com as skills do Maestri desligadas (`enabled=false`).

    O `-c` troca a lista inteira do config.toml, então as entradas que o Pedro já tinha lá vêm
    junto, na frente. O Codex só desliga pelo caminho do SKILL.md, por isso a varredura."""
    ours = [str(path / "SKILL.md") for path in _found(folders)]
    if not ours:
        return []
    try:
        with config_file.open("rb") as handle:
            current = tomllib.load(handle).get("skills", {}).get("config", [])
    except (OSError, tomllib.TOMLDecodeError, AttributeError):
        current = []
    entries: list[str] = []
    for entry in current if isinstance(current, list) else []:
        if not isinstance(entry, dict) or entry.get("path") in ours:
            continue
        fields = [f"{key}={_toml(value)}" for key, value in entry.items() if isinstance(value, (str, bool, int)) and key.isidentifier()]
        if fields:
            entries.append("{" + ",".join(fields) + "}")
    entries += ["{path=" + _toml(path) + ",enabled=false}" for path in ours]
    return ["-c", "skills.config=[" + ",".join(entries) + "]"]
