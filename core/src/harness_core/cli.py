"""Comando `metis` (antes `harness`, que segue como apelido): contas e troca de conta pelo terminal.

    metis contas                       lista as contas e qual está ativa
    metis switch <claude|codex> <conta> passa a usar outra conta nas sessões novas
    metis login <claude|codex> <nome>   cria a conta e abre o login oficial aqui
    metis web [endereço]               abre uma aba do navegador da MÊTIS (ex.: localhost:5173)
    metis brain buscar <termos>        busca no Brain (--tipo decisao, --projeto "Nome")
    metis brain ler "<título>"         mostra uma nota do Brain
    metis brain precedentes [termos]   registros de outros projetos parecidos com este
    metis brain conflitos "<decisão>"  antes de decidir: repetição, contradição e precedentes
    metis brain sugestoes              sugestões de precedente esperando o Pedro neste projeto
    metis brain mcp                    servidor MCP do Brain por stdio (para sessões fora da MÊTIS)
    metis brain contexto               hook SessionStart fora da MÊTIS (lê o JSON do Claude no stdin)
    metis tarefas                      as Próximas ações do projeto desta pasta, com o id
    metis tarefa nova "<texto>"        acrescenta uma tarefa (--descricao, --prioridade, --entrega,
                                       --inicio, --rotulo e --subtarefa, estes dois repetíveis)
    metis tarefa mover <id> <estado>   pendente, em-andamento, em-teste ou concluida
    metis lembrete "<texto>" <quando>  o bot da MÊTIS avisa no Slack na hora (ex.: sexta 9h, em 20 min)
    metis desligar                     desliga a MÊTIS de vez (fecha os terminais dos agentes)
    metis sessoes                      os terminais abertos na MÊTIS, com o id
    metis sessao ler <id>              o fim do terminal (ou as últimas mensagens do agente)
    metis sessao escrever <id> "texto" manda o texto para o terminal (como a barra de baixo)
    --json                             nos comandos de listar: a saída em JSON, para agentes
    metis automacoes                   as automações, com estado e a última execução
    metis rodar <automação>            roda a versão publicada agora (id ou nome)
    metis worktree nova <projeto> <nome> [--base REF | --commit SHA] [--sem-env]
                                       worktree nova (projeto por id ou nome); imprime pasta e branch
    metis worktree nova <projeto> [nome] --branch B
                                       abre um branch que já existe (local ou origin/…) numa worktree
    metis agente <claude|codex|agente> [--pasta P] [--modelo M] [--esforco E] [--titulo T] [pedido ...]
                                       abre um agente num terminal da MÊTIS (pasta padrão: a atual)
    metis versao                       a versão em uso e se há uma nova (na MÊTIS instalada)
    metis atualizar [versão]           instala a versão nova (ou a pedida) aqui, neste terminal

O login acontece sempre no fluxo oficial da CLI, numa pasta só daquela conta.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request

from .accounts import ENV_VAR, PROVIDERS, AccountStore, UnknownAccount
from .config import load_settings


def _notify_core(home) -> None:
    """Avisa o núcleo, se estiver rodando, para a janela atualizar as contas."""
    runtime = home / "runtime.json"
    try:
        info = json.loads(runtime.read_text(encoding="utf-8"))
        request = urllib.request.Request(
            f"{info['url']}/accounts/reload", method="POST", headers={"X-Harness-Token": info["token"]}
        )
        urllib.request.urlopen(request, timeout=2)
    except (OSError, ValueError, KeyError):
        pass


def _core_post(home, path: str, body: dict) -> None:
    """POST no núcleo em execução, achado pelo runtime.json."""
    info = json.loads((home / "runtime.json").read_text(encoding="utf-8"))
    request = urllib.request.Request(
        f"{info['url']}{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"X-Harness-Token": info["token"], "Content-Type": "application/json"},
    )
    urllib.request.urlopen(request, timeout=3)


def _core(home, method: str, path: str, body: dict | None = None):
    """Chamada ao núcleo em execução; devolve o JSON (ou o texto) da resposta."""
    info = json.loads((home / "runtime.json").read_text(encoding="utf-8"))
    headers = {"X-Harness-Token": info["token"], "Content-Type": "application/json"}
    if os.environ.get("HARNESS_SESSION_ID"):
        # v1.1: num terminal da MÊTIS, a atividade da tarefa diz qual agente mexeu nela.
        headers["X-Harness-Session"] = os.environ["HARNESS_SESSION_ID"]
    request = urllib.request.Request(
        f"{info['url']}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except ValueError:
            detail = None
        raise CoreRefused(str(detail or exc)) from exc
    try:
        return json.loads(raw)
    except ValueError:
        return raw


class CoreRefused(Exception):
    pass


STATE_ALIASES = {
    "pendente": "pendente",
    "andamento": "em-andamento",
    "em-andamento": "em-andamento",
    "fazendo": "em-andamento",
    "teste": "em-teste",
    "em-teste": "em-teste",
    "testando": "em-teste",
    "concluida": "concluida",
    "concluída": "concluida",
    "feita": "concluida",
    "feito": "concluida",
}
STATE_LABEL = {"pendente": "Pendente", "em-andamento": "Em andamento", "em-teste": "Em teste", "concluida": "Concluído"}
TYPE_ICON = {"decisao": "⚖️", "incidente": "🔥", "aprendizado": "💡", "entrega": "🛠️", "projeto": "🎯"}


def _q(params: dict) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v})


def _clean_snippet(text: str | None) -> str:
    return (text or "").replace("\x02", "").replace("\x03", "").replace("\n", " ").strip()


def _here_project(home, explicit: str | None) -> str:
    if explicit:
        return explicit
    place = _core(home, "GET", f"/brain/place?{_q({'cwd': os.getcwd()})}")
    project = (place or {}).get("project")
    if not project:
        raise CoreRefused("esta pasta não é de nenhum projeto do Brain (diretorio: na nota do projeto); use --projeto \"Nome\"")
    return project["name"]


def _brain_command(home, args) -> int:
    if args.acao == "buscar":
        items = _core(home, "GET", f"/brain/search?{_q({'q': ' '.join(args.termos), 'tipo': args.tipo, 'projeto': args.projeto, 'limit': args.limite})}")
        if args.json:
            print(json.dumps([{**i, "snippet": _clean_snippet(i.get("snippet"))} for i in items], ensure_ascii=False))
            return 0
        if not items:
            print("nada encontrado.")
        for item in items:
            where = " · ".join(x for x in (item["tipo"], item["projeto"], item["status"], item["data"]) if x)
            print(f"{TYPE_ICON.get(item['tipo'], '·')} {item['title']}  ({where})")
            snippet = _clean_snippet(item.get("snippet") or item.get("resumo"))
            if snippet:
                print(f"   {snippet[:240]}")
        return 0
    if args.acao == "ler":
        target = " ".join(args.termos)
        key = "path" if target.endswith(".md") else "title"
        note = _core(home, "GET", f"/brain/note?{_q({key: target})}")
        print(f"# {note['title']}  ({note['path']})")
        print(note["body"].strip())
        if note["backlinks"]:
            print("\nCitada por: " + "; ".join(b["title"] for b in note["backlinks"][:20]))
        return 0
    if args.acao == "conflitos":
        project = args.projeto
        if not project:
            try:
                project = _here_project(home, None)
            except CoreRefused:
                project = ""
        found = _core(home, "GET", f"/brain/conflitos?{_q({'q': ' '.join(args.termos), 'project': project})}")
        print(f"busca por {found['via']}")
        if project:
            print(f"decisões parecidas em {project}:")
            for item in found["same"] or [{"title": "nenhuma", "status": "", "resumo": ""}]:
                print(f"  ⚖️ {item['title']}" + (f" ({item['status']})" if item.get("status") else ""))
        print("registros parecidos em outros projetos:")
        for item in found["other"] or [{"title": "nenhum", "projeto": "", "tipo": ""}]:
            print(f"  {TYPE_ICON.get(item.get('tipo', ''), '·')} {item['title']}" + (f" ({item['projeto']})" if item.get("projeto") else ""))
        return 0
    if args.acao == "sugestoes":
        project = _here_project(home, args.projeto)
        items = _core(home, "GET", f"/brain/sugestoes?{_q({'project': project})}")
        if not items:
            print(f"nenhuma sugestão pendente em {project}.")
        for item in items:
            print(f"💡 #{item['id']} {item['title']}\n   de {item['source_title']} ({item['source_project']}): {item['motivo']}")
        return 0
    # precedentes
    project = args.projeto
    if not project:
        try:
            project = _here_project(home, None)
        except CoreRefused:
            project = ""
    items = _core(home, "GET", f"/brain/precedents?{_q({'project': project, 'q': ' '.join(args.termos), 'limit': args.limite})}")
    if not items:
        print("nenhum registro de outro projeto bateu.")
    for item in items:
        print(f"{TYPE_ICON.get(item['tipo'], '·')} {item['title']}  ({item['projeto']}{' · ' + item['status'] if item['status'] else ''})")
        if item.get("resumo"):
            print(f"   {item['resumo'][:260]}")
    return 0


def _tasks_command(home, args) -> int:
    project = _here_project(home, args.projeto)
    if args.command == "tarefas":
        tasks = _core(home, "GET", f"/brain/projects/{urllib.parse.quote(project, safe='')}/tasks")
        if args.json:
            print(json.dumps({"projeto": project, "tarefas": tasks}, ensure_ascii=False))
            return 0
        print(f"Próximas ações de {project}:")
        for state in ("em-andamento", "em-teste", "pendente", "concluida"):
            group = [t for t in tasks if t["state"] == state]
            if state == "concluida" and not args.todas:
                if group:
                    print(f"\n{STATE_LABEL[state]}: {len(group)} (use --todas para ver)")
                continue
            if not group:
                continue
            print(f"\n{STATE_LABEL[state]}:")
            for task in group:
                sub = f" [{task['subtasks_done']}/{task['subtasks_total']}]" if task["subtasks_total"] else ""
                print(f"  {task['id']}  {task['text'][:200]}{sub}")
        return 0
    base = f"/brain/projects/{urllib.parse.quote(project, safe='')}/tasks"
    if args.acao == "nova":
        state = STATE_ALIASES.get(args.estado, args.estado)
        payload = {"text": " ".join(args.resto), "state": state, "rotulos": args.rotulo, "subtarefas": args.subtarefa}
        for key in ("descricao", "prioridade", "inicio", "entrega"):
            if getattr(args, key):
                payload[key] = getattr(args, key)
        task = _core(home, "POST", base, payload)
        print(f"tarefa {task['id']} criada em {project} ({STATE_LABEL[task['state']]})")
        return 0
    if len(args.resto) != 2:
        raise CoreRefused("uso: metis tarefa mover <id> <estado>")
    task_id, state = args.resto
    state = STATE_ALIASES.get(state.lower(), state.lower())
    task = _core(home, "PUT", f"{base}/{urllib.parse.quote(task_id, safe='')}", {"state": state})
    print(f"{task['id']} → {STATE_LABEL[task['state']]}: {task['text'][:120]}")
    return 0


def web_url(target: str) -> str:
    """localhost:5173 → http://localhost:5173; exemplo.com → https://exemplo.com."""
    target = target.strip()
    if not target or "://" in target or target == "about:blank":
        return target
    host = target.split("/", 1)[0].split(":", 1)[0]
    local = host in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]") or host.endswith(".localhost") or host.endswith(".test")
    if target.isdigit():
        return f"http://localhost:{target}"
    return f"{'http' if local else 'https'}://{target}"


