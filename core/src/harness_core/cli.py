"""Comando `metis` (antes `harness`, que segue como apelido): contas e troca de conta pelo terminal.

    metis contas                       lista as contas e qual está ativa
    metis switch <claude|codex> <conta> passa a usar outra conta nas sessões novas
    metis login <claude|codex> <nome>   cria a conta e abre o login oficial aqui

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


def _print_accounts(store: AccountStore) -> None:
    for provider, entry in store.list().items():
        print(provider)
        for account in entry["accounts"]:
            mark = "●" if account["active"] else " "
            where = account["dir"] or "pasta padrão da CLI"
            print(f"  {mark} {account['name']:<16} {account['id']:<16} {where}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="metis", description="Contas da MÊTIS.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("contas", help="lista as contas e qual está ativa")
    switch = sub.add_parser("switch", help="troca a conta ativa de uma CLI")
    switch.add_argument("provider", choices=PROVIDERS)
    switch.add_argument("conta")
    login = sub.add_parser("login", help="cria uma conta e abre o login oficial neste terminal")
    login.add_argument("provider", choices=PROVIDERS)
    login.add_argument("nome")
    args = parser.parse_args(argv)

    home = load_settings().home
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
