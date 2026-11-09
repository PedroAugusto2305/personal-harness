"""Perfis da MÊTIS (v0.9.8): cada perfil é uma pasta de dados própria, com o próprio núcleo.

Decisão do Pedro: perfis completos. Projetos, agentes, automações, rotinas, conectores,
ajustes e terminais de um perfil não se misturam com os de outro (ex.: "Pessoal" e
"Seller Pro"). Trocar de perfil fecha os terminais do atual e reabre a MÊTIS no outro.

O registro mora sempre na pasta principal (`~/.harness/perfis.json`):

    {"ativo": "principal",
     "perfis": [{"id": "principal", "nome": "Principal", "pasta": "~/.harness",
                 "porta": 47830, "vault": null, "criado": "2026-11-09T10:00"}, ...]}

- O "principal" é a `~/.harness` de sempre e não se apaga.
- Perfil novo: pasta `~/.harness-perfis/<slug>` e porta = padrão + 10 × n, sem repetir.
- `vault`: o Brain daquele perfil (null = o padrão).
- O núcleo sabe o perfil pela variável HARNESS_PROFILE que o app passa ao subir; sem ela,
  é o principal. Os segredos de cada perfil ficam num serviço próprio do Keychain.

Nos testes, HARNESS_PROFILES aponta outro arquivo de registro, HARNESS_MAIN_HOME outra
pasta principal e HARNESS_PROFILES_DIR outra pasta para os perfis novos.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

MAIN_ID = "principal"
MAIN_NAME = "Principal"
PORT_STEP = 10
NAME_MAX = 40
TRASH = Path.home() / ".Trash"


class ProfileError(ValueError):
    """Pedido inválido (400); `code` 404 quando o perfil não existe, 409 quando trava."""

    def __init__(self, message: str, code: int = 400) -> None:
        super().__init__(message)
        self.code = code


def main_home() -> Path:
    """A pasta principal (o perfil "principal"), onde o registro mora."""
    return Path(os.environ.get("HARNESS_MAIN_HOME") or Path.home() / ".harness").expanduser()


def registry_path() -> Path:
    return Path(os.environ.get("HARNESS_PROFILES") or main_home() / "perfis.json").expanduser()


def profiles_root() -> Path:
    return Path(os.environ.get("HARNESS_PROFILES_DIR") or Path.home() / ".harness-perfis").expanduser()


def short_home(path: Path | str) -> str:
    """Caminho com ~ no lugar da pasta do usuário (como o Pedro escreve)."""
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home) :] if text == home or text.startswith(home + "/") else text


def slug(text: str) -> str:
    folded = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:40] or "perfil"


@dataclass
class Profile:
    id: str
    nome: str
    pasta: str
    porta: int
    vault: str | None = None
    criado: str = ""

    @property
    def folder(self) -> Path:
        return Path(self.pasta).expanduser()

    @property
    def brain(self) -> Path | None:
        return Path(self.vault).expanduser() if self.vault else None

    def to_dict(self) -> dict:
        return asdict(self)


def keychain_service(profile_id: str, base: str) -> str:
    """O principal usa o serviço de sempre; os outros, um serviço com o id no fim."""
    return base if profile_id in ("", MAIN_ID) else f"{base}.{profile_id}"


class ProfileRegistry:
    def __init__(self, default_port: int, path: Path | None = None, main: Path | None = None, root: Path | None = None, trash: Path | None = None) -> None:
        self.default_port = default_port
        self.path = path or registry_path()
        self.main = main or main_home()
        self.root = root or profiles_root()
        self.trash = trash or TRASH
        self._lock = threading.Lock()

    # --- arquivo -------------------------------------------------------------------------

    def _main_profile(self, stored: dict | None = None) -> Profile:
        stored = stored or {}
        return Profile(
            id=MAIN_ID,
            nome=str(stored.get("nome") or MAIN_NAME),
            pasta=short_home(self.main),
            porta=self.default_port,
            vault=stored.get("vault") or None,
            criado=str(stored.get("criado") or ""),
        )

    def _read(self) -> dict:
        """O registro como está no disco; o principal sempre existe e vem primeiro.
        Ler nunca grava: um núcleo que só consulta não cria o arquivo."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        raw = data.get("perfis") if isinstance(data, dict) else None
        items = [p for p in raw or [] if isinstance(p, dict)]
        main = self._main_profile(next((p for p in items if p.get("id") == MAIN_ID), None))
        others: list[Profile] = []
        for item in items:
            if item.get("id") == MAIN_ID or not item.get("id") or not item.get("pasta"):
                continue
            try:
                others.append(
                    Profile(
                        id=str(item["id"]),
                        nome=str(item.get("nome") or item["id"]),
                        pasta=str(item["pasta"]),
                        porta=int(item.get("porta") or 0),
                        vault=item.get("vault") or None,
                        criado=str(item.get("criado") or ""),
                    )
                )
            except (TypeError, ValueError):
                continue
        ids = {MAIN_ID, *(p.id for p in others)}
        active = str(data.get("ativo") or MAIN_ID) if isinstance(data, dict) else MAIN_ID
        return {"ativo": active if active in ids else MAIN_ID, "perfis": [main, *others]}

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ativo": state["ativo"], "perfis": [p.to_dict() for p in state["perfis"]]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # --- leitura ---------------------------------------------------------------------------

    def state(self) -> dict:
        state = self._read()
        return {"ativo": state["ativo"], "perfis": [p.to_dict() for p in state["perfis"]]}

    def list(self) -> list[Profile]:
        return self._read()["perfis"]

    def active(self) -> str:
        return self._read()["ativo"]

    def get(self, profile_id: str) -> Profile:
        found = next((p for p in self.list() if p.id == profile_id), None)
        if found is None:
            raise ProfileError(f"perfil desconhecido: {profile_id}", 404)
        return found

    def find(self, profile_id: str) -> Profile | None:
        return next((p for p in self.list() if p.id == profile_id), None)

    # --- escrita ---------------------------------------------------------------------------

    @staticmethod
    def _name(nome: str) -> str:
        clean = " ".join(str(nome or "").split())
        if not clean or len(clean) > NAME_MAX:
            raise ProfileError(f"o nome do perfil precisa ter de 1 a {NAME_MAX} caracteres")
        return clean

    @staticmethod
    def _vault(vault: str | None) -> str | None:
        if vault is None or not str(vault).strip():
            return None
        path = Path(str(vault).strip()).expanduser()
        if not path.is_dir():
            raise ProfileError(f"a pasta do Brain não existe: {short_home(path)}")
        return short_home(path.resolve())

    def _next_port(self, used: set[int]) -> int:
        n = 1
        while self.default_port + PORT_STEP * n in used:
            n += 1
        return self.default_port + PORT_STEP * n

    def create(self, nome: str, vault: str | None = None) -> Profile:
        name = self._name(nome)
        with self._lock:
            state = self._read()
            if any(p.nome.lower() == name.lower() for p in state["perfis"]):
                raise ProfileError(f"já existe um perfil chamado {name}", 409)
            taken = {p.id for p in state["perfis"]}
            base = slug(name)
            if base == MAIN_ID:
                base = f"{base}-2"
            profile_id, n = base, 2
            while profile_id in taken or (self.root / profile_id).exists():
                profile_id, n = f"{base}-{n}", n + 1
            folder = self.root / profile_id
            folder.mkdir(parents=True, exist_ok=False)
            profile = Profile(
                id=profile_id,
                nome=name,
                pasta=short_home(folder),
                porta=self._next_port({p.porta for p in state["perfis"]}),
                vault=self._vault(vault),
                criado=datetime.now().isoformat(timespec="minutes"),
            )
            state["perfis"].append(profile)
            self._write(state)
            return profile

    def update(self, profile_id: str, nome: str | None = None, vault: str | None = None, clear_vault: bool = False) -> Profile:
        with self._lock:
            state = self._read()
            target = next((p for p in state["perfis"] if p.id == profile_id), None)
            if target is None:
                raise ProfileError(f"perfil desconhecido: {profile_id}", 404)
            if nome is not None:
                name = self._name(nome)
                if any(p.id != profile_id and p.nome.lower() == name.lower() for p in state["perfis"]):
                    raise ProfileError(f"já existe um perfil chamado {name}", 409)
                target.nome = name
            if clear_vault:
                target.vault = None
            elif vault is not None:
                target.vault = self._vault(vault)
            self._write(state)
            return target

    def delete(self, profile_id: str) -> str:
        """Manda a pasta do perfil para a Lixeira (nunca apaga de vez) e o tira do registro."""
        with self._lock:
            state = self._read()
            if profile_id == MAIN_ID:
                raise ProfileError("o perfil principal não se apaga")
            if profile_id == state["ativo"]:
                raise ProfileError("este perfil está em uso: troque para outro antes de apagar")
            target = next((p for p in state["perfis"] if p.id == profile_id), None)
            if target is None:
                raise ProfileError(f"perfil desconhecido: {profile_id}", 404)
            moved = ""
            folder = target.folder
            if folder.exists():
                self.trash.mkdir(parents=True, exist_ok=True)
                dest = self.trash / f"MÊTIS perfil {target.nome}"
                n = 2
                while dest.exists():
                    dest = self.trash / f"MÊTIS perfil {target.nome} {n}"
                    n += 1
                shutil.move(str(folder), str(dest))
                moved = str(dest)
            state["perfis"] = [p for p in state["perfis"] if p.id != profile_id]
            self._write(state)
            return moved

    def activate(self, profile_id: str) -> Profile:
        with self._lock:
            state = self._read()
            target = next((p for p in state["perfis"] if p.id == profile_id), None)
            if target is None:
                raise ProfileError(f"perfil desconhecido: {profile_id}", 404)
            target.folder.mkdir(parents=True, exist_ok=True)
            state["ativo"] = profile_id
            self._write(state)
            return target


def resolve(profile_id: str | None, default_port: int) -> tuple[str, Profile | None]:
    """O perfil pedido pelo ambiente (HARNESS_PROFILE), lido do registro. Perfil que não
    existe mais cai no principal (com aviso no terminal), para a MÊTIS nunca deixar de abrir."""
    wanted = (profile_id or "").strip() or MAIN_ID
    registry = ProfileRegistry(default_port)
    found = registry.find(wanted)
    if found is None:
        if wanted != MAIN_ID:
            print(f"perfil {wanted!r} não existe no registro; abrindo o principal", flush=True)
        return MAIN_ID, registry.find(MAIN_ID)
    return wanted, found


def public(profile: Profile) -> dict[str, Any]:
    return profile.to_dict()
