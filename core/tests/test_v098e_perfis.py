"""v0.9.8, parte 5: perfis completos da MÊTIS (pasta de dados e núcleo próprios) e backup."""

from __future__ import annotations

import dataclasses
import io
import json
import sqlite3
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import backup, profiles
from harness_core.app import create_app
from harness_core.config import DEFAULT_PORT, load_settings
from harness_core.keychain import SERVICE, Keychain, MemoryVault, service_for

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


@pytest.fixture
def places(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Registro, pasta principal, pasta dos perfis e Lixeira, todos na pasta temporária."""
    main = tmp_path / "principal"
    main.mkdir()
    out = {
        "main": main,
        "registry": main / "perfis.json",
        "root": tmp_path / "perfis",
        "trash": tmp_path / "Lixeira",
        "brain": tmp_path / "Brain do Trabalho",
    }
    out["brain"].mkdir()
    monkeypatch.setenv("HARNESS_MAIN_HOME", str(main))
    monkeypatch.setenv("HARNESS_PROFILES", str(out["registry"]))
    monkeypatch.setenv("HARNESS_PROFILES_DIR", str(out["root"]))
    monkeypatch.setattr(profiles, "TRASH", out["trash"])
    for name in ("HARNESS_HOME", "HARNESS_PORT", "HARNESS_PROFILE", "BRAIN_VAULT"):
        monkeypatch.delenv(name, raising=False)
    return out


def registry(places: dict[str, Path]) -> profiles.ProfileRegistry:
    return profiles.ProfileRegistry(DEFAULT_PORT)


# --- registro ------------------------------------------------------------------------------


def test_main_profile_always_exists_and_reading_writes_nothing(places):
    reg = registry(places)
    state = reg.state()
    assert state["ativo"] == "principal"
    assert [p["id"] for p in state["perfis"]] == ["principal"]
    assert state["perfis"][0]["porta"] == DEFAULT_PORT
    assert not places["registry"].exists()


def test_create_rename_ports_and_vault(places):
    reg = registry(places)
    pessoal = reg.create("Pessoal")
    seller = reg.create("Seller Pro", vault=str(places["brain"]))
    assert pessoal.id == "pessoal" and pessoal.folder == places["root"] / "pessoal" and pessoal.folder.is_dir()
    assert {pessoal.porta, seller.porta} == {DEFAULT_PORT + 10, DEFAULT_PORT + 20}
    assert seller.brain == places["brain"].resolve()
    with pytest.raises(profiles.ProfileError) as same:
        reg.create("pessoal")
    assert same.value.code == 409
    with pytest.raises(profiles.ProfileError):
        reg.create("x", vault=str(places["main"] / "não existe"))
    renamed = reg.update("pessoal", nome="Casa")
    assert renamed.nome == "Casa" and renamed.id == "pessoal"
    assert reg.update("seller-pro", clear_vault=True).vault is None
    # Porta livre volta a ser usada, mas nunca repete entre os perfis que existem.
    reg.delete("pessoal")
    third = reg.create("Estudo")
    ports = [p.porta for p in reg.list()]
    assert len(ports) == len(set(ports)) and third.porta == DEFAULT_PORT + 10


def test_delete_goes_to_trash_and_refuses_main_active_and_unknown(places):
    reg = registry(places)
    profile = reg.create("Pessoal")
    (profile.folder / "ajustes.json").write_text("{}", encoding="utf-8")
    with pytest.raises(profiles.ProfileError):
        reg.delete("principal")
    reg.activate("pessoal")
    with pytest.raises(profiles.ProfileError):
        reg.delete("pessoal")
    reg.activate("principal")
    moved = reg.delete("pessoal")
    assert Path(moved).parent == places["trash"] and (Path(moved) / "ajustes.json").exists()
    assert not profile.folder.exists()
    with pytest.raises(profiles.ProfileError) as unknown:
        reg.delete("pessoal")
    assert unknown.value.code == 404


def test_activate_and_settings_follow_the_profile(places, monkeypatch):
    reg = registry(places)
    seller = reg.create("Seller Pro", vault=str(places["brain"]))
    reg.activate("seller-pro")
    assert reg.active() == "seller-pro"
    monkeypatch.setenv("HARNESS_PROFILE", "seller-pro")
    s = load_settings()
    assert s.profile == "seller-pro" and s.home == seller.folder and s.port == seller.porta
    assert s.brain == places["brain"].resolve() and not s.locked
    # HARNESS_HOME no ambiente vale por cima e trava a troca (app de desenvolvimento).
    monkeypatch.setenv("HARNESS_HOME", str(places["main"] / "dev"))
    locked = load_settings()
    assert locked.home == places["main"] / "dev" and locked.locked
    # Perfil que não existe mais cai no principal.
    monkeypatch.delenv("HARNESS_HOME")
    monkeypatch.setenv("HARNESS_PROFILE", "sumiu")
    fallback = load_settings()
    assert fallback.profile == "principal" and fallback.home == places["main"] and fallback.port == DEFAULT_PORT


def test_keychain_service_per_profile(monkeypatch):
    calls: list[tuple] = []
    fake = types.ModuleType("keyring")
    fake.set_password = lambda service, key, value: calls.append(("set", service, key))
    fake.get_password = lambda service, key: calls.append(("get", service, key)) or None
    monkeypatch.setitem(sys.modules, "keyring", fake)
    assert service_for("principal") == SERVICE and service_for("") == SERVICE
    Keychain(service_for("pessoal")).set("conector:slack", "xoxb-segredo")
    Keychain(service_for("principal")).get("conector:slack")
    assert calls == [("set", f"{SERVICE}.pessoal", "conector:slack"), ("get", SERVICE, "conector:slack")]


def test_cli_shim_carries_the_profile(tmp_path):
    from harness_core.relay import install_cli_shim

    principal = install_cli_shim(tmp_path / "a", tmp_path / "home a").read_text(encoding="utf-8")
    other = install_cli_shim(tmp_path / "b", tmp_path / "home b", "pessoal").read_text(encoding="utf-8")
    assert "HARNESS_PROFILE" not in principal
    assert "HARNESS_PROFILE=pessoal" in other and "home b" in other


# --- rotas -----------------------------------------------------------------------------------


def seed(home: Path) -> None:
    """Uma pasta de perfil com um pouco de tudo: o que entra e o que fica fora do backup."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "ajustes.json").write_text(json.dumps({"hibernar_min": 15}), encoding="utf-8")
    (home / "atalhos.json").write_text("{}", encoding="utf-8")
    (home / "conectores.json").write_text(
        json.dumps([{"id": "slack-pessoal", "kind": "slack", "name": "Slack pessoal", "meta": {"team": "Casa"}}]), encoding="utf-8"
    )
    (home / "runtime.json").write_text('{"token": "segredo-do-nucleo"}', encoding="utf-8")
    for name in ("atividade.db", "estudo.db"):
        with sqlite3.connect(home / name) as con:
            con.execute("create table if not exists marca(x text)")
    (home / "bin").mkdir(exist_ok=True)
    (home / "bin" / "metis").write_text("#!/bin/sh", encoding="utf-8")
    agents = home / "agentes"
    (agents / "sprites").mkdir(parents=True, exist_ok=True)
    (agents / "sprites" / "aurora.png").write_bytes(b"\x89PNG\r\n")
    (agents / "aurora.md").write_text(
        '---\nnome: Aurora\ncli: claude\nenv: "OPENAI_API_KEY=sk-abcdefghijklmnop1234\\nMODO=coach"\n---\n\nCoach de estudo.\n', encoding="utf-8"
    )
    (agents / ".lixeira").mkdir(exist_ok=True)
    (agents / ".lixeira" / "velho.md").write_text("apagado", encoding="utf-8")
    flows = home / "automacoes"
    (flows / "publicadas").mkdir(parents=True, exist_ok=True)
    (flows / ".git").mkdir(exist_ok=True)
    (flows / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (flows / "briefing.yaml").write_text("nome: Briefing\nnota: 'Bearer abcdefghijklmnopqrstu'\n", encoding="utf-8")
    (flows / "publicadas" / "briefing.yaml").write_text("nome: Briefing\n", encoding="utf-8")
    (home / "rotinas").mkdir(exist_ok=True)
    (home / "rotinas" / "check-in.md").write_text("---\nnome: Check-in\n---\n", encoding="utf-8")


@pytest.fixture
def core(settings, accounts, places, tmp_path):
    seed(settings.home)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False, keychain=MemoryVault())
    with TestClient(app) as client:
        yield client, app


def test_profile_routes(core, places, settings, monkeypatch):
    client, app = core
    listed = client.get("/perfis", headers=AUTH).json()
    assert listed["atual"] == "principal" and listed["travado"] is False and listed["perfis"][0]["id"] == "principal"
    made = client.post("/perfis", json={"nome": "Seller Pro", "copiar": True}, headers=AUTH)
    assert made.status_code == 201, made.text
    folder = Path(made.json()["pasta"]).expanduser()
    # Copiou a configuração, sem segredo nenhum e sem o que se recria.
    assert json.loads((folder / "ajustes.json").read_text())["hibernar_min"] == 15
    assert not (folder / "runtime.json").exists() and not (folder / "atividade.db").exists()
    assert "sk-abcdefghijklmnop1234" not in (folder / "agentes" / "aurora.md").read_text()
    assert json.loads((folder / "conectores.json").read_text())[0]["reconectar"] is True
    assert client.post("/perfis", json={"nome": "Vazio"}, headers=AUTH).status_code == 201
    assert client.patch("/perfis/vazio", json={"nome": "Vazio 2"}, headers=AUTH).json()["nome"] == "Vazio 2"
    assert client.delete("/perfis/principal", headers=AUTH).status_code == 400
    assert client.delete("/perfis/vazio", headers=AUTH).status_code == 204
    activated = client.post("/perfis/seller-pro/ativar", headers=AUTH).json()
    assert activated["id"] == "seller-pro" and activated["porta"] == DEFAULT_PORT + 10
    assert client.get("/perfis", headers=AUTH).json()["ativo"] == "seller-pro"
    assert client.post("/perfis/nao-existe/ativar", headers=AUTH).status_code == 404


def test_locked_core_cannot_switch(settings, accounts, places):
    locked = dataclasses.replace(settings, locked=True)
    app = create_app(locked, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False, keychain=MemoryVault())
    with TestClient(app) as client:
        assert client.get("/perfis", headers=AUTH).json()["travado"] is True
        client.post("/perfis", json={"nome": "Pessoal"}, headers=AUTH)
        assert client.post("/perfis/pessoal/ativar", headers=AUTH).status_code == 409


# --- backup ------------------------------------------------------------------------------------


def test_backup_listing_and_export(core, settings, tmp_path):
    client, _ = core
    listing = client.get("/backup", headers=AUTH).json()
    paths = {i["caminho"] for i in listing["itens"]}
    assert {"ajustes.json", "conectores.json", "estudo.db", "agentes/aurora.md", "agentes/sprites/aurora.png", "automacoes/briefing.yaml", "automacoes/publicadas/briefing.yaml", "rotinas/check-in.md"} <= paths
    assert not any(p.startswith(("automacoes/.git", "agentes/.lixeira", "bin/")) or p in ("runtime.json", "atividade.db") for p in paths)
    assert {f["caminho"] for f in listing["fora"]} >= {"runtime.json", "atividade.db", "bin"}

    exported = client.post("/backup/exportar", json={"destino": str(tmp_path / "Downloads")}, headers=AUTH).json()
    archive = Path(exported["arquivo"])
    assert archive.name == f"metis-backup-principal-{backup._now():%Y-%m-%d}.zip"
    again = client.post("/backup/exportar", json={"destino": str(tmp_path / "Downloads")}, headers=AUTH).json()
    assert Path(again["arquivo"]).name.endswith("(2).zip")
    with zipfile.ZipFile(archive) as z:
        names = set(z.namelist())
        everything = b"".join(z.read(n) for n in names)
        manifest = json.loads(z.read("manifesto.json"))
    assert "manifesto.json" in names and "runtime.json" not in names and not any(".git" in n for n in names)
    assert manifest["formato"] == 1 and manifest["perfil"] == "principal" and manifest["arquivos"]
    for secret in (b"sk-abcdefghijklmnop1234", b"segredo-do-nucleo", b"Bearer abcdefghijklmnopqrstu"):
        assert secret not in everything
    assert b"OPENAI_API_KEY=" in everything and b"MODO=" in everything


def zip_with(tmp_path: Path, files: dict[str, bytes], manifest: dict | None = None, name: str = "b.zip") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        if manifest is not None:
            z.writestr("manifesto.json", json.dumps(manifest))
        for key, data in files.items():
            z.writestr(key, data)
    return path


def test_backup_check_refuses_bad_zips(core, tmp_path):
    client, _ = core
    good = {"formato": 1, "versao_metis": "0.9.8", "data": "2026-11-09", "perfil": "x", "arquivos": []}
    no_manifest = zip_with(tmp_path, {"ajustes.json": b"{}"}, None, "a.zip")
    old = zip_with(tmp_path, {"ajustes.json": b"{}"}, {**good, "formato": 99}, "c.zip")
    slip = zip_with(tmp_path, {"../fora.txt": b"mal"}, good, "d.zip")
    foreign = zip_with(tmp_path, {"runtime.json": b"{}"}, good, "e.zip")
    for path in (no_manifest, old, slip, foreign):
        assert client.post("/backup/conferir", json={"arquivo": str(path)}, headers=AUTH).status_code == 400, path.name
    (tmp_path / "nao-zip.zip").write_text("oi")
    assert client.post("/backup/conferir", json={"arquivo": str(tmp_path / "nao-zip.zip")}, headers=AUTH).status_code == 400


def test_backup_check_and_import_with_automatic_backup_first(core, settings, tmp_path):
    client, _ = core
    incoming = zip_with(
        tmp_path,
        {
            "ajustes.json": json.dumps({"hibernar_min": 60}).encode(),
            "temas/noite.json": b'{"nome": "Noite"}',
            "conectores.json": json.dumps([{"id": "clickup-trabalho", "name": "ClickUp trabalho", "reconectar": True}]).encode(),
        },
        {"formato": 1, "versao_metis": "0.9.8", "data": "2026-11-09T10:00", "perfil": "trabalho", "arquivos": []},
    )
    checked = client.post("/backup/conferir", json={"arquivo": str(incoming)}, headers=AUTH).json()
    assert checked["perfil"] == "trabalho" and "temas/noite.json" in checked["novos"]
    assert {"ajustes.json", "conectores.json"} <= set(checked["substituidos"])
    assert checked["contas_para_reconectar"] == ["ClickUp trabalho"]
    assert json.loads((settings.home / "ajustes.json").read_text())["hibernar_min"] == 15  # conferir não grava

    done = client.post("/backup/importar", json={"arquivo": str(incoming)}, headers=AUTH).json()
    assert done["reiniciar"] is True and set(done["restaurados"]) == {"ajustes.json", "temas/noite.json", "conectores.json"}
    before = Path(done["backup_anterior"])
    assert before.parent == settings.home / "backups" and before.name.startswith("antes-de-importar-")
    with zipfile.ZipFile(before) as z:
        assert json.loads(z.read("ajustes.json"))["hibernar_min"] == 15
    assert json.loads((settings.home / "ajustes.json").read_text())["hibernar_min"] == 60
    assert (settings.home / "temas" / "noite.json").exists()
    # O que o zip não traz fica onde estava.
    assert (settings.home / "rotinas" / "check-in.md").exists() and (settings.home / "atividade.db").exists()


def test_import_commits_the_automations(tmp_path):
    home = tmp_path / "home"
    flows = home / "automacoes"
    flows.mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=flows, capture_output=True, text=True, check=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.name", "MÊTIS")
    run("config", "user.email", "metis@localhost")
    incoming = zip_with(
        tmp_path,
        {"automacoes/nova.yaml": b"nome: Nova\n", "automacoes/publicadas/nova.yaml": b"nome: Nova\n"},
        {"formato": 1, "versao_metis": "0.9.8", "data": "", "perfil": "x", "arquivos": []},
    )
    backup.restore(home, "principal", incoming)
    log = run("log", "--oneline").stdout
    assert "importar backup" in log
    assert (flows / "publicadas" / "nova.yaml").exists()


def test_build_zip_in_memory_has_no_secret(tmp_path):
    seed(tmp_path / "h")
    data, manifest = backup.build_zip(tmp_path / "h", "principal")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        joined = b"".join(z.read(n) for n in z.namelist())
    assert b"sk-abcdefghijklmnop1234" not in joined
    assert any("variáveis de ambiente" in note for note in manifest["avisos"])
    assert any("conectar de novo" in note for note in manifest["avisos"])


def test_backup_scrubs_short_bearer_tokens():
    """Um 'Bearer' curto num passo de código também sai como segredo removido."""
    from harness_core import backup

    text = 'const headers = {"Authorization": "Bearer sk-abc123"};'
    cleaned = backup.SECRET_VALUE.sub(backup.SECRET_MARK, text)
    assert "sk-abc123" not in cleaned
    assert backup.SECRET_MARK in cleaned
