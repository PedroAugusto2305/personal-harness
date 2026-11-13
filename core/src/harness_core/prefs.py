"""Ajustes da MÊTIS (v0.9.2) em ~/.harness/ajustes.json, e o que eles mudam nas sessões.

- Modo de permissão das sessões novas, por CLI: "padrao" (não passa nada: vale o que o
  Pedro configurou na própria CLI), "manual", "auto" ou "yolo".
- Confiar nas pastas: as pastas dos projetos da MÊTIS e as worktrees deles entram como
  confiáveis antes de a CLI abrir, para o "Do you trust this folder?" não travar cada
  worktree nova. Só essas pastas; nunca uma pasta qualquer.
- Manter o Mac acordado: nunca, só com agente trabalhando, ou sempre com o núcleo no ar.
- Avisos: notificação e som quando o agente termina ou espera você.
- Vista do agente (v1.2.0): o painel do Claude e do Codex abre na conversa desenhada ou no
  terminal. O terminal continua vivo por baixo nos dois casos.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

PERMISSION_MODES = ("padrao", "manual", "auto", "yolo")
AWAKE_MODES = ("nunca", "agente", "sempre")
GIT_AGENTS = ("claude", "codex")
#: v0.9.8: minutos esperando até o agente hibernar (0 = nunca).
HIBERNATE_MINUTES = (0, 15, 30, 60)
AGENT_VIEWS = ("conversa", "terminal")
RECIPE_MAX = 4000
NOTEBOOK_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

# Receitas de IA por ação (v0.9.6): o pedido que vai ao agente da worktree. {base} vira o branch alvo do PR.
RECIPE_COMMIT = (
    "Veja as mudanças desta worktree (git status e git diff), marque o que faz parte do mesmo trabalho e faça o "
    "commit com uma mensagem no padrão das mensagens recentes (git log -5 --oneline). Se houver mais de um assunto, "
    "me pergunte antes."
)
RECIPE_COMMIT_STAGED = (
    "Escreva a mensagem e faça o commit só das mudanças já marcadas nesta worktree (git diff --cached), no padrão das "
    "mensagens recentes (git log -5 --oneline). Não marque nem desmarque outros arquivos."
)
RECIPE_PR = (
    "Abra um pull request deste branch para o {base} com o gh: título curto no padrão dos commits recentes e corpo com "
    "o que mudou, o porquê e como testar. Se o branch não subiu, suba antes. Me devolva o link."
)

DEFAULTS: dict[str, Any] = {
    "permissao_claude": "padrao",
    "permissao_codex": "padrao",
    "confiar_pastas": True,
    "manter_acordado": "agente",
    "avisos": {"terminou": True, "espera": True, "aprovacao": True, "erro": True, "som": True, "volume": 0.6, "silencio": False},
    "receita_commit": RECIPE_COMMIT,
    "receita_commit_marcado": RECIPE_COMMIT_STAGED,
    "receita_pr": RECIPE_PR,
    "agente_git": "claude",
    "editor_externo": "",
    "hibernar_min": 0,
    "vista_agente": "conversa",
    # v0.9.8: o projeto do Brain onde mora o mapa do estudo (conceitos/) e o cronograma.
    "estudo_projeto": "AI Engineer 2027",
    # v1.3.0: o caderno do NotebookLM que o Sócrates usa como base das respostas (vazio = nenhum).
    "estudo_caderno": {"id": "", "titulo": ""},
}


class PrefsError(ValueError):
    pass


class Prefs:
    def __init__(self, home: Path) -> None:
        self.path = home / "ajustes.json"
        self._lock = threading.Lock()
        home.mkdir(parents=True, exist_ok=True)

    def get(self) -> dict:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        data = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
        data["avisos"] = {**DEFAULTS["avisos"], **(saved.get("avisos") or {})}
        return data

    def update(self, changes: dict) -> dict:
        with self._lock:
            data = self.get()
            for key, value in changes.items():
                if key not in DEFAULTS:
                    raise PrefsError(f"ajuste desconhecido: {key}")
                if key.startswith("permissao_") and value not in PERMISSION_MODES:
                    raise PrefsError(f"modo de permissão é {', '.join(PERMISSION_MODES)}")
                if key == "manter_acordado" and value not in AWAKE_MODES:
                    raise PrefsError(f"manter acordado é {', '.join(AWAKE_MODES)}")
                if key == "avisos":
                    if not isinstance(value, dict):
                        raise PrefsError("avisos é um objeto")
                    value = {**data["avisos"], **{k: v for k, v in value.items() if k in DEFAULTS["avisos"]}}
                    value["volume"] = max(0.0, min(1.0, float(value["volume"])))
                if key == "confiar_pastas":
                    value = bool(value)
                if key.startswith("receita_"):
                    if not isinstance(value, str) or len(value) > RECIPE_MAX:
                        raise PrefsError(f"a receita é um texto de até {RECIPE_MAX} caracteres")
                    value = value.strip() or DEFAULTS[key]  # vazia volta ao padrão
                if key == "agente_git" and value not in GIT_AGENTS:
                    raise PrefsError(f"o agente do git é {', '.join(GIT_AGENTS)}")
                if key == "hibernar_min":
                    if isinstance(value, bool) or not isinstance(value, int) or value not in HIBERNATE_MINUTES:
                        raise PrefsError("hibernar é 0 (nunca), 15, 30 ou 60 minutos")
                if key == "vista_agente" and value not in AGENT_VIEWS:
                    raise PrefsError(f"o agente abre em {' ou '.join(AGENT_VIEWS)}")
                if key == "editor_externo":
                    if not isinstance(value, str) or len(value) > 40:
                        raise PrefsError("editor externo inválido")
                    value = value.strip()
                if key == "estudo_caderno":
                    if value is None:
                        value = {"id": "", "titulo": ""}
                    if not isinstance(value, dict):
                        raise PrefsError("o caderno do estudo é {id, titulo}")
                    nb_id = str(value.get("id") or "").strip()
                    if nb_id and not NOTEBOOK_ID.match(nb_id):
                        raise PrefsError("id de caderno do NotebookLM inválido")
                    title = " ".join(str(value.get("titulo") or "").split())[:200]
                    value = {"id": nb_id, "titulo": title if nb_id else ""}
                if key == "estudo_projeto":
                    if not isinstance(value, str) or not value.strip() or len(value) > 120:
                        raise PrefsError("o projeto de estudo é o nome de um projeto do Brain")
                    value = value.strip()
                data[key] = value
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return data


def permission_args(kind: str, mode: str) -> list[str]:
    """Os argumentos da CLI para o modo escolhido (vazio em "padrao")."""
    if kind == "claude":
        return {"manual": ["--permission-mode", "manual"], "auto": ["--permission-mode", "auto"], "yolo": ["--dangerously-skip-permissions"]}.get(mode, [])
    if kind == "codex":
        return {"manual": ["-a", "untrusted"], "auto": ["--approve-for-me"], "yolo": ["--dangerously-bypass-approvals-and-sandbox"]}.get(mode, [])
    return []


def codex_trust_args(folder: str) -> list[str]:
    return ["-c", f'projects."{folder}".trust_level="trusted"']


def trust_claude_folder(config_file: Path, folder: str) -> bool:
    """Marca a pasta como confiável no .claude.json da conta. Devolve True se mudou algo.

    O arquivo é do Claude Code (vários Claudes abertos o regravam): lê, muda só a chave da
    pasta e troca de uma vez; se a pasta já é confiável, nem toca no arquivo."""
    try:
        data = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    except (OSError, ValueError):
        return False  # arquivo ilegível agora (um Claude gravando): fica para a próxima
    if not isinstance(data, dict):
        return False
    projects = data.setdefault("projects", {})
    entry = projects.setdefault(folder, {})
    if not isinstance(entry, dict) or entry.get("hasTrustDialogAccepted"):
        return False
    entry["hasTrustDialogAccepted"] = True
    mode = config_file.stat().st_mode & 0o777 if config_file.exists() else 0o600
    fd, tmp = tempfile.mkstemp(prefix=".claude.json.metis-", dir=config_file.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.chmod(tmp, mode)
        os.replace(tmp, config_file)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        return False
    return True
