"""v1.0.0: revisão do PR #24 (perfis, backup, Skills e estudo). Cada teste falhava antes da correção."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import backup, profiles, skills_manager
from harness_core.app import create_app
from harness_core.config import DEFAULT_PORT, load_settings
from harness_core.connectors import ConnectorStore
from harness_core.keychain import MemoryVault

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
AGENT = '---\nnome: Aurora\ncli: claude\nenv: "OPENAI_API_KEY=sk-abcdefghijklmnop1234\\nMODO=coach"\n---\n\n{body}\n'
ACCOUNT = {"id": "slack-pessoal", "kind": "slack", "name": "Slack pessoal", "created": 1.0, "meta": {"team": "Casa"}}


@pytest.fixture
def places(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Registro, pasta principal, pasta dos perfis e Lixeira, todos na pasta temporária."""
    main = tmp_path / "principal"
    main.mkdir()
    out = {"main": main, "registry": main / "perfis.json", "root": tmp_path / "perfis", "trash": tmp_path / "Lixeira"}
    monkeypatch.setenv("HARNESS_MAIN_HOME", str(main))
    monkeypatch.setenv("HARNESS_PROFILES", str(out["registry"]))
    monkeypatch.setenv("HARNESS_PROFILES_DIR", str(out["root"]))
    monkeypatch.setattr(profiles, "TRASH", out["trash"])
    for name in ("HARNESS_HOME", "HARNESS_PORT", "HARNESS_PROFILE", "BRAIN_VAULT"):
        monkeypatch.delenv(name, raising=False)
    return out


def home_with(path: Path, body: str = "Coach de estudo.", flow: str = "nome: Briefing\nnota: 'Bearer abcdefghijklmnopqrstu'\n") -> Path:
    """Uma pasta de perfil com um agente com env, uma conta de conector e uma automação com token."""
    (path / "agentes").mkdir(parents=True, exist_ok=True)
    (path / "agentes" / "aurora.md").write_text(AGENT.format(body=body), encoding="utf-8")
    (path / "conectores.json").write_text(json.dumps([ACCOUNT]), encoding="utf-8")
    (path / "automacoes").mkdir(exist_ok=True)
    (path / "automacoes" / "briefing.yaml").write_text(flow, encoding="utf-8")
    (path / "ajustes.json").write_text(json.dumps({"hibernar_min": 15}), encoding="utf-8")
    return path


def exported(home: Path, folder: Path) -> Path:
    return Path(backup.export(home, "principal", folder)["arquivo"])


# --- conectores ------------------------------------------------------------------------------


def test_connector_accounts_survive_import_and_profile_copy(tmp_path):
    """O backup marca as contas com "reconectar"; antes, a conta inteira sumia ao ler."""
    source = home_with(tmp_path / "origem")
    archive = exported(source, tmp_path / "Downloads")
    fresh = tmp_path / "outro"
    fresh.mkdir()
    backup.restore(fresh, "outro", archive)
    assert [a.id for a in ConnectorStore(fresh, MemoryVault()).list()] == ["slack-pessoal"]

    copied = tmp_path / "copia"
    backup.copy_config(source, copied, "principal")
    assert [a.name for a in ConnectorStore(copied, MemoryVault()).list()] == ["Slack pessoal"]


# --- importar sem apagar segredo ---------------------------------------------------------------


def test_export_then_import_in_the_same_profile_keeps_every_secret(tmp_path):
    home = home_with(tmp_path / "home")
    agent_before = (home / "agentes" / "aurora.md").read_bytes()
    flow_before = (home / "automacoes" / "briefing.yaml").read_bytes()
    archive = exported(home, tmp_path / "Downloads")

    checked = backup.check(home, archive)
    assert checked["substituidos"] == [] and checked["mantidos"] == []
    done = backup.restore(home, "principal", archive)
    assert (home / "agentes" / "aurora.md").read_bytes() == agent_before
    assert (home / "automacoes" / "briefing.yaml").read_bytes() == flow_before
    assert "agentes/aurora.md" in done["restaurados"] and done["mantidos"] == []
    # O backup de antes continua sem segredo nenhum.
    with zipfile.ZipFile(done["backup_anterior"]) as z:
        joined = b"".join(z.read(n) for n in z.namelist())
    assert b"sk-abcdefghijklmnop1234" not in joined and b"Bearer abcdefghijklmnopqrstu" not in joined


def test_import_fills_empty_env_of_an_existing_agent(tmp_path):
    """O agente do zip mudou e vem com o env sem valor: entra o texto novo, ficam os valores daqui."""
    home = home_with(tmp_path / "home")
    other = home_with(tmp_path / "outro", body="Coach de estudo e de inglês.")
    archive = exported(other, tmp_path / "Downloads")

    assert "agentes/aurora.md" in backup.check(home, archive)["substituidos"]
    backup.restore(home, "principal", archive)
    text = (home / "agentes" / "aurora.md").read_text(encoding="utf-8")
    assert "Coach de estudo e de inglês." in text
    assert "OPENAI_API_KEY=sk-abcdefghijklmnop1234" in text and "MODO=coach" in text


