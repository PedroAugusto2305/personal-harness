"""Agente por descrição: o Pedro descreve em uma frase e o Claude rascunha os campos.

Roda o `claude -p` oficial (sem tela), com a conta ativa do Claude, e só devolve o rascunho:
quem salva é o Pedro, depois de revisar no formulário. Mesma linha do chat da sprite, que
já usa o `codex exec` sem tela para um pedido pontual.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

PROMPT = """Você desenha agentes para a MÊTIS, o ambiente pessoal do Pedro Aquino no Mac (agentes do Claude Code e do Codex em terminais, com o Brain, um vault Obsidian em ~/Documents/Brain, como memória).
Regras dos agentes do Pedro: um agente, uma tarefa; agente novo só com dor real; responde sempre em português do Brasil, direto; nunca copia dados, código ou prompts da Seller Pro para lugar público; não inventa fatos sobre o Pedro; no Brain, segue o CLAUDE.md do vault (frontmatter, datas absolutas, nunca apagar nota). Os agentes têm codinome greco-romano (como Aurora, Alexandria, Sócrates, Hermes) e visual greco-romano.
Agentes que já existem (não repita a tarefa de nenhum): {existing}

Descrição do Pedro para o novo agente:
{description}

Responda SÓ com um objeto JSON, sem texto antes ou depois, com estas chaves:
- "name": codinome greco-romano curto, que ainda não exista;
- "description": o papel em até 6 palavras;
- "pain": a dor do Pedro que ele resolve, numa frase;
- "cli": "claude" (padrão) ou "codex" (só se for trabalho de código pesado);
- "color": cor em hexadecimal (#rrggbb) que combine com o papel;
- "folder": "" ou a pasta onde ele deve abrir (ex.: "~/Documents/Brain" se mexe no vault);
- "prompt": o papel completo, em português do Brasil e em segunda pessoa ("Você é…"): a tarefa única, o que faz quando é chamado (passos numerados), o que nunca faz e como responde;
- "sprite": uma frase descrevendo o personagem greco-romano para a sprite (roupa, objeto que segura, cores)."""

KEYS = ("name", "description", "pain", "cli", "color", "folder", "prompt", "sprite")


class DraftError(RuntimeError):
    pass


Runner = Callable[[list[str], dict[str, str], str], str]


def run_cli(argv: list[str], env: dict[str, str], cwd: str) -> str:
    try:
        done = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired as exc:
        raise DraftError("o Claude demorou demais para responder (4 min)") from exc
    if done.returncode != 0:
        raise DraftError(f"o Claude não respondeu: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout


def _json_object(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise DraftError("o Claude não devolveu o rascunho em JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise DraftError("o rascunho veio com JSON quebrado; tente de novo") from exc
    if not isinstance(data, dict):
        raise DraftError("o rascunho não é um objeto JSON")
    return data


def draft_agent(description: str, existing: list[str], env: dict[str, str], run: Runner = run_cli) -> dict:
    description = description.strip()
    if len(description) < 8:
        raise DraftError("descreva o agente numa frase (o que ele faz e qual dor resolve)")
    executable = shutil.which("claude", path=env.get("PATH"))
    if not executable:
        raise DraftError("claude não encontrado no PATH")
    prompt = PROMPT.format(description=description, existing=", ".join(existing) or "nenhum")
    raw = run([executable, "-p", "--output-format", "json", prompt], env, str(Path.home()))
    try:
        envelope = json.loads(raw)
        text = envelope.get("result", "") if isinstance(envelope, dict) else raw
    except json.JSONDecodeError:
        text = raw
    data = _json_object(text)
    draft = {key: str(data.get(key, "") or "").strip() for key in KEYS}
    if not draft["name"] or not draft["prompt"]:
        raise DraftError("o rascunho veio sem nome ou sem papel; tente descrever de novo")
    draft["cli"] = draft["cli"] if draft["cli"] in ("claude", "codex") else "claude"
    draft["color"] = draft["color"] if re.fullmatch(r"#[0-9a-fA-F]{6}", draft["color"]) else "#82a0ff"
    return draft
