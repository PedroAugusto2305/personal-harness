"""Contas por CLI: cada conta é uma pasta de configuração com o próprio login.

- Claude Code: `CLAUDE_CONFIG_DIR` (a doc oficial separa até a entrada do Keychain por pasta).
- Codex: `CODEX_HOME`.

A conta "padrão" não tem pasta: usa o `~/.claude` e o `~/.codex` de sempre. O Harness
nunca lê nem copia token; o login acontece no fluxo oficial, dentro do terminal.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

PROVIDERS = ("claude", "codex")
DEFAULT_ID = "padrao"
ENV_VAR = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME"}


class UnknownAccount(KeyError):
    pass


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    dir: str | None

    def to_dict(self, active: bool) -> dict:
        return {"id": self.id, "name": self.name, "dir": self.dir, "active": active}


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or "conta"


class AccountStore:
    def __init__(self, home: Path, codex_config_source: Path | None = None) -> None:
        self.path = home / "accounts.json"
        self.accounts_dir = home / "contas"
        self.codex_config_source = codex_config_source or Path.home() / ".codex" / "config.toml"

    # --- leitura e escrita -------------------------------------------------

    def _load(self) -> dict:
        data: dict = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        for provider in PROVIDERS:
            entry = data.setdefault(provider, {})
            accounts = entry.setdefault("accounts", [])
            if not any(a.get("id") == DEFAULT_ID for a in accounts):
                accounts.insert(0, {"id": DEFAULT_ID, "name": "padrão", "dir": None})
            if not any(a.get("id") == entry.get("active") for a in accounts):
                entry["active"] = DEFAULT_ID
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(self.path)

    @staticmethod
    def _check(provider: str) -> None:
        if provider not in PROVIDERS:
            raise UnknownAccount(provider)

    # --- consultas ---------------------------------------------------------

    def list(self) -> dict:
        data = self._load()
        return {
            provider: {
                "active": data[provider]["active"],
                "accounts": [Account(**a).to_dict(a["id"] == data[provider]["active"]) for a in data[provider]["accounts"]],
            }
            for provider in PROVIDERS
        }

    def get(self, provider: str, account_id: str) -> Account:
        self._check(provider)
        for raw in self._load()[provider]["accounts"]:
            if raw["id"] == account_id:
                return Account(**raw)
        raise UnknownAccount(f"{provider}/{account_id}")

    def find(self, provider: str, key: str) -> Account:
        """Por id ou por nome, sem diferenciar maiúsculas."""
        self._check(provider)
        wanted = key.strip().lower()
        for raw in self._load()[provider]["accounts"]:
            if raw["id"] == wanted or raw["name"].lower() == wanted or raw["id"] == slugify(key):
                return Account(**raw)
        raise UnknownAccount(f"{provider}/{key}")

    def active(self, provider: str) -> Account:
        self._check(provider)
        data = self._load()
        return self.get(provider, data[provider]["active"])

    # --- mudanças ----------------------------------------------------------

    def add(self, provider: str, name: str) -> Account:
        self._check(provider)
        data = self._load()
        taken = {a["id"] for a in data[provider]["accounts"]}
        base = slugify(name)
        account_id, n = base, 2
        while account_id in taken:
            account_id, n = f"{base}-{n}", n + 1
        folder = self.accounts_dir / f"{provider}-{account_id}"
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
        if provider == "codex" and self.codex_config_source.exists():
            # Mesma configuração do Codex de sempre (modelo, MCPs); o login fica separado.
            shutil.copy2(self.codex_config_source, folder / "config.toml")
        account = Account(id=account_id, name=name.strip() or account_id, dir=str(folder))
        data[provider]["accounts"].append({"id": account.id, "name": account.name, "dir": account.dir})
        self._save(data)
        return account

    def activate(self, provider: str, account_id: str) -> Account:
        account = self.get(provider, account_id)
        data = self._load()
        data[provider]["active"] = account.id
        self._save(data)
        return account

    @staticmethod
    def env(provider: str, account: Account) -> dict[str, str]:
        return {ENV_VAR[provider]: account.dir} if account.dir else {}


def resolve_executable(name: str) -> str | None:
    return shutil.which(name, path=os.environ.get("PATH"))
