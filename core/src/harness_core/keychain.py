"""Cofre dos tokens dos conectores: o Keychain do macOS, pelo `keyring`.

Só tokens de ferramentas de terceiros (Slack, ClickUp…). Login do Claude e do Codex
nunca passa por aqui: continua nas CLIs oficiais.
"""

from __future__ import annotations

from typing import Protocol

SERVICE = "dev.pedroaquino.metis"


class Vault(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class Keychain:
    """Keychain do macOS (serviço dev.pedroaquino.metis, uma entrada por conta de conector)."""

    def get(self, key: str) -> str | None:
        import keyring

        return keyring.get_password(SERVICE, key)

    def set(self, key: str, value: str) -> None:
        import keyring

        keyring.set_password(SERVICE, key, value)

    def delete(self, key: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(SERVICE, key)
        except PasswordDeleteError:
            pass


class MemoryVault:
    """Cofre em memória, para os testes não tocarem no Keychain de verdade."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.items.get(key)

    def set(self, key: str, value: str) -> None:
        self.items[key] = value

    def delete(self, key: str) -> None:
        self.items.pop(key, None)
