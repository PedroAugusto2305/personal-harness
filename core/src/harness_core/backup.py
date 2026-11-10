"""Backup da configuração de um perfil da MÊTIS (v0.9.8): exportar, conferir e importar um .zip.

Entra o que é configuração e trabalho do Pedro: ajustes, atalhos, comandos salvos, projetos,
barra lateral, kanban, perfis do navegador (só os nomes), contas dos conectores (sem segredo
nenhum: voltam marcadas para conectar de novo), agentes com as sprites, automações (rascunho
e publicadas, sem o .git), rotinas, temas e o placar do Estudo. Fica fora o que se recria
sozinho (runtime, bin, modelos, versões, build, bancos de cache e de execuções) e qualquer
segredo: tokens ficam no Keychain e não saem dele, as variáveis de ambiente dos agentes vão
sem valor e qualquer texto com cara de token vira <SEGREDO REMOVIDO>.

Importar grava antes um backup automático do estado atual e nunca apaga o que não está no zip.
Esse backup de antes também sai sem segredo, então importar nunca apaga um segredo que está
aqui: o arquivo que o zip traz igual ao atual (só sem os segredos) fica como está, o agente
que já existe mantém o valor das variáveis que o zip traz vazias, e o arquivo cujo segredo o
zip não traz fica como está (o importar avisa em "mantidos").
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import __version__

FORMAT = 1
MANIFEST = "manifesto.json"
FILES = (
    "ajustes.json",
    "atalhos.json",
    "comandos.json",
    "projects.json",
    "barra.json",
    "kanban.json",
    "navegador.json",
    "conectores.json",
    "estudo.db",
    "tarefas.db",
)
FOLDERS = ("agentes", "automacoes", "rotinas", "temas")
#: Nunca entram, nem dentro das pastas que entram.
SKIP_PARTS = {".git", "__pycache__", ".DS_Store", ".lixeira"}
#: O que fica fora, com o porquê (aparece na tela).
LEFT_OUT = {
    "runtime.json": "endereço do núcleo em execução",
    "bin": "o comando metis, regravado ao subir",
    "modelos": "modelos de voz e de busca (baixados de novo)",
    "versoes": "cópias das versões instaladas",
    "build": "compilação do app",
    "backups": "backups anteriores",
    "atividade.db": "histórico da Atividade",
    "brain.db": "índice do Brain (refeito do vault)",
    "automacoes.db": "execuções das automações",
    "sugestoes.db": "sugestões de precedente",
    "navegador.db": "histórico do navegador",
    "rotinas.db": "execuções das rotinas",
}
SECRET_MARK = "<SEGREDO REMOVIDO>"
# O \b no começo: o prefixo só vale no início de uma palavra, senão "task-1234567890" e
# "risk-assessment" (sk- no meio) virariam segredo e a configuração sairia estragada.
SECRET_VALUE = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{10,}|xox[abpr]-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|pk_[A-Za-z0-9_]{10,}"
    r"|GOCSPX-[A-Za-z0-9_-]{10,}|AIza[A-Za-z0-9_-]{30,}"
    # Bearer de qualquer tamanho: num cabeçalho, nem um token curto deve sair do Mac.
    r"|Bearer\s+[A-Za-z0-9._~+/=-]{3,})"
)
TEXT_SUFFIXES = {".json", ".md", ".yaml", ".yml", ".txt", ".toml"}


class BackupError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now()


def _included(home: Path) -> list[Path]:
    """Os arquivos que entram no backup, em ordem estável."""
    out: list[Path] = []
    for name in FILES:
        path = home / name
        if path.is_file():
            out.append(path)
    for folder in FOLDERS:
        base = home / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(home)
            if path.is_file() and not (SKIP_PARTS & set(rel.parts)):
                out.append(path)
    return out


def listing(home: Path) -> dict:
    """O que iria no zip agora, e o que existe na pasta e fica fora (com o motivo)."""
    items = []
    for path in _included(home):
        rel = path.relative_to(home).as_posix()
        items.append({"caminho": rel, "tamanho": path.stat().st_size, "tipo": rel.split("/")[0] if "/" in rel else "ajuste"})
    left = []
    if home.is_dir():
        for child in sorted(home.iterdir()):
            name = child.name
            if name in FILES or name in FOLDERS or name in (".DS_Store",):
                continue
            reason = LEFT_OUT.get(name) or ("banco de cache" if name.endswith(".db") else "não é configuração")
            left.append({"caminho": name, "motivo": reason})
    return {"itens": items, "fora": left}


# --- tirar segredos ------------------------------------------------------------------------


def _scrub_agent(text: str) -> tuple[str, bool]:
    """Variáveis de ambiente do agente vão sem valor (as chaves ficam, para preencher de novo)."""
    from .agents import parse_agent, parse_env, render_agent

    meta, body = parse_agent(text)
    raw = str(meta.get("env") or "").strip()
    if not raw:
        return text, False
    try:
        keys = list(parse_env(raw))
    except ValueError:
        keys = [line.split("=", 1)[0].strip() for line in raw.splitlines() if "=" in line]
    meta["env"] = "\n".join(f"{key}=" for key in keys)
    return render_agent(meta, body), True


def _scrub_connectors(raw: bytes) -> tuple[bytes, list[str]]:
    """Contas dos conectores: nada de segredo (já não há no arquivo) e todas marcadas para reconectar."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw, []
    names: list[str] = []
    if isinstance(data, list):
        for account in data:
            if isinstance(account, dict):
                account["reconectar"] = True
                names.append(str(account.get("name") or account.get("id") or ""))
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return SECRET_VALUE.sub(SECRET_MARK, text).encode("utf-8"), names


