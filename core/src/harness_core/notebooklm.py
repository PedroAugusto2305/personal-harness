"""NotebookLM na aba de Estudo (v1.3.0), pelo CLI do notebooklm-py.

O NotebookLM não tem API pública para conta pessoal do Google. O Pedro já usa o
`notebooklm-py` (o CLI `notebooklm`, instalado com `uv tool install "notebooklm-py[browser]"`),
que fala com o NotebookLM pela sessão do Google guardada em
`~/.notebooklm/profiles/<perfil>/storage_state.json`. O núcleo chama esse CLI com `--json`
(não importa o pacote: ele mora no ambiente do uv tool, com o Playwright) e entrega à tela e
à central de MCP:

- o status: instalado, versão e se o login ainda vale (`auth check --test`, que vai à rede);
- os cadernos, as fontes e o resumo de um caderno;
- perguntar ao caderno: a resposta do NotebookLM com as citações [n] ligadas ao título da fonte;
- o texto completo de uma fonte, em Markdown, em pedaços;
- entrar: `notebooklm login` abre o navegador no login do Google e salva sozinho quando o login
  termina (não precisa de terminal). Com o Chrome no Mac, vai `--browser chrome` (num perfil
  próprio do notebooklm-py, não o do Pedro): o Chromium do Playwright pode travar no macOS 15 ou
  mais novo, e a versão dele muda a cada atualização do pacote. Vai sempre com `--fresh` (v1.3.1):
  o perfil próprio guarda o cookie SID de uma sessão que o Google já derrubou, o notebooklm-py
  toma esse SID por login feito, salva os cookies sem o `__Secure-1PSIDTS` e fecha a janela num
  segundo, sem o Pedro conseguir entrar. Limpo, o perfil abre na tela de login do Google e espera.

Desde a 0.8 o NotebookLM mora em notebook.google.com; o notebooklm-py anterior a ela não
reconhece o endereço novo e dá o login como vencido. Por isso a versão mínima é 0.8.0.

Perguntar continua a última conversa do caderno no NotebookLM: a pergunta aparece no chat do
caderno no site. O `--new` apagaria a conversa do servidor e nunca é usado aqui.

Nada aqui registra cookie nem token: o CLI cuida da sessão do Google.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

HOST = "https://notebook.google.com"
MIN_VERSION = (0, 8, 0)
TIMEOUT = 90
#: Abaixo dos 60 s em que o Claude Code corta uma chamada de MCP por HTTP.
ASK_TIMEOUT = 55
LOGIN_TIMEOUT = 15 * 60
#: Quanto o notebooklm-py espera o login do Google (senha e 2FA): um minuto antes do corte do
#: núcleo, para ele mesmo dizer que o tempo acabou (o padrão dele é 5 minutos).
BROWSER_WAIT = LOGIN_TIMEOUT - 60
STATUS_TTL = 120
LIST_TTL = 60
SOURCES_TTL = 180
#: Corte do texto de uma fonte por pedido (a fonte inteira pode ter centenas de páginas).
FULLTEXT_LIMIT = 20_000
ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
VERSION = re.compile(r"version\s+(\d+)\.(\d+)\.(\d+)")
#: Variáveis da MÊTIS que não vão para o CLI (o token da central dá terminais).
BLOCKED = ("HARNESS_", "METIS_")

Runner = Callable[[list[str], float], tuple[int, str, str]]


class NotebookError(RuntimeError):
    pass


class NotLoggedIn(NotebookError):
    pass


def find_cli() -> str | None:
    """O `notebooklm` do PATH ou o lugar onde o uv tool instala (o app aberto pelo Finder
    adota o PATH do shell de login, mas o núcleo pode ter subido antes disso)."""
    found = shutil.which("notebooklm")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "notebooklm"
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


CHROME_APPS = (Path("/Applications/Google Chrome.app"), Path.home() / "Applications" / "Google Chrome.app")


def login_browser() -> str | None:
    """"chrome" quando o Google Chrome está instalado; senão, o Chromium do Playwright (None)."""
    return "chrome" if any(app.is_dir() for app in CHROME_APPS) else None


def cli_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(BLOCKED)}
    local_bin = str(Path.home() / ".local" / "bin")
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    if local_bin not in parts:
        parts.append(local_bin)
    env["PATH"] = os.pathsep.join(parts)
    env["NO_COLOR"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(argv: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=cli_env(), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise NotebookError(f"o NotebookLM não respondeu em {int(timeout)} s") from exc
    except OSError as exc:
        raise NotebookError(f"não consegui rodar o notebooklm: {exc}") from exc
    return done.returncode, done.stdout or "", done.stderr or ""


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = VERSION.search(text or "")
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def check_id(value: str, what: str = "caderno") -> str:
    value = str(value or "").strip()
    if not ID.match(value):
        raise NotebookError(f"id de {what} inválido")
    return value


def notebook_url(notebook_id: str | None) -> str:
    return f"{HOST}/notebook/{notebook_id}" if notebook_id else HOST


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").strip().splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


#: O que o `notebooklm login` escreve quando não termina, no que a tela mostra ao Pedro.
LOGIN_ERRORS = (
    ("Login not detected", "o login do Google não terminou a tempo: use Entrar de novo"),
    ("browser window was closed", "a janela do login foi fechada antes de o Google confirmar"),
    ("Could not verify a stable Google cookie", "o Google não confirmou a sessão: termine o login na janela e use Entrar de novo"),
    ("Google Chrome not found", "o Google Chrome não foi achado para o login"),
)


def login_error(out: str, code: int) -> str:
    for marker, text in LOGIN_ERRORS:
        if marker in (out or ""):
            return text
    return _last_line(out) or f"saiu com {code}"


class NotebookLM:
    def __init__(
        self,
        run: Runner | None = None,
        which: Callable[[], str | None] = find_cli,
        on_change: Callable[[dict], None] | None = None,
        spawn: Callable[..., subprocess.Popen] | None = None,
        browser: Callable[[], str | None] = login_browser,
    ) -> None:
        self._runner = run or _run
        self._which = which
        self._spawn = spawn or subprocess.Popen
        self._browser = browser
        self.on_change = on_change or (lambda _status: None)
        self._lock = threading.Lock()
        self._status: tuple[float, dict] | None = None
        self._lists: dict[str, tuple[float, Any]] = {}
        self._login: dict = {"rodando": False}
        self._login_proc: subprocess.Popen | None = None

    # --- execução -----------------------------------------------------------------

    def installed(self) -> bool:
        return bool(self._which())

    def _cli(self) -> str:
        cli = self._which()
        if not cli:
            raise NotebookError('o notebooklm-py não está instalado: rode uv tool install "notebooklm-py[browser]"')
        return cli

    def _json(self, args: list[str], timeout: float = TIMEOUT) -> Any:
        code, out, err = self._runner([self._cli(), *args], timeout)
        text = out.strip()
        data: Any = None
        if text:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                # Algum aviso na saída antes do JSON: o objeto começa na primeira linha com { ou [.
                start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
                if start > 0:
                    try:
                        data = json.loads(text[start:])
                    except json.JSONDecodeError:
                        data = None
        if isinstance(data, dict) and data.get("error") is True:
            message = str(data.get("message") or "erro do NotebookLM")
            if str(data.get("code") or "").upper().startswith("AUTH") or ("login" in message.lower() and "expired" in message.lower()):
                self._forget_status()
                raise NotLoggedIn("o login do NotebookLM venceu: use Entrar na aba NotebookLM do Estudo")
            raise NotebookError(message[:400])
        if code != 0 or data is None:
            detail = _last_line(err) or _last_line(out) or f"saiu com {code}"
            if "notebooklm login" in (err + out):
                self._forget_status()
                raise NotLoggedIn("o login do NotebookLM venceu: use Entrar na aba NotebookLM do Estudo")
            raise NotebookError(f"o NotebookLM falhou: {detail}")
        return data

    def _cached(self, key: str, ttl: float, load: Callable[[], Any], fresh: bool = False) -> Any:
        now = time.time()
        with self._lock:
            hit = self._lists.get(key)
        if hit and not fresh and now - hit[0] < ttl:
            return hit[1]
        value = load()
        with self._lock:
            self._lists[key] = (now, value)
        return value

    def _forget_status(self) -> None:
        with self._lock:
            self._status = None

    # --- status ---------------------------------------------------------------------

    def version(self) -> tuple[int, int, int] | None:
        code, out, err = self._runner([self._cli(), "--version"], 20)
        return parse_version(out + err) if code == 0 else None

    def status(self, fresh: bool = False) -> dict:
        """Instalado, versão e login. O login vai à rede: fica guardado uns minutos."""
        with self._lock:
            cached = self._status
            login = dict(self._login)
        if cached and not fresh and time.time() - cached[0] < STATUS_TTL:
            return {**cached[1], "entrando": login}
        cli = self._which()
        base: dict = {"instalado": bool(cli), "versao": None, "versao_ok": False, "logado": False, "erro": None, "host": HOST}
        if not cli:
            base["erro"] = 'o notebooklm-py não está instalado: rode uv tool install "notebooklm-py[browser]" no Terminal'
            return {**base, "entrando": login}
        try:
            version = self.version()
        except NotebookError as exc:
            version = None
            base["erro"] = str(exc)
        base["versao"] = ".".join(map(str, version)) if version else None
        base["versao_ok"] = bool(version and version >= MIN_VERSION)
        if version and not base["versao_ok"]:
            base["erro"] = (
                f"o notebooklm-py {base['versao']} não conhece o endereço novo do NotebookLM (notebook.google.com): "
                "rode uv tool upgrade notebooklm-py no Terminal"
            )
        elif version:
            try:
                code, out, err = self._runner([cli, "auth", "check", "--test", "--json"], 60)
                data = json.loads(out) if out.strip() else {}
                checks = data.get("checks") or {}
                base["logado"] = data.get("status") == "ok" and checks.get("token_fetch") is True
                if not base["logado"]:
                    detail = str((data.get("details") or {}).get("error") or _last_line(err) or "")
                    base["erro"] = "o login do NotebookLM venceu ou não foi feito: use Entrar" if "login" in detail.lower() or not detail else detail[:300]
            except (NotebookError, json.JSONDecodeError) as exc:
                base["erro"] = f"não consegui conferir o login: {exc}"
        with self._lock:
            self._status = (time.time(), base)
        return {**base, "entrando": login}

    # --- leitura ----------------------------------------------------------------------

    def notebooks(self, fresh: bool = False) -> list[dict]:
        def load() -> list[dict]:
            data = self._json(["list", "--json"])
            items = data.get("notebooks", []) if isinstance(data, dict) else data if isinstance(data, list) else []
            result = []
            for nb in items:
                if not isinstance(nb, dict) or not nb.get("id"):
                    continue
                result.append({
                    "id": str(nb["id"]),
                    "titulo": str(nb.get("title") or "Sem título"),
                    "papel": nb.get("role") or ("owner" if nb.get("is_owner") else None),
                    "criado": nb.get("created_at"),
                    "visto": nb.get("last_viewed_at") or nb.get("modified_at"),
                    "url": notebook_url(str(nb["id"])),
                })  # fmt: skip
            # O mais visto por último primeiro (é o que o Pedro está estudando).
            result.sort(key=lambda n: str(n.get("visto") or n.get("criado") or ""), reverse=True)
            return result

        return self._cached("cadernos", LIST_TTL, load, fresh)

    def sources(self, notebook_id: str, fresh: bool = False) -> list[dict]:
        nb = check_id(notebook_id)

        def load() -> list[dict]:
            data = self._json(["source", "list", "-n", nb, "--json"])
            items = data.get("sources", []) if isinstance(data, dict) else data if isinstance(data, list) else []
            return [
                {
                    "id": str(s["id"]),
                    "titulo": str(s.get("title") or "Sem título"),
                    "tipo": s.get("type") or s.get("kind"),
                    "url": s.get("url"),
                    "status": s.get("status"),
                }
                for s in items
                if isinstance(s, dict) and s.get("id")
            ]

        return self._cached(f"fontes:{nb}", SOURCES_TTL, load, fresh)

    def summary(self, notebook_id: str) -> dict:
        nb = check_id(notebook_id)

        def load() -> dict:
            data = self._json(["summary", "-n", nb, "--topics", "--json"])
            data = data if isinstance(data, dict) else {}
            return {"resumo": str(data.get("summary") or ""), "topicos": [str(t) for t in data.get("suggested_topics") or [] if t]}

        return self._cached(f"resumo:{nb}", SOURCES_TTL, load)

    def ask(self, notebook_id: str, question: str, source_ids: list[str] | None = None) -> dict:
        """A resposta do NotebookLM ao caderno, com as citações ligadas ao título da fonte."""
        nb = check_id(notebook_id)
        question = " ".join(str(question or "").split()).strip()
        if not question:
            raise NotebookError("a pergunta está vazia")
        if len(question) > 4000:
            raise NotebookError("pergunta longa demais (até 4000 caracteres)")
        args = ["ask", "-n", nb, "--json"]
        for sid in source_ids or []:
            args += ["-s", check_id(sid, "fonte")]
        # "--": a pergunta pode começar com "-".
        data = self._json([*args, "--", question], ASK_TIMEOUT)
        data = data if isinstance(data, dict) else {}
        try:
            titles = {s["id"]: s["titulo"] for s in self.sources(nb)}
        except NotebookError:
            titles = {}
        refs = []
        seen: set[tuple[int, str]] = set()
        for ref in data.get("references") or []:
            if not isinstance(ref, dict):
                continue
            number = ref.get("citation_number")
            sid = str(ref.get("source_id") or "")
            key = (int(number) if isinstance(number, int) else 0, sid)
            if key in seen:
                continue
            seen.add(key)
            excerpt = " ".join(str(ref.get("cited_text") or "").split())
            refs.append({"n": number, "fonte_id": sid, "fonte": titles.get(sid, ""), "trecho": excerpt[:500]})
        return {"resposta": str(data.get("answer") or "").strip(), "citacoes": refs, "conversa": data.get("conversation_id")}

    def fulltext(self, notebook_id: str, source_id: str, start: int = 0, limit: int = FULLTEXT_LIMIT) -> dict:
        nb = check_id(notebook_id)
        sid = check_id(source_id, "fonte")

        def load() -> dict:
            data = self._json(["source", "fulltext", sid, "-n", nb, "--json", "-f", "markdown"], ASK_TIMEOUT)
            data = data if isinstance(data, dict) else {}
            inner = data.get("fulltext") if isinstance(data.get("fulltext"), dict) else data
            return {"titulo": str(inner.get("title") or ""), "texto": str(inner.get("content") or inner.get("text") or "")}

        full = self._cached(f"texto:{nb}:{sid}", SOURCES_TTL, load)
        text = full["texto"]
        start = max(0, min(int(start or 0), len(text)))
        limit = max(500, min(int(limit or FULLTEXT_LIMIT), FULLTEXT_LIMIT))
        end = min(len(text), start + limit)
        return {"titulo": full["titulo"], "texto": text[start:end], "inicio": start, "fim": end, "total": len(text)}

    # --- entrar ----------------------------------------------------------------------

    def login(self) -> dict:
        """Abre o login do Google num perfil limpo do navegador do notebooklm-py. Termina sozinho
        quando o login é detectado; o status volta a ser conferido e a tela recebe o aviso."""
        cli = self._cli()
        with self._lock:
            if self._login.get("rodando"):
                return dict(self._login)
            browser = self._browser()
            argv = [cli, "login", "--fresh", "--browser-timeout", str(BROWSER_WAIT), *(["--browser", browser] if browser else [])]
            try:
                proc = self._spawn(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=cli_env())
            except OSError as exc:
                raise NotebookError(f"não consegui abrir o login: {exc}") from exc
            self._login_proc = proc
            self._login = {"rodando": True, "inicio": time.time(), "ok": None, "erro": None, "navegador": browser or "chromium"}
            state = dict(self._login)
        threading.Thread(target=self._wait_login, args=(proc,), daemon=True).start()
        return state

    def _wait_login(self, proc: subprocess.Popen) -> None:
        try:
            out, _ = proc.communicate(timeout=LOGIN_TIMEOUT)
            ok, error = proc.returncode == 0, None if proc.returncode == 0 else login_error(out, proc.returncode)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            ok, error = False, "o login não terminou em 15 minutos"
        with self._lock:
            self._login = {**self._login, "rodando": False, "fim": time.time(), "ok": ok, "erro": error}
            self._status = None
            self._lists.clear()
            self._login_proc = None
        try:
            status = self.status(fresh=True)
            # O CLI sai com 0 mesmo quando salva uma sessão sem o __Secure-1PSIDTS: só o auth
            # check diz se o login vale.
            if ok and not status.get("logado"):
                with self._lock:
                    self._login = {**self._login, "ok": False, "erro": "a janela fechou, mas o Google não deu uma sessão que valha: use Entrar de novo"}
                    login = dict(self._login)
                status = {**status, "entrando": login}
            self.on_change(status)
        except Exception:  # aviso à tela é o de menos: o login já terminou
            pass

    def stop(self) -> None:
        """Núcleo desligando: o login aberto fecha junto."""
        proc = self._login_proc
        if proc is not None and proc.poll() is None:
            proc.kill()
