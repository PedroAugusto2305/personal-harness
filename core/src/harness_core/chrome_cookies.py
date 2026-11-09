"""Cookies de um navegador Chromium do Mac (Chrome, Brave, Edge, Arc, Chromium), para um perfil da MÊTIS.

O WebKit tem outro cofre de cookies; importar evita fazer login de novo em cada site.
O banco (`Network/Cookies` ou `Cookies` na pasta do perfil) guarda o valor cifrado:
`v10`/`v11` + AES-128-CBC com a chave PBKDF2-HMAC-SHA1(senha do Keychain, "saltysalt",
1003 voltas, 16 bytes) e iv de 16 espaços. A senha sai do Keychain pelo `security`, e o
macOS pede licença ao Pedro na primeira vez. Desde a versão 24 do banco, o texto decifrado
começa com 32 bytes (o SHA-256 do domínio), que saem.

O AES vem do CommonCrypto do próprio macOS (por ctypes) e o PBKDF2 do hashlib: o pacote
`cryptography` não tem roda para Mac Intel e seria compilado a cada instalação.

Nada aqui registra valor de cookie: nem em log, nem em mensagem de erro.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

SUPPORT = Path.home() / "Library" / "Application Support"
#: id → (nome, pasta em Application Support, serviço do Keychain, conta do Keychain)
BROWSERS: dict[str, tuple[str, str, str, str]] = {
    "chrome": ("Chrome", "Google/Chrome", "Chrome Safe Storage", "Chrome"),
    "brave": ("Brave", "BraveSoftware/Brave-Browser", "Brave Safe Storage", "Brave"),
    "edge": ("Edge", "Microsoft Edge", "Microsoft Edge Safe Storage", "Microsoft Edge"),
    "arc": ("Arc", "Arc/User Data", "Arc Safe Storage", "Arc"),
    "chromium": ("Chromium", "Chromium", "Chromium Safe Storage", "Chromium"),
}
SAME_SITE = {-1: None, 0: "none", 1: "lax", 2: "strict"}
EPOCH_1601 = 11644473600  # segundos entre 1601-01-01 e 1970-01-01
KEYCHAIN_TIMEOUT = 90

PasswordReader = Callable[[str, str], str]


class ChromeCookieError(RuntimeError):
    pass


def keychain_password(service: str, account: str) -> str:
    """A senha do cofre do navegador; o macOS mostra o pedido de licença ao Pedro."""
    try:
        done = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service, "-a", account],
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ChromeCookieError("sem resposta do Keychain") from exc
    password = done.stdout.strip()
    if done.returncode != 0 or not password:
        raise ChromeCookieError("o Keychain recusou")
    return password


def _cookies_file(profile_dir: Path) -> Path | None:
    for candidate in (profile_dir / "Network" / "Cookies", profile_dir / "Cookies"):
        if candidate.is_file():
            return candidate
    return None


def _profile_names(folder: Path) -> dict[str, str]:
    try:
        state = json.loads((folder / "Local State").read_text(encoding="utf-8"))
        cache = state.get("profile", {}).get("info_cache", {})
        return {key: str(value.get("name") or key) for key, value in cache.items() if isinstance(value, dict)}
    except (OSError, ValueError, AttributeError):
        return {}


def _order(name: str) -> tuple[int, int, str]:
    if name == "Default":
        return (0, 0, name)
    if name.startswith("Profile ") and name[8:].isdigit():
        return (1, int(name[8:]), name)
    return (2, 0, name)


def list_sources(support: Path | None = None) -> list[dict]:
    """Os perfis de navegador com banco de cookies nesta máquina."""
    base = support or SUPPORT
    found: list[dict] = []
    for key, (label, rel, _service, _account) in BROWSERS.items():
        folder = base / rel
        if not folder.is_dir():
            continue
        names = _profile_names(folder)
        try:
            children = sorted((c for c in folder.iterdir() if c.is_dir()), key=lambda c: _order(c.name))
        except OSError:
            continue
        for child in children:
            cookies = _cookies_file(child)
            if cookies is None:
                continue
            found.append({"id": f"{key}:{child.name}", "navegador": label, "perfil": names.get(child.name, child.name), "caminho": str(cookies)})
    return found


IV = b" " * 16
_ENCRYPT, _DECRYPT = 0, 1  # kCCEncrypt, kCCDecrypt
_AES, _PKCS7 = 0, 1  # kCCAlgorithmAES, kCCOptionPKCS7Padding
_crypto: ctypes.CDLL | None = None


def _commoncrypto() -> ctypes.CDLL:
    global _crypto
    if _crypto is None:
        path = ctypes.util.find_library("System") or "/usr/lib/libSystem.B.dylib"
        lib = ctypes.CDLL(path)
        lib.CCCrypt.restype = ctypes.c_int32
        lib.CCCrypt.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]  # fmt: skip
        _crypto = lib
    return _crypto


def aes_cbc(operation: int, key: bytes, data: bytes, iv: bytes = IV) -> bytes:
    """AES-CBC com PKCS7 pelo CommonCrypto. ValueError se o texto não fecha (chave errada, lixo)."""
    if len(key) not in (16, 24, 32):
        raise ValueError("chave AES inválida")
    out = ctypes.create_string_buffer(len(data) + 16)
    moved = ctypes.c_size_t(0)
    status = _commoncrypto().CCCrypt(operation, _AES, _PKCS7, key, len(key), iv, data, len(data), out, len(out), ctypes.byref(moved))
    if status != 0:
        raise ValueError(f"o AES recusou (CommonCrypto {status})")
    return out.raw[: moved.value]


def derive_key(password: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), b"saltysalt", 1003, 16)


def decrypt_value(encrypted: bytes, key: bytes, db_version: int, host: str = "") -> str:
    """O valor do cookie; ValueError se não decifra (o chamador conta como ignorado).

    Na versão 24 em diante o texto começa com o SHA-256 do domínio: conferir esse prefixo
    separa uma chave errada (ou um valor estragado) de um valor de verdade.
    """
    if encrypted[:3] not in (b"v10", b"v11"):
        raise ValueError("formato de cifra desconhecido")
    if not encrypted[3:] or len(encrypted[3:]) % 16:
        raise ValueError("tamanho de cifra inválido")
    plain = aes_cbc(_DECRYPT, key, encrypted[3:])
    if db_version >= 24:
        if plain[:32] != hashlib.sha256(host.encode("utf-8")).digest():
            raise ValueError("o prefixo do domínio não confere")
        plain = plain[32:]
    return plain.decode("utf-8")


def _matches(host: str, domains: list[str]) -> bool:
    bare = host.lstrip(".").lower()
    for domain in domains:
        wanted = domain.strip().lstrip(".").lower()
        if wanted and (bare == wanted or bare.endswith("." + wanted)):
            return True
    return False


def _source(fonte: str, base: Path) -> tuple[str, Path, str, str]:
    key, _, profile = (fonte or "").partition(":")
    if key not in BROWSERS or not profile or "/" in profile or profile in (".", ".."):
        raise ChromeCookieError("fonte de cookies inválida")
    label, rel, service, account = BROWSERS[key]
    cookies = _cookies_file(base / rel / profile)
    if cookies is None:
        raise ChromeCookieError(f"o perfil {profile} do {label} não tem cookies")
    return label, cookies, service, account


def read_cookies(
    fonte: str,
    dominios: list[str] | None = None,
    support: Path | None = None,
    password_reader: PasswordReader | None = None,
    now: float | None = None,
) -> dict:
    """{"cookies": [...], "ignorados": n}; ignorados = os que não decifraram."""
    base = support or SUPPORT
    label, cookies_path, service, account = _source(fonte, base)
    reader = password_reader or keychain_password
    try:
        password = reader(service, account)
    except ChromeCookieError as exc:
        raise ChromeCookieError(f"o macOS não liberou a chave do {label}") from exc
    key = derive_key(password)
    moment = time.time() if now is None else now
    wanted = [d for d in (dominios or []) if d and d.strip()]
    with tempfile.TemporaryDirectory(prefix="metis-cookies-") as tmp:
        # O navegador aberto trava o banco: lê uma cópia (com o diário, se houver).
        copy = Path(tmp) / "Cookies"
        try:
            shutil.copy2(cookies_path, copy)
            for suffix in ("-wal", "-shm", "-journal"):
                extra = cookies_path.with_name(cookies_path.name + suffix)
                if extra.is_file():
                    shutil.copy2(extra, copy.with_name(copy.name + suffix))
        except OSError as exc:
            raise ChromeCookieError(f"não consegui ler o banco de cookies do {label}") from exc
        try:
            db = sqlite3.connect(copy)
            try:
                row = db.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
                version = int(row[0]) if row else 0
                rows = db.execute(
                    "SELECT host_key, name, value, encrypted_value, path, expires_utc, is_secure, is_httponly, samesite FROM cookies"
                ).fetchall()
            finally:
                db.close()
        except (sqlite3.Error, ValueError) as exc:
            raise ChromeCookieError(f"o banco de cookies do {label} não abriu") from exc
    out: list[dict] = []
    ignored = 0
    for host, name, plain, encrypted, path, expires_utc, secure, http_only, same_site in rows:
        if wanted and not _matches(host or "", wanted):
            continue
        expires = None
        if expires_utc:
            expires = expires_utc / 1_000_000 - EPOCH_1601
            if expires <= moment:
                continue
        if encrypted:
            try:
                value = decrypt_value(bytes(encrypted), key, version, host or "")
            except (ValueError, UnicodeDecodeError):
                ignored += 1
                continue
        else:
            value = plain or ""
        out.append(
            {
                "nome": name,
                "valor": value,
                "dominio": host,
                "caminho": path or "/",
                "expira": expires,
                "seguro": bool(secure),
                "http_only": bool(http_only),
                "same_site": SAME_SITE.get(same_site if isinstance(same_site, int) else -1),
            }
        )
    return {"cookies": out, "ignorados": ignored}