def _payload(home: Path, path: Path) -> tuple[bytes, list[str]]:
    """O conteúdo que vai para o zip, sem segredo, e os avisos sobre ele."""
    rel = path.relative_to(home).as_posix()
    raw = path.read_bytes()
    notes: list[str] = []
    if rel == "conectores.json":
        raw, names = _scrub_connectors(raw)
        if names:
            notes.append(f"contas dos conectores sem token (conectar de novo): {', '.join(names)}")
        return raw, notes
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return raw, notes
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw, notes
    if rel.startswith("agentes/") and path.suffix == ".md":
        text, changed = _scrub_agent(text)
        if changed:
            notes.append(f"{rel}: variáveis de ambiente sem valor (preencher de novo)")
    cleaned = SECRET_VALUE.sub(SECRET_MARK, text)
    if cleaned != text:
        notes.append(f"{rel}: um texto com cara de token virou {SECRET_MARK}")
    return cleaned.encode("utf-8"), notes


def _is_agent(name: str) -> bool:
    return name.startswith("agentes/") and name.endswith(".md")


def _agent_env(text: str) -> dict[str, str]:
    """As variáveis do agente (CHAVE=valor), lidas sem rigor: aqui só importa achar o valor."""
    from .agents import parse_agent

    meta, _body = parse_agent(text)
    env: dict[str, str] = {}
    for line in str(meta.get("env") or "").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            env[key.strip()] = value.strip()
    return env


def _secrets(name: str, raw: bytes) -> set[str]:
    """Os valores que a limpeza do backup tiraria deste arquivo: o env dos agentes e os textos
    com cara de token."""
    if PurePosixPath(name).suffix.lower() not in TEXT_SUFFIXES:
        return set()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return set()
    found = {match.group(0) for match in SECRET_VALUE.finditer(text)}
    if _is_agent(name):
        found |= {f"{key}={value}" for key, value in _agent_env(text).items() if value}
    return found


def _keep_env(current: bytes, incoming: bytes) -> bytes:
    """Agente que já existe: a variável que vem sem valor no zip fica com o valor de agora."""
    from .agents import parse_agent, render_agent

    try:
        have = _agent_env(current.decode("utf-8"))
        meta, body = parse_agent(incoming.decode("utf-8"))
    except UnicodeDecodeError:
        return incoming
    lines, changed = [], False
    for line in str(meta.get("env") or "").splitlines():
        key, sep, value = line.partition("=")
        if sep and not value.strip() and have.get(key.strip()):
            line, changed = f"{key.strip()}={have[key.strip()]}", True
        lines.append(line)
    if not changed:
        return incoming
    meta["env"] = "\n".join(lines)
    return render_agent(meta, body).encode("utf-8")


def _incoming(home: Path, name: str, data: bytes) -> tuple[str, bytes]:
    """O que fazer com um arquivo do zip e o conteúdo que fica no disco:
    "novo"; "igual" (o zip traz o atual, só que sem os segredos: fica o atual, com eles);
    "manter" (gravar o do zip apagaria um segredo daqui, que o backup de antes também não
    guarda: fica o atual); ou "substituir"."""
    target = home / name
    if not target.is_file():
        return "novo", data
    current = target.read_bytes()
    if data == current or data == _payload(home, target)[0]:
        return "igual", current
    if _is_agent(name):
        data = _keep_env(current, data)
    if _secrets(name, current) - _secrets(name, data):
        return "manter", current
    return "substituir", data


# --- exportar ------------------------------------------------------------------------------


