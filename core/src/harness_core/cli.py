"""Comando `metis` (antes `harness`, que segue como apelido): contas e troca de conta pelo terminal.

    metis contas                       lista as contas e qual está ativa
    metis switch <claude|codex> <conta> passa a usar outra conta nas sessões novas
    metis login <claude|codex> <nome>   cria a conta e abre o login oficial aqui
    metis web [endereço]               abre uma aba do navegador da MÊTIS (ex.: localhost:5173)
    metis brain buscar <termos>        busca no Brain (--tipo decisao, --projeto "Nome")
    metis brain ler "<título>"         mostra uma nota do Brain
    metis brain precedentes [termos]   registros de outros projetos parecidos com este
    metis tarefas                      as Próximas ações do projeto desta pasta, com o id
    metis tarefa nova "<texto>"        acrescenta uma tarefa
    metis tarefa mover <id> <estado>   pendente, em-andamento, em-teste ou concluida

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
    request = urllib.request.Request(
        f"{info['url']}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"X-Harness-Token": info["token"], "Content-Type": "application/json"},
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
        task = _core(home, "POST", base, {"text": " ".join(args.resto), "state": state})
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


def _print_accounts(store: AccountStore) -> None:
    for provider, entry in store.list().items():
        print(provider)
        for account in entry["accounts"]:
            mark = "●" if account["active"] else " "
            where = account["dir"] or "pasta padrão da CLI"
            print(f"  {mark} {account['name']:<16} {account['id']:<16} {where}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="metis", description="Contas, navegador, Brain e tarefas da MÊTIS.")
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
    brain.add_argument("acao", choices=("buscar", "ler", "precedentes"))
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
    args = parser.parse_args(argv)

    home = load_settings().home

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
