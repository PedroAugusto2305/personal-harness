"""Estratégias de orquestração (v0.9.8, parte 4): desenhos prontos de vários agentes no canvas.

Cada estratégia vira um RASCUNHO de automação comum (gatilho manual, passos de agente,
condição e aprovação), que o Pedro ajusta e publica como qualquer outra. Todos os agentes
trocam de provedor quando a cota da janela de 5 h passa de 80% (`troca_cota`).
"""

from __future__ import annotations

from typing import Any

from .automations import AutomationError, validate

CLIS = ("claude", "codex")

TASK = {"nome": "tarefa", "rotulo": "O que fazer", "tipo": "texto", "padrao": ""}
FOLDER = {"nome": "pasta", "rotulo": "Pasta (worktree) onde os agentes trabalham", "tipo": "pasta", "padrao": ""}

STRATEGIES: list[dict] = [
    {
        "id": "explorar-e-construir",
        "nome": "Explorar e construir",
        "descricao": "Um agente lê o código e planeja sem mexer em nada; outro implementa o plano.",
        "parametros": [TASK, FOLDER, {"nome": "cli", "rotulo": "Quem constrói", "tipo": "cli", "padrao": "claude"}],
    },
    {
        "id": "planejar-e-executar",
        "nome": "Planejar grande, executar pequeno",
        "descricao": "Um planejador quebra a tarefa em até 5 etapas; um executor faz uma a uma; um revisor confere.",
        "parametros": [
            TASK,
            FOLDER,
            {"nome": "planejador", "rotulo": "Quem planeja", "tipo": "cli", "padrao": "claude"},
            {"nome": "executor", "rotulo": "Quem executa", "tipo": "cli", "padrao": "codex"},
        ],
    },
    {
        "id": "melhor-de-n",
        "nome": "Melhor de N",
        "descricao": "N agentes propõem uma solução em paralelo (sem editar), um juiz escolhe e um construtor aplica.",
        "parametros": [TASK, FOLDER, {"nome": "n", "rotulo": "Quantas propostas (2 a 5)", "tipo": "numero", "padrao": 3}],
    },
    {
        "id": "portao-de-revisao",
        "nome": "Portão de revisão",
        "descricao": "Um construtor faz, um revisor aprova ou aponta problemas; aprovado vai para você, reprovado volta para correção.",
        "parametros": [TASK, FOLDER, {"nome": "cli", "rotulo": "Quem constrói", "tipo": "cli", "padrao": "claude"}],
    },
]


class StrategyError(ValueError):
    pass


def catalog() -> list[dict]:
    return [dict(s) for s in STRATEGIES]


def _cli(value: Any, default: str) -> str:
    return str(value) if value in CLIS else default


def _other(cli: str) -> str:
    return "codex" if cli == "claude" else "claude"


def _agent(sid: str, title: str, cli: str, request: str, output: dict, x: int, y: int, folder: str) -> dict:
    step = {"id": sid, "titulo": title, "tipo": "agente", "cli": cli, "pedido": request, "saida": output, "troca_cota": True, "x": x, "y": y}
    if folder:
        step["pasta"] = folder
    return step


def build(strategy_id: str, params: dict | None) -> dict:
    """O desenho da estratégia com os parâmetros do Pedro (já conferido pelo validate)."""
    params = dict(params or {})
    task = " ".join(str(params.get("tarefa") or "").split())
    if not task:
        raise StrategyError("diga o que os agentes vão fazer (tarefa)")
    folder = str(params.get("pasta") or "").strip()
    builders = {
        "explorar-e-construir": _explore,
        "planejar-e-executar": _plan,
        "melhor-de-n": _best_of_n,
        "portao-de-revisao": _gate,
    }
    builder = builders.get(strategy_id)
    if builder is None:
        raise StrategyError(f"estratégia desconhecida: {strategy_id}")
    flow = builder(task, folder, params)
    try:
        return validate(flow)
    except AutomationError as exc:  # desenho pronto que não fecha é erro nosso
        raise StrategyError(f"a estratégia não fechou: {exc}") from exc