def build_zip(home: Path, profile: str) -> tuple[bytes, dict]:
    buffer = io.BytesIO()
    entries = []
    notes: list[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _included(home):
            rel = path.relative_to(home).as_posix()
            data, extra = _payload(home, path)
            notes += extra
            archive.writestr(rel, data)
            entries.append({"caminho": rel, "tamanho": len(data)})
        manifest = {
            "formato": FORMAT,
            "versao_metis": __version__,
            "data": _now().isoformat(timespec="seconds"),
            "perfil": profile,
            "arquivos": entries,
            "avisos": notes,
        }
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
    return buffer.getvalue(), manifest


def _free_name(folder: Path, name: str) -> Path:
    target = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while target.exists():
        target = folder / f"{stem} ({n}){suffix}"
        n += 1
    return target


def export(home: Path, profile: str, folder: Path | None = None) -> dict:
    """Grava o zip em ~/Downloads (sem sobrescrever) e devolve onde ficou."""
    data, manifest = build_zip(home, profile)
    folder = (folder or Path.home() / "Downloads").expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    target = _free_name(folder, f"metis-backup-{profile}-{_now():%Y-%m-%d}.zip")
    target.write_bytes(data)
    return {"arquivo": str(target), "tamanho": len(data), "avisos": manifest["avisos"]}


# --- conferir e importar ---------------------------------------------------------------------


def _safe(name: str) -> str:
    """Caminho de dentro do zip, conferido: relativo, sem `..`, e só no que o backup leva."""
    if name.startswith("/") or "\\" in name:
        raise BackupError(f"caminho inválido no zip: {name}")
    parts = PurePosixPath(name).parts
    if not parts or ".." in parts or parts[0] in ("", "."):
        raise BackupError(f"caminho inválido no zip: {name}")
    if not (name in FILES or parts[0] in FOLDERS):
        raise BackupError(f"o zip traz um arquivo que não é de backup da MÊTIS: {name}")
    if SKIP_PARTS & set(parts):
        raise BackupError(f"o zip traz um arquivo que o backup não leva: {name}")
    return name


def _open(path: Path) -> tuple[zipfile.ZipFile, dict, list[str]]:
    path = Path(path).expanduser()
    if not path.is_file():
        raise BackupError(f"arquivo não encontrado: {path}")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise BackupError("isso não é um .zip válido") from exc
    names = [n for n in archive.namelist() if not n.endswith("/")]
    if MANIFEST not in names:
        archive.close()
        raise BackupError("o zip não tem o manifesto: não é um backup da MÊTIS")
    try:
        manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        archive.close()
        raise BackupError("o manifesto do backup está ilegível") from exc
    if not isinstance(manifest, dict) or manifest.get("formato") != FORMAT:
        archive.close()
        raise BackupError(f"backup de um formato que esta versão não lê (formato {manifest.get('formato') if isinstance(manifest, dict) else '?'})")
    files = []
    try:
        for name in names:
            if name == MANIFEST:
                continue
            files.append(_safe(name))
    except BackupError:
        archive.close()
        raise
    return archive, manifest, files


def check(home: Path, path: Path) -> dict:
    """O que mudaria se importar, sem gravar nada."""
    archive, manifest, files = _open(path)
    with archive:
        new, replaced, kept = [], [], []
        for name in files:
            action, _data = _incoming(home, name, archive.read(name))
            if action == "novo":
                new.append(name)
            elif action == "substituir":
                replaced.append(name)
            elif action == "manter":
                kept.append(name)
        accounts: list[str] = []
        if "conectores.json" in files:
            try:
                data = json.loads(archive.read("conectores.json").decode("utf-8"))
                accounts = [str(a.get("name") or a.get("id")) for a in data if isinstance(a, dict)]
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                accounts = []
    return {
        "versao": manifest.get("versao_metis", ""),
        "data": manifest.get("data", ""),
        "perfil": manifest.get("perfil", ""),
        "novos": new,
        "substituidos": replaced,
        "mantidos": kept,
        "contas_para_reconectar": accounts,
        "avisos": manifest.get("avisos") or [],
    }


def _commit_automations(home: Path) -> None:
    folder = home / "automacoes"
    if not (folder / ".git").is_dir() or shutil.which("git") is None:
        return
    for args in (["add", "-A"], ["commit", "-q", "-m", "importar backup"]):
        subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, timeout=20)


def restore(home: Path, profile: str, path: Path) -> dict:
    """Grava antes um backup do estado atual; depois restaura os arquivos do zip (substitui os
    que existem, cria os novos e não apaga o que o zip não traz). Como o backup de antes sai
    sem segredo, nenhum segredo daqui é apagado: veja `_incoming`."""
    archive, _manifest, files = _open(path)
    with archive:
        before_dir = home / "backups"
        before_dir.mkdir(parents=True, exist_ok=True)
        data, _ = build_zip(home, profile)
        before = _free_name(before_dir, f"antes-de-importar-{_now():%Y-%m-%d-%H%M}.zip")
        before.write_bytes(data)
        restored, kept = [], []
        for name in files:
            action, content = _incoming(home, name, archive.read(name))
            if action == "manter":
                kept.append(name)
                continue
            if action != "igual":
                target = home / name
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".importando")
                tmp.write_bytes(content)
                tmp.replace(target)
            restored.append(name)
    _commit_automations(home)
    return {"restaurados": restored, "mantidos": kept, "backup_anterior": str(before), "reiniciar": True}


def copy_config(source: Path, target: Path, profile: str) -> list[str]:
    """Perfil novo "copiando a configuração": o mesmo zip do backup, aberto na pasta nova."""
    data, _ = build_zip(source, profile)
    target.mkdir(parents=True, exist_ok=True)
    restored = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if name == MANIFEST or name.endswith("/"):
                continue
            dest = target / _safe(name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.read(name))
            restored.append(name)
    return restored

