"""Login OAuth de MCP remoto (o oficial do ClickUp), feito pela própria MÊTIS.

Segue a autorização do MCP: descobre o servidor de autorização pelo .well-known do recurso,
registra a MÊTIS como cliente público (registro dinâmico), abre a página de login no
navegador com PKCE e recebe o código em http://127.0.0.1:<porta>/conectores/oauth/retorno.
Usa 127.0.0.1 e não localhost: no Chrome do Pedro, localhost dá 431 por excesso de cookies.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

import httpx


class OAuthError(RuntimeError):
    pass


@dataclass
class OAuthStart:
    state: str
    verifier: str
    client_id: str
    redirect_uri: str
    token_endpoint: str
    resource: str
    authorize_url: str


def _get_json(http: httpx.Client, url: str) -> dict | None:
    try:
        response = http.get(url)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def discover(http: httpx.Client, mcp_url: str) -> tuple[str, dict]:
    """(recurso, metadados do servidor de autorização) de um MCP remoto."""
    parsed = urlparse(mcp_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    resource_meta = _get_json(http, f"{origin}/.well-known/oauth-protected-resource{parsed.path}") or _get_json(
        http, f"{origin}/.well-known/oauth-protected-resource"
    )
    resource = (resource_meta or {}).get("resource") or mcp_url
    issuers = (resource_meta or {}).get("authorization_servers") or [origin]
    issuer = issuers[0].rstrip("/")
    issuer_path = urlparse(issuer).path
    issuer_origin = issuer[: len(issuer) - len(issuer_path)] if issuer_path else issuer
    meta = (
        _get_json(http, f"{issuer_origin}/.well-known/oauth-authorization-server{issuer_path}")
        or _get_json(http, f"{issuer_origin}/.well-known/openid-configuration{issuer_path}")
    )
    if not meta or not meta.get("authorization_endpoint") or not meta.get("token_endpoint"):
        raise OAuthError("o serviço não publica como fazer login (sem metadados OAuth)")
    return resource, meta


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def begin(http: httpx.Client, mcp_url: str, redirect_uri: str, client_name: str = "MÊTIS") -> OAuthStart:
    resource, meta = discover(http, mcp_url)
    registration = meta.get("registration_endpoint")
    if not registration:
        raise OAuthError("o serviço não aceita registro automático de cliente")
    response = http.post(
        registration,
        json={
            "client_name": client_name,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    if response.status_code >= 400:
        raise OAuthError(f"registro do cliente recusado ({response.status_code}): {response.text[:200]}")
    client_id = response.json().get("client_id")
    if not client_id:
        raise OAuthError("o registro não devolveu client_id")
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
        "resource": resource,
    }
    scopes = meta.get("scopes_supported")
    if scopes:
        params["scope"] = " ".join(scopes)
    url = f"{meta['authorization_endpoint']}?{urlencode(params)}"
    return OAuthStart(state, verifier, client_id, redirect_uri, meta["token_endpoint"], resource, url)


def finish(http: httpx.Client, start: OAuthStart, code: str) -> dict:
    """Troca o código pelo token. Devolve o JSON do servidor (access_token, talvez refresh_token)."""
    response = http.post(
        start.token_endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": start.redirect_uri,
            "client_id": start.client_id,
            "code_verifier": start.verifier,
            "resource": start.resource,
        },
        headers={"Accept": "application/json"},
    )
    if response.status_code >= 400:
        raise OAuthError(f"troca do código recusada ({response.status_code}): {response.text[:200]}")
    tokens = response.json()
    if not tokens.get("access_token"):
        raise OAuthError("o serviço não devolveu access_token")
    return tokens
