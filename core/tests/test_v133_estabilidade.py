"""v1.3.3: a MÊTIS que fechava sozinha e a lista de projetos que sumia (print do Pedro, 2026-11-13).

O núcleo esgotou os 256 arquivos abertos (um `codex app-server` órfão a cada consulta da cota,
coberto em test_usage_and_voice.py), a lista de projetos veio vazia e a janela fechou com um
abort() no protocolo tauri:// do wry."""

import errno
import json
import tomllib
from pathlib import Path

import pytest

from harness_core.projects import ProjectError, ProjectStore

ROOT = Path(__file__).resolve().parents[2]


def test_release_build_lets_objc_exceptions_be_caught():
    # Com panic = "abort", o objc2::exception::catch que o wry põe em volta do didReceiveData
    # não pega a exceção do WebKit (carga cancelada com a página recarregando) e o app aborta.
    cargo = tomllib.loads((ROOT / "app/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    assert cargo["profile"]["release"].get("panic", "unwind") == "unwind"


def test_projects_are_not_overwritten_when_the_list_cannot_be_read(settings, repo, monkeypatch):
    store = ProjectStore(settings.home)
    kept = [{"id": "antigo", "name": "antigo", "path": "/tmp/antigo"}]
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps(kept), encoding="utf-8")
    real_read = Path.read_text

    def no_free_files(self, *args, **kwargs):
        if self == store.path:
            raise OSError(errno.EMFILE, "Too many open files")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", no_free_files)
    assert store.list() == []  # a tela fica sem a lista, mas nada se perde
    with pytest.raises(ProjectError, match="nada foi gravado"):
        store.add(str(repo))
    with pytest.raises(ProjectError):
        store.remove("antigo")
    with pytest.raises(ProjectError):
        store.set_scripts("antigo", setup="make")
    monkeypatch.undo()
    assert json.loads(store.path.read_text(encoding="utf-8")) == kept
