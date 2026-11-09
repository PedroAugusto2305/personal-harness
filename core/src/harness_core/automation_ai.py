"""Automação por frase e código escrito pelo Claude (v0.9.8, parte 4).

- Criar ou ajustar por frase: o Pedro descreve, o Claude (pelo `claude -p`, sem ferramentas)
  monta o desenho a partir do catálogo de passos, das ferramentas da central e dos agentes da
  galeria. A MÊTIS confere o desenho (ferramenta que não existe vira um passo de agente com
  nota "revisar", ids e nomes repetidos são acertados, posições em grade) e devolve a
  PROPOSTA: nada é salvo, quem aplica ao rascunho é o Pedro, pela tela.
- Escrever código: a descrição de um passo Código vira Python ou JavaScript seguindo a
  convenção do motor (`entrada` e `passos` → `saida`).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from . import automations
from .automations import ID_RE, TRIGGER_ID, AutomationError, fold, slug

Ask = Callable[[str], dict]

LAYER_X = 260
ROW_Y = 140
MAX_DESCRIPTION = 1500

# Convenção do passo Código (o motor roda assim; o prompt e a tela repetem).
CODE_CONVENTION = {
    "python": (
        "Python 3 só com a biblioteca padrão. O código roda como um script (no nível de cima, sem return): as variáveis "
        "`entrada` (o que chegou do passo anterior) e `passos` (dicionário título do passo → saída dele) já existem; ao terminar, "
        "atribua o resultado a `saida` (algo que vire JSON: dict, lista, texto, número). Não leia nem escreva arquivos "
        "fora de /tmp e não use rede, a não ser que a descrição peça."
    ),
    "javascript": (
        "JavaScript do Node, só com o que vem no Node (fetch é global). O código roda dentro de uma função async: "
        "as variáveis `entrada` (o que chegou do passo anterior) e `passos` (objeto título do passo → saída dele) já "
        "existem, `await` funciona e, ao terminar, atribua o resultado a `saida` (algo que vire JSON; não declare `saida` "
        "de novo). Só require de módulos do próprio Node; nada de rede, a não ser que a descrição peça."
    ),
}

STEP_CATALOG = """Tipos de passo (campos de cada um):
- ferramenta: {ferramenta: "<nome exato de uma ferramenta da lista>", argumentos: {…}} — chamada direta, sem agente e sem cota.
- agente: {cli: "claude"|"codex", agente?: "<id da galeria>", pedido: "o que fazer, com {{expressões}}", saida: {campo: "texto"|"numero"|"lista"|"objeto"|"sim/nao"}, pasta?: "~/caminho" (onde ele trabalha), ferramentas?: ["<nomes da central liberados para ele>"] ou ["*"] (todas), troca_cota?: true (troca de provedor se a cota de 5 h passar de 80%)} — um Claude ou Codex num terminal, pelo plano.
- condicao: {regra: "{{Passo.campo}} > 0 e não vazio({{Outro}})"} — duas saídas: ligações com ramo "sim" e "não". Regra só com comparações, e/ou/não, len(), vazio(), contem().
- aprovacao: {mensagem: "texto para o Pedro", prazo_min: 60} — espera o sim do Pedro.
- brain: {acao: "buscar"|"ler"|"precedentes"|"tarefas"|"diario", termos?, nota?, projeto?, texto?} — o vault do Pedro.
- esperar: {minutos: número}.
- codigo: {linguagem: "python"|"javascript", descricao: "o que o código faz", codigo: "<código>", tempo_limite_s: 30} — recebe `entrada` e `passos` (título → saída), devolve em `saida`; o JavaScript roda dentro de uma função async (await funciona).

Gatilho (um só, id "gatilho"):
- manual: {tipo: "manual"}
- agendado: {tipo: "agendado", dias: [0..6] (0 = segunda), hora: "07:30", recupera_min: 60, aviso: false (DM no Slack quando começa)}
- evento: {tipo: "evento", evento: "brain.nota"|"tarefa.moveu"|"agente.terminou"|"agente.errou"|"worktree.criada"|"captura", filtro: {campo: valor} (opcional)} — os campos do evento chegam como saída do gatilho.
- sondagem: {tipo: "sondagem", ferramenta: "<ferramenta de leitura>", argumentos: {…}, cada_min: 15, chave: "id", caminho: "onde está a lista na resposta"} — roda quando aparece item novo, com {novos: [...]} na saída do gatilho.