def _base(name: str, task: str, steps: list[dict], edges: list[dict], note: str) -> dict:
    return {
        "nome": f"{name}: {task[:60]}",
        "descricao": note,
        "gatilho": {"tipo": "manual", "x": 0, "y": 0},
        "passos": steps,
        "ligacoes": edges,
        "notas": [{"id": "n1", "titulo": "Como funciona", "texto": note, "x": 0, "y": 220, "w": 300}],
    }


def _explore(task: str, folder: str, params: dict) -> dict:
    builder = _cli(params.get("cli"), "claude")
    steps = [
        _agent(
            "explorar",
            "Explorador",
            "claude",
            f"Tarefa: {task}\n\nSó leia e investigue o código (não edite nada). Entenda onde mexer, o que pode quebrar e como testar. Monte um plano em passos curtos.",
            {"plano": "texto"},
            300,
            0,
            folder,
        ),
        _agent(
            "construir",
            "Construtor",
            builder,
            f"Tarefa: {task}\n\nSiga este plano do explorador e implemente, rodando os testes no fim:\n{{{{Explorador.plano}}}}",
            {"resumo": "texto"},
            600,
            0,
            folder,
        ),
    ]
    edges = [{"de": "gatilho", "para": "explorar"}, {"de": "explorar", "para": "construir"}]
    return _base("Explorar e construir", task, steps, edges, "O explorador só lê e planeja; o construtor implementa o plano. Os dois trocam de provedor se a cota passar de 80%.")


def _plan(task: str, folder: str, params: dict) -> dict:
    planner = _cli(params.get("planejador"), "claude")
    executor = _cli(params.get("executor"), _other(planner))
    steps = [
        _agent(
            "planejar",
            "Planejador",
            planner,
            f"Tarefa: {task}\n\nNão edite nada. Quebre a tarefa em no máximo 5 etapas pequenas, cada uma testável sozinha, na ordem certa. Cada item da lista é uma frase com o que fazer e como conferir.",
            {"etapas": "lista"},
            300,
            0,
            folder,
        ),
        _agent(
            "executar",
            "Executor",
            executor,
            f"Tarefa: {task}\n\nFaça estas etapas uma a uma, conferindo cada uma antes da próxima:\n{{{{Planejador.etapas}}}}\n\nNo fim, diga o que ficou pronto e o que não deu.",
            {"resumo": "texto"},
            600,
            0,
            folder,
        ),
        _agent(
            "revisar",
            "Revisor",
            planner,
            f"Tarefa: {task}\n\nRevise em poucas linhas o que o executor fez (git diff na pasta) contra as etapas:\n{{{{Planejador.etapas}}}}\n\nResumo do executor: {{{{Executor.resumo}}}}",
            {"parecer": "texto"},
            900,
            0,
            folder,
        ),
    ]
    edges = [{"de": "gatilho", "para": "planejar"}, {"de": "planejar", "para": "executar"}, {"de": "executar", "para": "revisar"}]
    return _base("Planejar e executar", task, steps, edges, "O planejador quebra em até 5 etapas, o executor faz uma a uma e o revisor confere o diff.")