def test_import_keeps_a_file_whose_secret_the_zip_does_not_bring(tmp_path):
    home = home_with(tmp_path / "home")
    flow_before = (home / "automacoes" / "briefing.yaml").read_bytes()
    other = home_with(tmp_path / "outro", flow="nome: Briefing novo\nnota: 'Bearer zzzzzzzzzzzzzzzzzzzz'\n")
    (other / "ajustes.json").write_text(json.dumps({"hibernar_min": 60}), encoding="utf-8")
    archive = exported(other, tmp_path / "Downloads")

    checked = backup.check(home, archive)
    assert checked["mantidos"] == ["automacoes/briefing.yaml"] and "ajustes.json" in checked["substituidos"]
    done = backup.restore(home, "principal", archive)
    assert done["mantidos"] == ["automacoes/briefing.yaml"]
    assert (home / "automacoes" / "briefing.yaml").read_bytes() == flow_before
    assert json.loads((home / "ajustes.json").read_text())["hibernar_min"] == 60


# --- o que tem cara de token ----------------------------------------------------------------


def test_secret_pattern_only_matches_at_the_start_of_a_word():
    for text in ('{"id": "task-1234567890"}', '{"titulo": "risk-assessment"}', "desk-organizer-2026", "stack_pk_1234567890ab"):
        assert backup.SECRET_VALUE.sub(backup.SECRET_MARK, text) == text, text
    for text in ('{"chave": "sk-ant-api03-abcdefghij"}', "OPENAI_API_KEY=sk-proj-abcdefghij", "Authorization: Bearer xyz123"):
        assert backup.SECRET_MARK in backup.SECRET_VALUE.sub(backup.SECRET_MARK, text), text


def test_kanban_ids_survive_the_backup(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    board = {"cards": [{"id": "task-1234567890", "titulo": "risk-assessment do trimestre"}]}
    (home / "kanban.json").write_text(json.dumps(board), encoding="utf-8")
    data, manifest = backup.build_zip(home, "principal")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert json.loads(z.read("kanban.json")) == board
    assert not any("kanban.json" in note for note in manifest["avisos"])


# --- Skills ----------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["..", ".", "a/../..", ""])
def test_skill_actions_refuse_names_that_leave_the_skills_folder(tmp_path, name):
    claude = tmp_path / "claude"
    skills = claude / "skills"
    (skills / "boa").mkdir(parents=True)
    (skills / "boa" / "SKILL.md").write_text("---\nname: boa\n---\n", encoding="utf-8")
    (claude / ".credentials.json").write_text("{}", encoding="utf-8")
    for action in (
        lambda: skills_manager.trash(name, skills, tmp_path / "Lixeira"),
        lambda: skills_manager.export(name, skills, tmp_path / "Downloads"),
        lambda: skills_manager.copy(name, skills, tmp_path / "codex" / "skills"),
        lambda: skills_manager.update(name, skills),
    ):
        with pytest.raises(skills_manager.SkillError):
            action()
    assert (claude / ".credentials.json").exists() and (skills / "boa" / "SKILL.md").exists()
    assert not (tmp_path / "Lixeira").exists() and not (tmp_path / "Downloads").exists()


def test_skill_routes_refuse_dot_dot(settings, accounts, tmp_path):
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False, keychain=MemoryVault())
    claude = tmp_path / "homes" / "claude"
    (claude / "skills").mkdir(parents=True)
    (claude / ".credentials.json").write_text("{}", encoding="utf-8")
    app.state.cli_homes = {"claude": claude, "codex": tmp_path / "homes" / "codex"}
    app.state.skills_downloads = tmp_path / "Downloads"
    app.state.skills_trash = tmp_path / "Lixeira"
    with TestClient(app) as client:
        gone = client.delete("/skills/%2E%2E", params={"destino": "claude"}, headers=AUTH)
        zipped = client.post("/skills/%2E%2E/exportar", json={"destino": "claude"}, headers=AUTH)
    assert gone.status_code == 400 and zipped.status_code == 400
    assert (claude / ".credentials.json").exists() and not (tmp_path / "Downloads").exists()


# --- perfis ----------------------------------------------------------------------------------


def test_brain_vault_from_the_environment_beats_the_profile_vault(places, tmp_path, monkeypatch):
    real = tmp_path / "Brain de verdade"
    fake = tmp_path / "Brain de teste"
    real.mkdir()
    fake.mkdir()
    profiles.ProfileRegistry(DEFAULT_PORT).update("principal", vault=str(real))
    monkeypatch.setenv("BRAIN_VAULT", str(fake))
    assert load_settings().brain == fake
    monkeypatch.delenv("BRAIN_VAULT")
    assert load_settings().brain == real.resolve()


def test_create_with_a_bad_vault_leaves_no_orphan_folder(places):
    reg = profiles.ProfileRegistry(DEFAULT_PORT)
    with pytest.raises(profiles.ProfileError):
        reg.create("Seller Pro", vault=str(places["main"] / "não existe"))
    assert not (places["root"] / "seller-pro").exists()
    assert reg.create("Seller Pro").id == "seller-pro"


def test_delete_profile_with_a_slash_in_the_name(places):
    reg = profiles.ProfileRegistry(DEFAULT_PORT)
    made = reg.create("Casa/Trabalho")
    (made.folder / "ajustes.json").write_text("{}", encoding="utf-8")
    moved = Path(reg.delete(made.id))
    assert moved.parent == places["trash"] and moved.name == "MÊTIS perfil Casa-Trabalho"
    assert (moved / "ajustes.json").exists() and not made.folder.exists()
