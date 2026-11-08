"""Comando `metis` (antes `harness`, que segue como apelido): contas e troca de conta pelo terminal.

    metis contas                       lista as contas e qual está ativa
    metis switch <claude|codex> <conta> passa a usar outra conta nas sessões novas
    metis login <claude|codex> <nome>   cria a conta e abre o login oficial aqui
    metis web [endereço]               abre uma aba do navegador da MÊTIS (ex.: localhost:5173)

O login acontece sempre no fluxo oficial da CLI, numa pasta só daquela conta.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
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
    parser = argparse.ArgumentParser(prog="metis", description="Contas e navegador da MÊTIS.")
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
    args = parser.parse_args(argv)

    home = load_settings().home

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