def _best_of_n(task: str, folder: str, params: dict) -> dict:
    try:
        n = int(params.get("n") or 3)
    except (TypeError, ValueError):
        n = 3
    n = max(2, min(5, n))
    steps: list[dict] = []
    edges: list[dict] = []
    top = -(n - 1) * 140 // 2
    for i in range(n):
        cli = CLIS[i % 2]
        sid = f"proposta-{i + 1}"
        steps.append(
            _agent(
                sid,
                f"Proposta {i + 1}",
                cli,
                f"Tarefa: {task}\n\nProponha uma solução completa, mas NÃO edite arquivos (outros agentes propõem ao mesmo tempo na mesma pasta). Descreva as mudanças com trechos de código e diga por que a sua é a melhor.",
                {"proposta": "texto", "justificativa": "texto"},
                300,
                top + i * 140,
                folder,
            )
        )
        edges.append({"de": "gatilho", "para": sid})
    listing = "\n\n".join(f"Proposta {i + 1}:\n{{{{Proposta {i + 1}.proposta}}}}\nPor quê: {{{{Proposta {i + 1}.justificativa}}}}" for i in range(n))
    steps.append(
        _agent(
            "juiz",
            "Juiz",
            "claude",
            f"Tarefa: {task}\n\nCompare as propostas e escolha a melhor (correção, simplicidade, risco). Não edite nada.\n\n{listing}",
            {"escolhida": "numero", "motivo": "texto"},
            600,
            0,
            folder,
        )
    )
    steps.append(
        _agent(
            "aplicar",
            "Construtor",
            "claude",
            f"Tarefa: {task}\n\nO juiz escolheu a proposta {{{{Juiz.escolhida}}}} ({{{{Juiz.motivo}}}}). Aplique essa proposta na pasta e rode os testes.\n\n{listing}",
            {"resumo": "texto"},
            900,
            0,
            folder,
        )
    )
    for i in range(n):
        edges.append({"de": f"proposta-{i + 1}", "para": "juiz"})
    edges.append({"de": "juiz", "para": "aplicar"})
    return _base("Melhor de N", task, steps, edges, f"{n} agentes (alternando Claude e Codex) propõem em paralelo sem editar; o juiz escolhe e o construtor aplica a escolhida.")


def _gate(task: str, folder: str, params: dict) -> dict:
    builder = _cli(params.get("cli"), "claude")
    reviewer = _other(builder)
    steps = [
        _agent("construir", "Construtor", builder, f"Tarefa: {task}\n\nImplemente e rode os testes.", {"resumo": "texto"}, 300, 0, folder),
        _agent(
            "revisar",
            "Revisor",
            reviewer,
            f"Tarefa: {task}\n\nRevise o que o construtor fez (git diff na pasta): bugs, testes faltando, o que foge da tarefa. Resumo dele: {{{{Construtor.resumo}}}}\nNão edite nada.",
            {"aprovado": "sim/nao", "problemas": "texto"},
            600,
            0,
            folder,
        ),
        {"id": "aprovado", "titulo": "Aprovado?", "tipo": "condicao", "regra": "{{Revisor.aprovado}} == true", "x": 900, "y": 0},
        {
            "id": "pedro",
            "titulo": "Sua aprovação",
            "tipo": "aprovacao",
            "mensagem": f"O revisor aprovou: {task[:120]}. Pode seguir?",
            "prazo_min": 240,
            "x": 1180,
            "y": -90,
        },
        _agent(
            "corrigir",
            "Corretor",
            builder,
            f"Tarefa: {task}\n\nO revisor apontou estes problemas; corrija e rode os testes:\n{{{{Revisor.problemas}}}}",
            {"resumo": "texto"},
            1180,
            90,
            folder,
        ),
        _agent(
            "revisar-2",
            "Revisor 2",
            reviewer,
            f"Tarefa: {task}\n\nConfira se a correção resolveu estes problemas (git diff na pasta):\n{{{{Revisor.problemas}}}}\nResumo do corretor: {{{{Corretor.resumo}}}}\nNão edite nada.",
            {"aprovado": "sim/nao", "problemas": "texto"},
            1480,
            90,
            folder,
        ),
    ]
    edges = [
        {"de": "gatilho", "para": "construir"},
        {"de": "construir", "para": "revisar"},
        {"de": "revisar", "para": "aprovado"},
        {"de": "aprovado", "para": "pedro", "ramo": "sim"},
        {"de": "aprovado", "para": "corrigir", "ramo": "não"},
        {"de": "corrigir", "para": "revisar-2"},
    ]
    return _base("Portão de revisão", task, steps, edges, "O construtor faz, o revisor (no outro provedor) aprova ou aponta problemas; aprovado vai para você, reprovado passa por uma correção e uma segunda revisão.")