def _worktree_command(home, args) -> int:
    """metis worktree nova <projeto> <nome>: o projeto vale por id ou por nome (sem caixa)."""
    wanted = args.projeto.strip().casefold()
    project = next((p for p in _core(home, "GET", "/projects") if p["id"] == args.projeto or p["name"].casefold() == wanted), None)
    if project is None:
        raise CoreRefused(f"projeto não encontrado: {args.projeto}. Os projetos são os da barra lateral da MÊTIS.")
    if args.branch:
        body = {"name": args.nome, "base": args.branch, "copy_env": not args.sem_env, "modo": "branch"}
    elif not args.nome:
        raise CoreRefused("diga o nome da worktree (ou --branch para abrir um branch que já existe)")
    elif args.commit:
        body = {"name": args.nome, "base": args.commit, "copy_env": not args.sem_env, "modo": "commit"}
    else:
        body = {"name": args.nome, "base": args.base or None, "copy_env": not args.sem_env}
    created = _core(home, "POST", f"/projects/{urllib.parse.quote(project['id'], safe='')}/worktrees", body)
    if args.json:
        print(json.dumps(created, ensure_ascii=False))
        return 0
    print(f"worktree nova: {created['path']}")
    print(f"branch: {created.get('branch') or '(sem branch)'}")
    if created.get("setup"):
        print(f"o setup do projeto roda no terminal {created['setup']}.")
    return 0