Ligações: [{de: "gatilho"|"<id>", para: "<id>", ramo?: "sim"|"não" (só saindo de condição)}]. Sem ciclos.
Expressões: {{Nome do passo.campo}} (ou {{id.campo}}), {{hoje}}, {{agora}}, {{entrada}}.
Notas no canvas: [{id, titulo, texto, x, y, w: 240}]."""

PROMPT = """Você monta automações para a MÊTIS, o ambiente pessoal do Pedro Aquino no Mac (um "n8n" pessoal: passos ligados num canvas, ferramenta é determinística e sem cota, agente é um Claude ou Codex num terminal pelo plano). Tudo em português do Brasil.

{catalog}

Ferramentas da central que existem agora (use SÓ estes nomes; [fala com outras pessoas] pede aprovação do Pedro):
{tools}

Agentes da galeria (use o id em `agente` quando o papel servir):
{agents}

{task}

Regras: ids curtos em minúsculas com hífen; títulos curtos e únicos (as expressões usam o título); passo de agente sempre com `saida` combinada quando o próximo passo usa o resultado; nada que fale com outras pessoas sem um passo `aprovacao` antes, a não ser que o Pedro peça; prefira ferramenta a agente quando uma ferramenta resolve.

Responda SÓ com um objeto JSON, sem texto antes ou depois:
{{"fluxo": {{"nome": "...", "descricao": "...", "gatilho": {{...}}, "passos": [...], "ligacoes": [...], "notas": []}}, "explicacao": "2 a 5 frases para o Pedro: o que montou e o que ele precisa conferir"}}"""

CODE_PROMPT = """Escreva o código de um passo Código de uma automação da MÊTIS.

Linguagem e convenção: {convention}

