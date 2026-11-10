"""O que a barra de baixo oferece ao digitar "/" (v0.9.8) e a skill da MÊTIS para os agentes.

Comandos de barra: os do projeto e do usuário primeiro (os .md de commands do Claude, os
prompts do Codex), depois as skills, depois os da própria CLI, com uma descrição curta em
português. A skill da MÊTIS é um SKILL.md que ensina o agente a usar o app (o comando
`metis` e as ferramentas da central de MCP); instalar grava em <home>/skills/metis/.
"""

from __future__ import annotations

from pathlib import Path

from .system import frontmatter

CLAUDE_BUILTIN: list[tuple[str, str]] = [
    ("/clear", "limpa a conversa e começa do zero"),
    ("/compact", "resume a conversa para liberar contexto"),
    ("/context", "mostra o que ocupa a janela de contexto"),
    ("/cost", "custo e tokens desta sessão"),
    ("/model", "troca o modelo"),
    ("/review", "revisa um pull request"),
    ("/init", "cria o CLAUDE.md do projeto"),
    ("/memory", "edita os arquivos de memória (CLAUDE.md)"),
    ("/mcp", "servidores MCP desta sessão"),
    ("/agents", "subagentes"),
    ("/resume", "retoma uma conversa anterior"),
    ("/status", "versão, conta, modelo e conexões"),
    ("/config", "configurações do Claude Code"),
    ("/permissions", "regras de permissão das ferramentas"),
    ("/hooks", "hooks configurados"),
    ("/help", "ajuda e lista de comandos"),
]

CODEX_BUILTIN: list[tuple[str, str]] = [
    ("/model", "troca o modelo e o esforço"),
    ("/approvals", "o que o Codex pode fazer sem perguntar"),
    ("/new", "começa uma conversa nova"),
    ("/init", "cria o AGENTS.md do projeto"),
    ("/compact", "resume a conversa para liberar contexto"),
    ("/diff", "mostra o diff do git, com os arquivos novos"),
    ("/mention", "menciona um arquivo"),
    ("/status", "configuração e uso de tokens da sessão"),
    ("/review", "revisa as mudanças"),
    ("/quit", "sai do Codex"),
]


def describe(path: Path) -> str:
    """A description do frontmatter, ou a primeira linha com texto (sem os # de título)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:12000]
    except OSError:
        return ""
    found = frontmatter(text).get("description", "")  # entende description: > e | (várias linhas)
    if found:
        return found[:160]
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        body = text[end + 4 :] if end != -1 else text
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and line != "---":
            return line[:160]
    return ""


def _commands(folder: Path, origin: str, prefix: str = "/") -> list[dict]:
    out: list[dict] = []
    if not folder.is_dir():
        return out
    for path in sorted(folder.rglob("*.md")):
        rel = path.relative_to(folder).with_suffix("")
        name = ":".join(rel.parts)
        out.append({"nome": f"{prefix}{name}", "descricao": describe(path), "origem": origin})
    return out


def _skills(folder: Path) -> list[dict]:
    out: list[dict] = []
    if not folder.is_dir():
        return out
    for skill in sorted(folder.glob("*/SKILL.md")):
        out.append({"nome": f"/{skill.parent.name}", "descricao": describe(skill), "origem": "skill"})
    return out


def slash_commands(kind: str, home: Path, cwd: str) -> list[dict]:
    """Os comandos de "/" de uma sessão: home é a pasta da conta (~/.claude, CODEX_HOME…)."""
    if kind == "claude":
        found = _commands(Path(cwd) / ".claude" / "commands", "projeto") + _commands(home / "commands", "usuario")
        found += _skills(home / "skills")
        found += [{"nome": name, "descricao": text, "origem": "cli"} for name, text in CLAUDE_BUILTIN]
    elif kind == "codex":
        found = _commands(home / "prompts", "usuario", "/prompts:")
        found += [{"nome": name, "descricao": text, "origem": "cli"} for name, text in CODEX_BUILTIN]
    else:
        return []
    seen: set[str] = set()
    unique = []
    for item in found:
        if item["nome"] not in seen:
            seen.add(item["nome"])
            unique.append(item)
    return unique


# --- a skill da MÊTIS ------------------------------------------------------------------------

METIS_SKILL = """\
---
name: metis
description: Use dentro da MÊTIS (o ambiente do Pedro) para consultar e registrar no Brain, mover tarefas do kanban, agendar lembretes, abrir páginas no navegador da MÊTIS, ler outros terminais, rodar automações, criar worktrees e abrir outros agentes. Use também antes de uma decisão técnica relevante (brain conflitos).
---

# MÊTIS

A MÊTIS é o ambiente do Pedro no Mac: terminais do Claude e do Codex por worktree, o Brain
(o vault do Obsidian em ~/Documents/Brain) como memória, kanban, rotinas, automações e
conectores. Você roda num terminal dela: o comando `metis` e o servidor MCP "metis" já estão
à mão. Responda e registre sempre em português do Brasil.