def _agent_command(home, args) -> int:
    """metis agente <claude|codex|nome-ou-id>: sessão nova na MÊTIS, com o pedido já entrando."""
    body: dict = {"cwd": os.path.abspath(os.path.expanduser(args.pasta or os.getcwd()))}
    if args.alvo in PROVIDERS:
        body["kind"] = args.alvo
    else:
        wanted = args.alvo.strip().casefold()
        agent = next((a for a in _core(home, "GET", "/agents") if a["id"] == args.alvo or a["name"].casefold() == wanted), None)
        if agent is None:
            raise CoreRefused(f"agente não encontrado: {args.alvo}. Use claude, codex ou o nome de um agente da MÊTIS.")
        body["kind"] = agent["cli"] if agent["cli"] in PROVIDERS else "shell"
        body["agent"] = agent["id"]
    if args.modelo:
        body["model"] = args.modelo
    if args.esforco:
        body["effort"] = args.esforco
    if args.titulo:
        body["title"] = args.titulo
    prompt = " ".join(args.pedido).strip()
    if prompt:
        body["prompt"] = prompt
    session = _core(home, "POST", "/sessions", body)
    if args.json:
        print(json.dumps({k: session.get(k) for k in ("id", "title", "kind", "status", "cwd", "agent")}, ensure_ascii=False))
        return 0
    print(f"{session['id']}  {session['title']}")
    return 0