O que o passo faz:
{description}
{example}
Responda SÓ com um objeto JSON, sem texto antes ou depois: {{"codigo": "<o código completo>"}}. Código curto, comentado em português do Brasil onde não for óbvio."""


class ProposalError(RuntimeError):
    """O Claude não devolveu um desenho que dê para usar (vira 502)."""


class ProposalInputError(ValueError):
    """Pedido inválido (vira 400)."""


# --- catálogo para o prompt -------------------------------------------------------------------


def describe_tools(tools: list[dict]) -> str:
    if not tools:
        return "(nenhuma conta ligada: use agentes, Brain e código)"
    lines = []
    for tool in tools[:120]:
        description = " ".join(str(tool.get("descricao") or "").split())[:140]
        mark = " [fala com outras pessoas]" if tool.get("pessoas") else ""
        lines.append(f"- {tool['nome']}{mark}: {description}")
    return "\n".join(lines)


def describe_agents(agents: list[dict]) -> str:
    if not agents:
        return "(nenhum agente na galeria)"
    return "\n".join(f"- {a['id']}: {a.get('nome') or a.get('name') or a['id']} ({a.get('cli', 'claude')}) — {str(a.get('descricao') or a.get('description') or '')[:100]}" for a in agents[:40])


# --- conserto do desenho que veio ---------------------------------------------------------------


def _unique_id(raw: Any, taken: set[str], fallback: str) -> str:
    base = slug(str(raw or "")) or fallback
    if not ID_RE.fullmatch(base):
        base = fallback
    base = base[:50]
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    taken.add(candidate)
    return candidate


def _unique_title(raw: Any, taken: set[str], fallback: str) -> str:
    title = " ".join(str(raw or "").split())[:80] or fallback
    candidate, n = title, 2
    while fold(candidate) in taken:
        candidate, n = f"{title} {n}", n + 1
    taken.add(fold(candidate))
    return candidate


def layout(flow: dict, keep: dict[str, tuple[float, float]] | None = None) -> None:
    """Posições em grade: gatilho em 0,0, uma coluna por camada (260 px), 140 px entre passos da
    mesma camada. O que está em `keep` (id → x, y) fica onde estava."""
    keep = keep or {}
    try:
        groups = automations.layers(flow)
    except Exception:  # noqa: BLE001 - desenho torto: tudo numa coluna só
        groups = [[TRIGGER_ID], [s["id"] for s in flow["passos"]]]
    placed = {node for group in groups for node in group}
    loose = [s["id"] for s in flow["passos"] if s["id"] not in placed]
    if loose:
        groups.append(loose)
    by_id = {s["id"]: s for s in flow["passos"]}
    for depth, group in enumerate(groups):
        offset = -(len(group) - 1) * ROW_Y / 2
        for row, node in enumerate(group):
            target = flow["gatilho"] if node == TRIGGER_ID else by_id.get(node)
            if target is None:
                continue
            if node in keep:
                target["x"], target["y"] = keep[node]
            else:
                target["x"], target["y"] = depth * LAYER_X, round(offset + row * ROW_Y)


def repair(flow: Any, tool_names: set[str], agent_ids: set[str]) -> tuple[dict, list[str]]:
    """Acerta o desenho do Claude antes de conferir: ids e títulos únicos, ferramenta que não existe
    vira agente com nota, agente da galeria que não existe sai, ligações para passo sumido saem."""
    if not isinstance(flow, dict):
        raise ProposalError("o Claude não devolveu o desenho da automação")
    review: list[str] = []
    taken_ids: set[str] = {TRIGGER_ID}
    taken_titles: set[str] = set()
    renamed: dict[str, str] = {}
    steps = []
    for index, raw in enumerate(flow.get("passos") or []):
        if not isinstance(raw, dict):
            continue
        step = dict(raw)
        old = str(step.get("id") or "")
        step["id"] = _unique_id(old or step.get("titulo"), taken_ids, f"passo-{index + 1}")
        renamed[old] = step["id"]
        step["titulo"] = _unique_title(step.get("titulo") or step["id"], taken_titles, step["id"])
        kind = step.get("tipo")
        if kind == "ferramenta" and str(step.get("ferramenta") or "") not in tool_names:
            missing = str(step.get("ferramenta") or "uma ferramenta")
            step = {
                "id": step["id"],
                "titulo": step["titulo"],
                "tipo": "agente",
                "cli": "claude",
                "pedido": f"Faça o que a ferramenta {missing} faria neste passo ({step['titulo']}), com {json.dumps(step.get('argumentos') or {}, ensure_ascii=False)}.",
                "saida": {},
                **({"x": step["x"], "y": step["y"]} if "x" in step and "y" in step else {}),
            }
            review.append(f"{step['titulo']}: a ferramenta {missing} não existe nas contas ligadas; virou um passo de agente")
        if step.get("tipo") == "agente":
            if step.get("agente") and str(step["agente"]) not in agent_ids:
                step.pop("agente", None)
            if step.get("cli") not in ("claude", "codex"):
                step["cli"] = "claude"
            if not isinstance(step.get("saida"), dict):
                step["saida"] = {}
            step["ferramentas"] = [t for t in step.get("ferramentas") or [] if t in tool_names or t == "*"]
        steps.append(step)
    ids = {s["id"] for s in steps}
    edges = []
    for raw in flow.get("ligacoes") or []:
        if not isinstance(raw, dict):
            continue
        src = str(raw.get("de") or "")
        dst = str(raw.get("para") or "")
        src = TRIGGER_ID if src == TRIGGER_ID else renamed.get(src, src)
        dst = renamed.get(dst, dst)
        if (src == TRIGGER_ID or src in ids) and dst in ids:
            edge = {"de": src, "para": dst}
            if raw.get("ramo"):
                edge["ramo"] = raw["ramo"]
            edges.append(edge)
    trigger = flow.get("gatilho") if isinstance(flow.get("gatilho"), dict) else {"tipo": "manual"}
    notes = [dict(n) for n in flow.get("notas") or [] if isinstance(n, dict)]
    return {
        "nome": str(flow.get("nome") or "").strip() or "Nova automação",
        "descricao": str(flow.get("descricao") or ""),
        "gatilho": dict(trigger),
        "passos": steps,
        "ligacoes": edges,
        "notas": notes,
    }, review


def _review_note(flow: dict, review: list[str]) -> None:
    if not review:
        return
    xs = [float(s.get("x") or 0) for s in flow["passos"]] or [0]
    ys = [float(s.get("y") or 0) for s in flow["passos"]] or [0]
    taken = {str(n.get("id")) for n in flow["notas"]}
    note_id = _unique_id("revisar", taken, "revisar")
    flow["notas"].append({"id": note_id, "titulo": "Revisar", "texto": "\n".join(f"- {line}" for line in review), "x": min(xs), "y": max(ys) + 160, "w": 300})


# --- proposta ---------------------------------------------------------------------------------


def propose(description: Any, current: Any, tools: list[dict], agents: list[dict], ask: Ask) -> dict:
    """{"proposta": desenho conferido (não salvo), "explicacao": texto}."""
    text = " ".join(str(description or "").split())
    if not 3 <= len(text) <= MAX_DESCRIPTION:
        raise ProposalInputError(f"descreva a automação em 3 a {MAX_DESCRIPTION} caracteres")
    if current is not None:
        try:
            current = automations.validate(current)
        except AutomationError as exc:
            raise ProposalInputError(f"o desenho atual não fecha: {exc}") from exc
        task = (
            "Desenho atual (JSON):\n" + json.dumps(current, ensure_ascii=False) + "\n\nO Pedro quer este ajuste:\n" + text +
            "\n\nDevolva o desenho inteiro já ajustado. Mantenha os ids, os títulos e as posições (x, y) do que não mudou."
        )  # fmt: skip
    else:
        task = "O Pedro quer esta automação:\n" + text
    tool_names = {str(t["nome"]) for t in tools}
    agent_ids = {str(a["id"]) for a in agents}
    prompt = PROMPT.format(catalog=STEP_CATALOG, tools=describe_tools(tools), agents=describe_agents(agents), task=task)
    error = ""
    for attempt in range(2):
        answer = ask(prompt if not error else prompt + f"\n\nA resposta anterior não fechou: {error}. Corrija e devolva o JSON inteiro de novo.")
        if not isinstance(answer, dict):
            raise ProposalError("o Claude não devolveu um objeto JSON")
        raw = answer.get("fluxo") if isinstance(answer.get("fluxo"), dict) else answer
        explanation = " ".join(str(answer.get("explicacao") or "").split())
        flow, review = repair(raw, tool_names, agent_ids)
        keep: dict[str, tuple[float, float]] = {}
        if current is not None:
            old = {s["id"]: s for s in current["passos"]}
            for step in flow["passos"]:
                prev = old.get(step["id"])
                if prev is not None and "x" in prev and "y" in prev:
                    keep[step["id"]] = (prev["x"], prev["y"])
            if "x" in current["gatilho"]:
                keep[TRIGGER_ID] = (current["gatilho"].get("x", 0), current["gatilho"].get("y", 0))
        layout(flow, keep)
        _review_note(flow, review)
        try:
            checked = automations.validate(flow)
        except AutomationError as exc:
            error = str(exc)
            continue
        if not explanation:
            explanation = f"Montei {len(checked['passos'])} passo(s) a partir da sua descrição. Confira cada um antes de aplicar."
        if review:
            explanation += " A nota Revisar no canvas lista o que precisa da sua conferência."
        return {"proposta": checked, "explicacao": explanation}
    raise ProposalError(f"o Claude devolveu um desenho que não fecha: {error}")


# --- código -------------------------------------------------------------------------------------


def _syntax_problem(code: str, language: str) -> str | None:
    if language == "python":
        try:
            compile(code, "<passo>", "exec")
        except SyntaxError as exc:
            return f"linha {exc.lineno}: {exc.msg}"
        return None
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "passo.cjs"
        # Igual ao motor: CommonJS, o código dentro de uma função async.
        path.write_text("let entrada, passos, saida = null;\n(async () => {\n" + code + "\n})();\n", encoding="utf-8")
        try:
            done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if done.returncode != 0:
            lines = [line for line in done.stderr.splitlines() if "SyntaxError" in line]
            return lines[0].strip() if lines else done.stderr.strip()[:200]
    return None


def write_code(description: Any, language: Any, example: Any, ask: Ask) -> dict:
    """{"codigo": str} na convenção do passo Código."""
    text = " ".join(str(description or "").split())
    if not 3 <= len(text) <= MAX_DESCRIPTION:
        raise ProposalInputError(f"descreva o passo em 3 a {MAX_DESCRIPTION} caracteres")
    lang = str(language or "").lower()
    if lang not in CODE_CONVENTION:
        raise ProposalInputError("linguagem é python ou javascript")
    sample = ""
    if example is not None:
        sample = "\nExemplo do que chega em `entrada`:\n" + json.dumps(example, ensure_ascii=False)[:3000] + "\n"
    prompt = CODE_PROMPT.format(convention=CODE_CONVENTION[lang], description=text, example=sample)
    error = ""
    for _ in range(2):
        answer = ask(prompt if not error else prompt + f"\n\nO código anterior tinha erro de sintaxe ({error}). Corrija.")
        code = str((answer or {}).get("codigo") or "").strip() if isinstance(answer, dict) else ""
        code = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", code).strip()
        if not code:
            raise ProposalError("o Claude não devolveu o código")
        problem = _syntax_problem(code, lang)
        if problem is None:
            if "saida" not in code:
                code += "\n" + ("saida = entrada" if lang == "python" else "saida = entrada;")
            return {"codigo": code}
        error = problem
    raise ProposalError(f"o código veio com erro de sintaxe: {error}")
