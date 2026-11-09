"""Busca no registro oficial de MCP (registry.modelcontextprotocol.io), v0.9.8.

Cada servidor vem com os endereços remotos (para "MCP por endereço") e os pacotes, com o
comando pronto para colar em "MCP por comando" (npx, uvx, docker) e as variáveis que pede.
Cache de 10 minutos por busca.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

import httpx

REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
TTL = 10 * 60
LIMIT = 30


class RegistryError(RuntimeError):
    pass


def _command(package: dict) -> str:
    kind = str(package.get("registryType") or "").lower()
    name = str(package.get("identifier") or "")
    version = str(package.get("version") or "")
    if not name:
        return ""
    if kind == "npm":
        return f"npx -y {name}@{version}" if version else f"npx -y {name}"
    if kind == "pypi":
        return f"uvx {name}=={version}" if version else f"uvx {name}"
    if kind == "oci":
        image = name
        if version and ":" not in name.rsplit("/", 1)[-1] and "@" not in name:
            image = f"{name}:{version}"
        return f"docker run -i --rm {image}"
    if kind == "nuget":
        return f"dnx {name}@{version} --yes" if version else f"dnx {name} --yes"
    return ""


def _server(item: dict) -> dict | None:
    server = item.get("server") if isinstance(item.get("server"), dict) else item
    if not isinstance(server, dict) or not server.get("name"):
        return None
    packages = []
    for package in server.get("packages") or []:
        if not isinstance(package, dict):
            continue
        packages.append(
            {
                "registro": package.get("registryType") or "",
                "nome": package.get("identifier") or "",
                "versao": package.get("version") or "",
                "comando": _command(package),
                "env": [
                    {
                        "nome": env.get("name") or "",
                        "descricao": env.get("description") or "",
                        "obrigatoria": bool(env.get("isRequired")),
                        "secreta": bool(env.get("isSecret")),
                    }
                    for env in package.get("environmentVariables") or []
                    if isinstance(env, dict) and env.get("name")
                ],
            }
        )
    remotes = [
        {"tipo": remote.get("type") or "", "url": remote.get("url") or ""}
        for remote in server.get("remotes") or []
        if isinstance(remote, dict) and remote.get("url")
    ]
    repository = server.get("repository") if isinstance(server.get("repository"), dict) else {}
    return {
        "nome": server["name"],
        "titulo": server.get("title") or server["name"].split("/")[-1],
        "descricao": server.get("description") or "",
        "versao": server.get("version") or "",
        "site": server.get("websiteUrl") or repository.get("url") or "",
        "remotos": remotes,
        "pacotes": packages,
    }


class McpRegistry:
    def __init__(self, http: Callable[[], httpx.Client]) -> None:
        self.http = http
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()

    def search(self, query: str = "") -> list[dict]:
        key = " ".join(query.lower().split())
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.time() - cached[0] < TTL:
                return cached[1]
        params = {"version": "latest", "limit": LIMIT}
        if key:
            params["search"] = key
        try:
            response = self.http().get(REGISTRY, params=params, headers={"Accept": "application/json"})
            data = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as exc:
            raise RegistryError("o catálogo oficial de MCP não respondeu") from exc
        if not isinstance(data, dict) or not isinstance(data.get("servers"), list):
            raise RegistryError("o catálogo oficial de MCP não respondeu")
        found: list[dict] = []
        seen: set[str] = set()
        for item in data["servers"]:
            server = _server(item) if isinstance(item, dict) else None
            if server is None or server["nome"] in seen:
                continue
            seen.add(server["nome"])
            found.append(server)
            if len(found) >= LIMIT:
                break
        with self._lock:
            self._cache[key] = (time.time(), found)
        return found