## Comando `metis` (no terminal)

- `metis brain buscar <termos>` — busca no Brain. Ex.: `metis brain buscar webhook guru --tipo decisao`
- `metis brain ler "<título>"` — lê uma nota. Ex.: `metis brain ler "Webhook passa por fila"`
- `metis brain precedentes` — o que outros projetos já decidiram, parecido com este.
- `metis brain conflitos "<decisão>"` — antes de decidir: repetição, contradição e precedentes.
- `metis tarefas` e `metis tarefa mover <id> <estado>` — Próximas ações do projeto (pendente, em-andamento, em-teste, concluida). Ex.: `metis tarefa mover 4ea9e8ea em-teste`
- `metis lembrete "<texto>" <quando>` — o bot do Slack avisa o Pedro na hora. Ex.: `metis lembrete "revisar o PR" amanhã 9h`
- `metis web <endereço>` — abre uma aba no navegador da MÊTIS. Ex.: `metis web localhost:5173`
- `metis sessoes` e `metis sessao ler|escrever <id>` — outros terminais abertos. Ex.: `metis sessao ler 6d57ea05`
- `metis automacoes` e `metis rodar <automação>` — automações publicadas. Ex.: `metis rodar "Briefing da manhã"`
- `metis worktree nova <projeto> <nome>` — worktree nova para outra tarefa. Ex.: `metis worktree nova personal-harness corrige-login`
- `metis agente <claude|codex|agente> [pedido]` — abre outro agente num terminal. Ex.: `metis agente codex --pasta . "rode os testes e conserte o que falhar"`
- `metis versao` — a versão da MÊTIS em uso.
- `--json` nos comandos de listar dá a saída em JSON.

## Ferramentas da central de MCP "metis"

- `brain_buscar`, `brain_ler`, `brain_precedentes`, `brain_conflitos` — o Brain.
- `tarefas`, `tarefa_mover`, `tarefa_nova` — o kanban do projeto desta pasta.
- `lembrete` — mensagem do bot do Slack na DM do Pedro, na hora marcada.
- `codigo_grafo_consultar`, `codigo_grafo_caminho`, `codigo_grafo_explicar` — o grafo do código desta pasta (graphify), quando o repositório tem graphify-out/: pergunte a ele antes de sair lendo arquivo por arquivo.
- Ferramentas de cada conta conectada (Slack, ClickUp…), com o id da conta na frente.
- `saida` — só nas automações: devolve o resultado do passo no formato combinado.

## Navegador da MÊTIS

Pela central de MCP você usa o navegador da MÊTIS, na aba da worktree desta pasta, e o Pedro vê o
seu cursor agindo na página:

- `navegador_abrir` (endereço ou aba nova), `navegador_abas`, `navegador_fechar`.
- `navegador_ler` — o texto da página com refs como [e12]. Rode antes de agir.
- `navegador_clicar`, `navegador_digitar`, `navegador_tecla`, `navegador_escolher`, `navegador_passar`, `navegador_rolar` — pela ref (ou seletor CSS).
- `navegador_ir` (voltar, avançar, recarregar) e `navegador_esperar` (um texto ou seletor aparecer).
- `navegador_foto`, `navegador_console`, `navegador_rede` e `navegador_js` — para conferir e depurar.

Regras do navegador: use `navegador_ler` antes de agir e as refs [eN] que ele mostra; nunca digite senha,
dado de cartão nem documento: peça ao Pedro; envio que fala com outras pessoas (formulário, compra,
mensagem) só com o Pedro de acordo. `navegador_js` e `navegador_digitar` com `enviar` esperam a aprovação
do Pedro na MÊTIS.

## Regras

- O que fala com outras pessoas (mensagem em canal, criar ou mudar algo no ClickUp) espera a aprovação do Pedro na MÊTIS: peça e aguarde, não contorne.
- Antes de registrar uma decisão no Brain, rode `brain_conflitos` (ou `metis brain conflitos`) com a decisão numa frase; se contradiz algo, diga ao Pedro.
- Nunca apague nota do Brain; decisão revista é substituída, não apagada.
"""


def skill_state(homes: dict[str, list[Path]]) -> dict:
    """homes: as pastas de cada CLI (a padrão primeiro, depois as das contas extras)."""
    return {
        "texto": METIS_SKILL,
        "instalada": {cli: bool(homes[cli]) and (homes[cli][0] / "skills" / "metis" / "SKILL.md").is_file() for cli in ("claude", "codex")},
    }


def install_skill(homes: dict[str, list[Path]], destino: str) -> dict:
    """Grava o SKILL.md em <home>/skills/metis/ de cada pasta da CLI escolhida (ou das duas)."""
    targets = ("claude", "codex") if destino == "ambos" else (destino,)
    for cli in targets:
        for home in homes[cli]:
            folder = home / "skills" / "metis"
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / "SKILL.md.tmp"
            tmp.write_text(METIS_SKILL, encoding="utf-8")
            tmp.replace(folder / "SKILL.md")
    return skill_state(homes)