def _print_accounts(store: AccountStore) -> None:
    for provider, entry in store.list().items():
        print(provider)
        for account in entry["accounts"]:
            mark = "●" if account["active"] else " "
            where = account["dir"] or "pasta padrão da CLI"
            print(f"  {mark} {account['name']:<16} {account['id']:<16} {where}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="metis", description="Contas, navegador, Brain, tarefas e lembretes da MÊTIS.")
    parser.add_argument("--json", action="store_true", help="saída em JSON (contas, brain buscar, tarefas, sessões, automações, worktree, agente)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("contas", help="lista as contas e qual está ativa")
    switch = sub.add_parser("switch", help="troca a conta ativa de uma CLI")
    switch.add_argument("provider", choices=PROVIDERS)
    switch.add_argument("conta")
    login = sub.add_parser("login", help="cria uma conta e abre o login oficial neste terminal")
    login.add_argument("provider", choices=PROVIDERS)
    login.add_argument("nome")
    web = sub.add_parser("web", help="abre uma aba do navegador da MÊTIS")
    web.add_argument("endereco", nargs="?", default="", help="endereço ou porta (ex.: 5173, localhost:3000, exemplo.com)")
    brain = sub.add_parser("brain", help="busca, leitura e precedentes do Brain")
    brain.add_argument("acao", choices=("buscar", "ler", "precedentes", "conflitos", "sugestoes", "mcp", "contexto"))
    brain.add_argument("termos", nargs="*")
    brain.add_argument("--tipo", default="", help="decisao, incidente, aprendizado, entrega, projeto (vírgula para vários)")
    brain.add_argument("--projeto", default="")
    brain.add_argument("--limite", type=int, default=12)
    tasks = sub.add_parser("tarefas", help="as Próximas ações do projeto desta pasta")
    tasks.add_argument("--projeto", default="")
    tasks.add_argument("--todas", action="store_true", help="mostra também as concluídas")
    task = sub.add_parser("tarefa", help="cria ou move uma tarefa do kanban")
    task.add_argument("acao", choices=("nova", "mover"))
    task.add_argument("resto", nargs="+", help='nova: "texto"; mover: <id> <estado>')
    task.add_argument("--projeto", default="")
    task.add_argument("--estado", default="pendente", help="estado inicial de uma tarefa nova")
    task.add_argument("--descricao", default="", help="nova: Markdown do corpo do cartão")
    task.add_argument("--prioridade", default="", help="nova: urgente, alta, media, normal, baixa ou minima")
    task.add_argument("--inicio", default="", help="nova: data de início, AAAA-MM-DD")
    task.add_argument("--entrega", default="", help="nova: prazo, AAAA-MM-DD")
    task.add_argument("--rotulo", action="append", default=[], help="nova: rótulo sem o # (repetível)")
    task.add_argument("--subtarefa", action="append", default=[], help="nova: etapa, na ordem (repetível)")
    reminder = sub.add_parser("lembrete", help="agenda um lembrete no Slack (toca no iPhone)")
    reminder.add_argument("texto")
    reminder.add_argument("quando", nargs="+", help="ex.: sexta 9h, amanhã 14:30, em 20 min, 13/11 9h")
    reminder.add_argument("--conta", default="", help="id da conta do Slack (padrão: a de lembretes)")
    sub.add_parser("desligar", help="desliga o núcleo da MÊTIS (fecha os terminais dos agentes)")
    sub.add_parser("sessoes", help="os terminais abertos na MÊTIS")
    one = sub.add_parser("sessao", help="lê ou escreve num terminal da MÊTIS")
    one.add_argument("acao", choices=("ler", "escrever"))
    one.add_argument("id")
    one.add_argument("texto", nargs="*")
    sub.add_parser("automacoes", help="as automações, com estado e a última execução")
    run = sub.add_parser("rodar", help="roda a versão publicada de uma automação agora")
    run.add_argument("automacao", nargs="+", help="id ou nome da automação")
    worktree = sub.add_parser("worktree", help="cria uma worktree num projeto da MÊTIS")
    worktree.add_argument("acao", choices=("nova",))
    worktree.add_argument("projeto", help="id ou nome do projeto")
    worktree.add_argument("nome", nargs="?", default="", help="nome da worktree (vira a branch; com --branch é opcional)")
    start = worktree.add_mutually_exclusive_group()
    start.add_argument("--base", default="", help="branch, tag ou commit de partida (padrão: o atual)")
    start.add_argument("--branch", default="", help="abre um branch que já existe (local ou origin/…) em vez de criar um")
    start.add_argument("--commit", default="", help="branch novo com o nome, a partir deste commit")
    worktree.add_argument("--sem-env", action="store_true", help="não copia os .env do projeto")
    agent = sub.add_parser("agente", help="abre o Claude, o Codex ou um agente da MÊTIS num terminal")
    agent.add_argument("alvo", help="claude, codex ou o nome (ou id) de um agente")
    agent.add_argument("pedido", nargs="*", help="o que pedir ao agente (opcional)")
    agent.add_argument("--pasta", default="", help="pasta da sessão (padrão: a atual)")
    agent.add_argument("--modelo", default="", help="modelo só desta sessão")
    agent.add_argument("--esforco", default="", choices=("", "low", "medium", "high", "xhigh"), help="esforço (só no Codex)")
    agent.add_argument("--titulo", default="", help="título da aba")
    sub.add_parser("versao", help="a versão em uso e se há uma nova")
    upgrade = sub.add_parser("atualizar", help="instala a versão nova da MÊTIS neste terminal")
    upgrade.add_argument("versao", nargs="?", default="", help="ex.: v0.9.5 (padrão: a mais nova)")
    args = parser.parse_args(argv)

    home = load_settings().home

    if args.command in ("versao", "atualizar"):
        from . import updates

        info = updates.check(home, fetch=True)
        if args.command == "versao":
            if args.json:
                print(json.dumps(info, ensure_ascii=False))
                return 0
            where = f"instalada ({info['tag']})" if info["instalada"] else f"de desenvolvimento, em {info['pasta']}"
            print(f"MÊTIS v{info['versao']} · {where}")
            if info["nova"]:
                print(f"versão nova: {info['nova']} (metis atualizar)")
            elif info["instalada"]:
                print("é a mais nova.")
            return 0
        if not info["repositorio"]:
            print("não achei o repositório da MÊTIS para buscar a versão nova.", file=sys.stderr)
            return 1
        tag = args.versao or info["ultima"] or ""
        if not updates.version_key(tag) or tag not in updates.tags(info["repositorio"]):
            print(f"versão não encontrada no repositório: {tag or '(nenhuma tag v*)'}", file=sys.stderr)
            return 1
        command = updates.update_command(info["repositorio"], tag)
        os.execvp("sh", ["sh", "-c", command])

    if args.command in ("sessoes", "sessao"):
        try:
            if args.command == "sessoes":
                items = _core(home, "GET", "/sessions")
                if args.json:
                    print(json.dumps([{k: s.get(k) for k in ("id", "title", "kind", "status", "cwd", "agent", "tag")} for s in items], ensure_ascii=False))
                for s in [] if args.json else items:
                    print(f"{s['id']}  {s['kind']:6s} {s['status']:8s} {s['title']}  ({s['cwd']})")
                return 0
            if args.acao == "ler":
                glance = _core(home, "GET", f"/sessions/{args.id}/resumo")
                if args.json:
                    print(json.dumps(glance, ensure_ascii=False))
                    return 0
                for m in glance["ultimas"]:
                    print(f"{'você' if m['role'] == 'voce' else 'agente'}: {m['text']}")
                print("\n".join(glance["linhas"]))
                return 0
            text = " ".join(args.texto).strip()
            if not text:
                print("diga o texto: metis sessao escrever <id> \"texto\"", file=sys.stderr)
                return 1
            _core(home, "POST", f"/sessions/{args.id}/mensagem", {"texto": text})
            print("enviado.")
            return 0
        except CoreRefused as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (OSError, ValueError, KeyError) as exc:
            print(f"a MÊTIS não respondeu ({exc}). O app está aberto?", file=sys.stderr)
            return 1

    if args.command == "desligar":
        try:
            done = _core(home, "POST", "/desligar", {})
        except (CoreRefused, OSError, ValueError, KeyError) as exc:
            print(f"a MÊTIS não respondeu ({exc}): já está desligada?", file=sys.stderr)
            return 1
        print(f"desligando a MÊTIS ({done['fechando']} terminal(is) fechando).")
        return 0

    if args.command in ("automacoes", "rodar"):
        try:
            items = _core(home, "GET", "/automacoes")
            if args.command == "automacoes":
                if args.json:
                    print(json.dumps(items, ensure_ascii=False))
                    return 0
                for item in items:
                    last = item.get("ultima") or {}
                    state = "ativa" if item.get("ativa") else ("publicada" if item.get("publicada") else "rascunho")
                    print(f"⚙️ {item['nome']}  ({item['id']} · {state}{' · v' + str(item['publicada']) if item.get('publicada') else ''})"
                          + (f"  última: {last.get('status')}" if last else ""))
                if not items:
                    print("nenhuma automação ainda: crie na tela de Automações.")
                return 0
            wanted = " ".join(args.automacao).strip().lower()
            match = next((i for i in items if i["id"] == wanted or i["nome"].lower() == wanted), None)
            if match is None:
                print(f"automação não encontrada: {wanted}. Veja `metis automacoes`.", file=sys.stderr)
                return 1
            done = _core(home, "POST", f"/automacoes/{match['id']}/rodar", {})
            print(f"rodando {match['nome']} (execução #{done['execucao']}); acompanhe em Automações → Execuções.")
            return 0
        except CoreRefused as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (OSError, ValueError, KeyError) as exc:
            print(f"a MÊTIS não respondeu ({exc}). O app está aberto?", file=sys.stderr)
            return 1

    if args.command in ("worktree", "agente"):
        try:
            return _worktree_command(home, args) if args.command == "worktree" else _agent_command(home, args)
        except CoreRefused as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (OSError, ValueError, KeyError) as exc:
            print(f"a MÊTIS não respondeu ({exc}). O app está aberto?", file=sys.stderr)
            return 1

    if args.command == "lembrete":
        try:
            done = _core(home, "POST", "/lembretes", {"texto": args.texto, "quando": " ".join(args.quando), "conta": args.conta})
        except CoreRefused as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (OSError, ValueError, KeyError) as exc:
            print(f"a MÊTIS não respondeu ({exc}). O app está aberto?", file=sys.stderr)
            return 1
        print(done["message"])
        return 0

    if args.command == "brain" and args.acao in ("mcp", "contexto"):
        # Sem o núcleo: funcionam com a MÊTIS fechada (brain_mcp.py).
        from .brain_mcp import StdioServer, session_hook

        settings = load_settings()
        if args.acao == "mcp":
            StdioServer(settings).serve()
            return 0
        try:
            payload = json.loads(sys.stdin.read() or "{}") if not sys.stdin.isatty() else {}
        except ValueError:
            payload = {}
        try:
            text = session_hook(settings, payload if isinstance(payload, dict) else {})
        except Exception:  # hook nunca trava o início da sessão
            text = ""
        if text:
            print(text)
        return 0

    if args.command in ("brain", "tarefas", "tarefa"):
        try:
            return _brain_command(home, args) if args.command == "brain" else _tasks_command(home, args)
        except CoreRefused as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (OSError, ValueError, KeyError) as exc:
            print(f"a MÊTIS não respondeu ({exc}). O app está aberto?", file=sys.stderr)
            return 1

    if args.command == "web":
        url = web_url(args.endereco)
        try:
            _core_post(home, "/ui/web", {"url": url, "cwd": os.getcwd()})
        except (OSError, ValueError, KeyError) as exc:
            print(f"a MÊTIS não respondeu ({exc}). O app está aberto?", file=sys.stderr)
            return 1
        print(f"aberto na MÊTIS: {url or 'aba em branco'}")
        return 0

    store = AccountStore(home)

    if args.command == "contas":
        if args.json:
            print(json.dumps(store.list(), ensure_ascii=False))
            return 0
        _print_accounts(store)
        return 0

    if args.command == "switch":
        try:
            account = store.find(args.provider, args.conta)
        except UnknownAccount:
            print(f"conta não encontrada: {args.conta}. Veja `metis contas`.", file=sys.stderr)
            return 1
        store.activate(args.provider, account.id)
        _notify_core(home)
        print(f"{args.provider}: agora usando a conta {account.name}")
        return 0

    try:
        account = store.find(args.provider, args.nome)
    except UnknownAccount:
        account = store.add(args.provider, args.nome)
        _notify_core(home)
    executable = shutil.which(args.provider)
    if not executable:
        print(f"{args.provider} não encontrado no PATH", file=sys.stderr)
        return 1
    if not account.dir:
        print("a conta padrão usa o login de sempre da CLI; nada a fazer.")
        return 0
    env = {**os.environ, ENV_VAR[args.provider]: account.dir}
    argv_login = [executable] if args.provider == "claude" else [executable, "login"]
    print(f"Abrindo o login oficial do {args.provider} para a conta {account.name} ({account.dir})…", flush=True)
    os.execvpe(executable, argv_login, env)
    return 0  # não chega aqui


if __name__ == "__main__":
    raise SystemExit(main())
