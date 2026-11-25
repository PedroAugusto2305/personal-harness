"""v1.7.0: a barra de entrada da conversa com modelo e força, e a prévia dos anexos.

- modelo e força por conversa: a troca reabre a mesma conversa com as flags oficiais da CLI
  (`claude --resume --model --effort`, `codex resume -m -c model_reasoning_effort=`) e a escolha
  acompanha a sessão quando ela reinicia;
- a lista de modelos do Codex vem do models_cache.json da conta; a do Claude, dos apelidos;
- a prévia dos anexos (Pillow para imagem, QuickLook para vídeo, PDF e o resto) e os anexos que
  não são imagem aparecendo na sua mensagem da conversa.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from harness_core import app as app_mod
from harness_core import attachments, conversa, modelos
from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.statusline import parse_statusline

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


def waiting_argv(kind, settings):
    # Fica vivo com qualquer argumento que a MÊTIS acrescente (viram $0, $1… do sh).
    return ["/bin/sh", "-c", "exec sleep 300"]


CODEX_CACHE = {
    "fetched_at": "2026-11-24T10:00:00Z",
    "models": [
        {"slug": "gpt-escondido", "display_name": "Escondido", "visibility": "hide", "priority": 1,
         "default_reasoning_level": "medium", "supported_reasoning_levels": [{"effort": "medium"}]},
        {"slug": "gpt-terra", "display_name": "GPT-Terra", "visibility": "list", "priority": 4,
         "default_reasoning_level": "medium", "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}, {"effort": "high"}, {"effort": "max"}]},
        {"slug": "gpt-sol", "display_name": "GPT-Sol", "visibility": "list", "priority": 3,
         "default_reasoning_level": "low", "supported_reasoning_levels": [{"effort": "ultra"}, {"effort": "low"}, {"effort": "xhigh"}]},
        {"slug": "rm -rf /", "display_name": "Ruim", "visibility": "list", "priority": 2},
    ],
}  # fmt: skip


@pytest.fixture
def core(settings, accounts, monkeypatch, tmp_path):
    monkeypatch.setattr(sessions_mod, "resolve_argv", waiting_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    codex_home = tmp_path / "homes" / "codex"
    codex_home.mkdir(parents=True)
    (codex_home / "models_cache.json").write_text(json.dumps(CODEX_CACHE), encoding="utf-8")
    (codex_home / "config.toml").write_text('model = "gpt-sol"\nmodel_reasoning_effort = "low"\n', encoding="utf-8")
    app.state.cli_homes = {"claude": tmp_path / "homes" / "claude", "codex": codex_home}
    with TestClient(app) as client:
        yield client, app
        for session_id in list(app.state.manager.sessions):
            client.delete(f"/sessions/{session_id}", headers=AUTH)


def argv_of(app, session_id: str) -> list[str]:
    return app.state.manager.get(session_id).pty.argv


# --- statusline e catálogo ------------------------------------------------------------------------


def test_statusline_traz_a_forca_e_o_id_do_modelo(statusline_payload):
    parsed = parse_statusline({**statusline_payload, "effort": {"level": "xhigh"}})
    assert parsed["effort"] == "xhigh" and parsed["model_id"] == "claude-opus-5-5"
    assert parse_statusline(statusline_payload)["effort"] is None  # modelo sem força: não vem


def test_catalogo_do_codex_vem_do_cache_da_conta_na_ordem_dele(tmp_path):
    (tmp_path / "models_cache.json").write_text(json.dumps(CODEX_CACHE), encoding="utf-8")
    found = modelos.codex_models(tmp_path)
    assert [m["id"] for m in found] == ["gpt-sol", "gpt-terra"]  # escondido e nome ruim ficam de fora
    assert found[0]["esforcos"] == ["low", "xhigh", "ultra"] and found[0]["esforco_padrao"] == "low"
    assert found[1]["esforcos"] == ["low", "medium", "high", "max"]
    assert modelos.codex_models(tmp_path / "nada") == []
    (tmp_path / "config.toml").write_text('model = "gpt-antigo"\n', encoding="utf-8")
    data = modelos.catalog("codex", tmp_path)
    # O padrão do config que não está no cache aparece também, para a barra marcar o que vale.
    assert data["padrao"] == {"modelo": "gpt-antigo", "esforco": None}
    assert data["modelos"][-1]["id"] == "gpt-antigo"
    claude = modelos.catalog("claude")
    assert [m["id"] for m in claude["modelos"]] == ["fable", "opus", "sonnet", "haiku"]
    assert claude["esforcos"] == ["low", "medium", "high", "xhigh", "max"]


def test_validacao_do_pedido_da_barra():
    assert modelos.validate("claude", " opus ", "") == ("opus", None)
    assert modelos.validate("codex", "", "ultra") == (None, "ultra")
    for kind, model, effort in (("claude", None, "ultra"), ("codex", "rm -rf /", None), ("shell", None, None), ("claude", "a\nb", None)):
        with pytest.raises(modelos.AjusteError):
            modelos.validate(kind, model, effort)


def test_rota_de_modelos_da_sessao(core):
    client, app = core
    codex = client.post("/sessions", json={"kind": "codex"}, headers=AUTH).json()
    data = client.get(f"/sessions/{codex['id']}/modelos", headers=AUTH).json()
    assert data["cli"] == "codex" and [m["id"] for m in data["modelos"]] == ["gpt-sol", "gpt-terra"]
    assert data["padrao"] == {"modelo": "gpt-sol", "esforco": "low"}
    assert data["atual"] == {"modelo": None, "esforco": None}
    claude = client.post("/sessions", json={"kind": "claude", "model": "sonnet", "effort": "max"}, headers=AUTH).json()
    data = client.get(f"/sessions/{claude['id']}/modelos", headers=AUTH).json()
    assert data["atual"] == {"modelo": "sonnet", "esforco": "max"}
    shell = client.post("/sessions", json={"kind": "shell"}, headers=AUTH).json()
    assert client.get(f"/sessions/{shell['id']}/modelos", headers=AUTH).status_code == 400
    # Agente com modelo: o "padrão" da conversa é o do agente.
    agent = client.post("/agents", json={"name": "Revisor", "cli": "claude", "model": "haiku"}, headers=AUTH).json()
    own = client.post("/sessions", json={"kind": "claude", "agent": agent["id"]}, headers=AUTH).json()
    data = client.get(f"/sessions/{own['id']}/modelos", headers=AUTH).json()
    assert data["padrao"]["modelo"] == "haiku" and data["padrao"]["do_agente"] is True


# --- troca de modelo e força ----------------------------------------------------------------------


def test_claude_troca_reabrindo_a_mesma_conversa_com_as_flags(core, tmp_path):
    client, app = core
    manager = app.state.manager
    old = client.post("/sessions", json={"kind": "claude", "title": "Minha conversa"}, headers=AUTH).json()
    transcript = tmp_path / "abc12345-conversa.jsonl"
    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    manager.get(old["id"]).statusline = {"session_id": "abc12345-conversa", "transcript": str(transcript)}
    manager.get(old["id"]).status = "waiting"
    answer = client.post(f"/sessions/{old['id']}/ajustes", json={"modelo": "opus", "esforco": "xhigh"}, headers=AUTH)
    assert answer.status_code == 200, answer.text
    data = answer.json()
    new = data["sessao"]
    assert data["reabriu"] is True and new["id"] != old["id"]
    assert manager.get(old["id"]) is None  # a antiga fechou
    assert new["modelo"] == "opus" and new["esforco"] == "xhigh" and new["title"] == "Minha conversa"
    argv = argv_of(app, new["id"])
    assert argv[argv.index("--resume") + 1] == "abc12345-conversa"
    assert argv[argv.index("--model") + 1] == "opus" and argv[argv.index("--effort") + 1] == "xhigh"
    # O mesmo pedido de novo não reabre nada.
    again = client.post(f"/sessions/{new['id']}/ajustes", json={"modelo": "opus", "esforco": "xhigh"}, headers=AUTH).json()
    assert again["reabriu"] is False and again["sessao"]["id"] == new["id"]
    # Voltar ao padrão: sem as flags.
    manager.get(new["id"]).status = "waiting"
    back = client.post(f"/sessions/{new['id']}/ajustes", json={"modelo": "", "esforco": ""}, headers=AUTH).json()["sessao"]
    argv = argv_of(app, back["id"])
    assert "--model" not in argv and "--effort" not in argv and back["modelo"] is None


def test_claude_sem_conversa_ainda_reabre_do_zero(core, tmp_path):
    client, app = core
    old = client.post("/sessions", json={"kind": "claude"}, headers=AUTH).json()  # "starting", sem statusline
    new = client.post(f"/sessions/{old['id']}/ajustes", json={"esforco": "low"}, headers=AUTH).json()["sessao"]
    argv = argv_of(app, new["id"])
    assert "--resume" not in argv and argv[argv.index("--effort") + 1] == "low"
    # A statusline traz o id antes da primeira mensagem, sem a conversa no disco: reabre do zero
    # (retomar um id sem conversa fazia o Claude sair com código 1).
    app.state.manager.get(new["id"]).statusline = {"session_id": "sem-conversa-ainda", "transcript": str(tmp_path / "nada.jsonl")}
    again = client.post(f"/sessions/{new['id']}/ajustes", json={"modelo": "haiku"}, headers=AUTH).json()["sessao"]
    assert "--resume" not in argv_of(app, again["id"])
    # E o "Continuar a conversa" dessa sessão diz que não há conversa, em vez de abrir e sair.
    assert client.post(f"/sessions/{again['id']}/reiniciar", json={"continuar": True}, headers=AUTH).status_code == 409


def test_codex_troca_com_resume_m_e_model_reasoning_effort(core, monkeypatch):
    client, app = core
    monkeypatch.setattr(app_mod, "codex_rollout_for", lambda *a, **k: {"id": "019a-conversa-codex", "arquivo": "/tmp/x.jsonl"})
    old = client.post("/sessions", json={"kind": "codex"}, headers=AUTH).json()
    new = client.post(f"/sessions/{old['id']}/ajustes", json={"modelo": "gpt-terra", "esforco": "max"}, headers=AUTH).json()["sessao"]
    argv = argv_of(app, new["id"])
    assert argv[1:3] == ["resume", "019a-conversa-codex"]
    assert argv[argv.index("-m") + 1] == "gpt-terra"
    assert argv[argv.index('model_reasoning_effort="max"') - 1] == "-c"
    assert argv[argv.index("check_for_update_on_startup=false") - 1] == "-c"  # sem o aviso de atualização
    assert new["modelo"] == "gpt-terra" and new["esforco"] == "max"


def test_troca_recusada_com_o_agente_ocupado_ou_pedido_ruim(core):
    client, app = core
    manager = app.state.manager
    session = client.post("/sessions", json={"kind": "claude"}, headers=AUTH).json()
    manager.get(session["id"]).status = "working"
    busy = client.post(f"/sessions/{session['id']}/ajustes", json={"modelo": "opus"}, headers=AUTH)
    assert busy.status_code == 409 and "trabalhando" in busy.json()["detail"]
    manager.get(session["id"]).status = "waiting"
    manager.get(session["id"]).atencao = "pergunta"
    asking = client.post(f"/sessions/{session['id']}/ajustes", json={"modelo": "opus"}, headers=AUTH)
    assert asking.status_code == 409 and "responda" in asking.json()["detail"]
    manager.get(session["id"]).atencao = None
    assert client.post(f"/sessions/{session['id']}/ajustes", json={"esforco": "ultra"}, headers=AUTH).status_code == 400
    assert client.post(f"/sessions/{session['id']}/ajustes", json={"modelo": "opus; rm"}, headers=AUTH).status_code == 400
    assert client.post("/sessions/naoexiste/ajustes", json={"modelo": "opus"}, headers=AUTH).status_code == 404
    assert manager.get(session["id"]) is not None  # nada foi fechado


def test_escolha_acompanha_o_reiniciar_mas_nao_passa_para_a_outra_cli(core):
    client, app = core
    manager = app.state.manager
    first = client.post("/sessions", json={"kind": "claude", "model": "sonnet", "effort": "high", "permissao": "auto"}, headers=AUTH).json()
    restarted = client.post(f"/sessions/{first['id']}/reiniciar", json={"continuar": False}, headers=AUTH).json()
    argv = argv_of(app, restarted["id"])
    assert argv[argv.index("--model") + 1] == "sonnet" and argv[argv.index("--effort") + 1] == "high"
    # O modo de permissão pedido na abertura (o "auto" do kanban) também vai junto.
    assert argv[argv.index("--permission-mode") + 1] == "auto"
    assert restarted["modelo"] == "sonnet" and restarted["esforco"] == "high"
    manager.get(restarted["id"]).status = "waiting"
    swapped = client.post(f"/sessions/{restarted['id']}/ajustes", json={"modelo": "opus", "esforco": "high"}, headers=AUTH).json()["sessao"]
    argv = argv_of(app, swapped["id"])
    assert argv[argv.index("--permission-mode") + 1] == "auto" and argv[argv.index("--model") + 1] == "opus"
    restarted = swapped
    manager.get(restarted["id"]).status = "waiting"
    other = client.post(f"/sessions/{restarted['id']}/passar", json={"para": "codex"}, headers=AUTH).json()
    argv = argv_of(app, other["id"])
    assert "-m" not in argv and not any("model_reasoning_effort" in a for a in argv)
    assert other["modelo"] is None and other["esforco"] is None


# --- prévia dos anexos ------------------------------------------------------------------------------


def png_bytes(size=(640, 360), color=(200, 30, 60)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def test_upload_devolve_nome_tamanho_e_tipo(core, settings):
    client, _ = core
    data = png_bytes()
    answer = client.post("/attachments?name=print%20da%20tela.png", content=data, headers=AUTH).json()
    assert answer["path"] == answer["caminho"] and answer["path"].startswith(str(settings.home / "anexos"))
    assert answer["tipo"] == "imagem" and answer["tamanho"] == len(data) and answer["nome"].endswith("print-da-tela.png")
    info = client.get("/anexos/info", params={"caminho": answer["path"]}, headers=AUTH).json()
    assert info == {k: answer[k] for k in ("caminho", "nome", "tamanho", "tipo")}
    assert client.get("/anexos/info", params={"caminho": "relativo.png"}, headers=AUTH).status_code == 404
    assert client.get("/anexos/info", params={"caminho": str(settings.home)}, headers=AUTH).status_code == 404  # pasta não


def test_miniatura_da_imagem_sai_do_pillow_e_fica_guardada(core, settings, tmp_path, monkeypatch):
    client, _ = core
    image = tmp_path / "foto.png"
    image.write_bytes(png_bytes((1200, 600)))
    calls: list[list[str]] = []
    monkeypatch.setattr(attachments, "_run", lambda argv, **kw: calls.append(argv))
    answer = client.get("/anexos/miniatura", params={"caminho": str(image), "tamanho": 200, "token": TOKEN})
    assert answer.status_code == 200 and answer.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(answer.content)) as thumb:
        assert max(thumb.size) == 192  # o tamanho pedido vai para o mais perto da lista
    assert calls == []  # imagem comum não chama o QuickLook
    assert len(list((settings.home / "cache" / "miniaturas").glob("*.png"))) == 1
    assert client.get("/anexos/miniatura", params={"caminho": str(image)}).status_code == 401  # sem token


def test_miniatura_do_video_e_do_pdf_sai_do_quicklook(core, tmp_path, monkeypatch):
    client, _ = core
    video = tmp_path / "gravação da tela.mov"
    video.write_bytes(b"\x00\x00\x00\x14ftypqt  " + b"0" * 64)
    seen: list[list[str]] = []

    def fake_qlmanage(argv, **kw):
        seen.append(argv)
        out = Path(argv[argv.index("-o") + 1])
        (out / (Path(argv[-1]).name + ".png")).write_bytes(png_bytes((256, 144), (10, 10, 10)))

    monkeypatch.setattr(attachments, "_run", fake_qlmanage)
    answer = client.get("/anexos/miniatura", params={"caminho": str(video)}, headers=AUTH)
    assert answer.status_code == 200 and answer.content.startswith(b"\x89PNG")
    assert seen[0][:4] == ["/usr/bin/qlmanage", "-t", "-s", "192"] and seen[0][-1] == str(video)
    # O QuickLook que não desenha nada: 404, e a barra mostra ícone, nome e tamanho.
    monkeypatch.setattr(attachments, "_run", lambda argv, **kw: None)
    other = tmp_path / "dados.bin"
    other.write_bytes(b"\x01\x02")
    assert client.get("/anexos/miniatura", params={"caminho": str(other)}, headers=AUTH).status_code == 404
    empty = tmp_path / "vazio.pdf"
    empty.write_bytes(b"")
    assert client.get("/anexos/miniatura", params={"caminho": str(empty)}, headers=AUTH).status_code == 404


def test_arquivo_inteiro_so_para_imagem_video_e_audio_com_pedido_por_partes(core, tmp_path):
    client, _ = core
    video = tmp_path / "clip.mp4"
    video.write_bytes(bytes(range(256)) * 8)
    whole = client.get("/anexos/arquivo", params={"caminho": str(video), "token": TOKEN})
    assert whole.status_code == 200 and whole.headers["content-type"] == "video/mp4"
    part = client.get("/anexos/arquivo", params={"caminho": str(video), "token": TOKEN}, headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100  # o player do WebKit pede por partes
    text = tmp_path / "segredo.txt"
    text.write_text("não sai", encoding="utf-8")
    assert client.get("/anexos/arquivo", params={"caminho": str(text), "token": TOKEN}).status_code == 415


def test_tipos_dos_anexos():
    assert [attachments.kind_of(n) for n in ("a.HEIC", "b.mov", "c.m4a", "d.pdf", "e.xlsx", "f.key", "g.docx", "h.zip", "i.py", "j")] == [
        "imagem", "video", "audio", "pdf", "planilha", "apresentacao", "documento", "compactado", "codigo", "arquivo"]  # fmt: skip


# --- a mensagem enviada com os anexos --------------------------------------------------------------


def test_mensagem_enviada_traz_os_anexos_que_nao_sao_imagem(tmp_path):
    root = tmp_path / "Harness" / "anexos" / "2026-11-24"
    root.mkdir(parents=True)
    conversa.set_attachments_root(tmp_path / "Harness" / "anexos")
    try:
        video = root / "ab12cd34-tela.mov"
        video.write_bytes(b"v" * 10)
        notes = root / "ef56-notas.py"  # código: só vira anexo por estar na pasta de anexos
        notes.write_text("print(1)\n", encoding="utf-8")
        finder = tmp_path / "Meus Documentos" / "contrato final.pdf"
        finder.parent.mkdir()
        finder.write_bytes(b"%PDF-1.4")
        loose = tmp_path / "repo" / "app.py"  # código fora dos anexos: continua só texto
        loose.parent.mkdir()
        loose.write_text("x = 1\n", encoding="utf-8")
        blob = tmp_path / "dados.bin"  # tipo desconhecido arrastado do Finder: anexo também
        blob.write_bytes(b"\x00")
        text = f"compare {video} e '{finder}' com {notes}, sem mexer em {loose} nem em /nao/existe.pdf {blob}"
        found = conversa.files_in_text(text, str(tmp_path))
        assert [f["arquivo"] for f in found] == [str(finder), str(video), str(notes), str(blob)]
        assert [f["tipo"] for f in found] == ["pdf", "video", "codigo", "arquivo"]
        assert found[0]["nome"] == "contrato final.pdf" and found[1]["tamanho"] == 10

        path = tmp_path / "claude.jsonl"
        path.write_text(json.dumps({"type": "user", "uuid": "u1", "cwd": str(tmp_path), "message": {"content": text}}) + "\n", encoding="utf-8")
        you = [i for i in conversa.read(str(path), "claude").items if i["tipo"] == "voce"]
        # O prefixo de 8 letras que a barra põe ao guardar sai do nome mostrado.
        assert [a["nome"] for a in you[0]["anexos"]] == ["contrato final.pdf", "tela.mov", "ef56-notas.py", "dados.bin"]
    finally:
        conversa.set_attachments_root(None)


def test_colagem_longa_do_claude_aparece_como_sua_mensagem(tmp_path):
    """O Claude grava a colagem longa embrulhada em <pasted_content>: era lida como aviso e sumia."""
    root = tmp_path / "Harness" / "anexos" / "2026-11-24"
    root.mkdir(parents=True)
    conversa.set_attachments_root(tmp_path / "Harness" / "anexos")
    try:
        video = root / "ae56f8e2-gravação-da-tela.mp4"
        video.write_bytes(b"v")
        pasted = f"Em uma linha: os nomes dos anexos. '{video}'"
        path = tmp_path / "claude.jsonl"
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in [
            {"type": "user", "uuid": "u1", "cwd": str(tmp_path), "message": {"content": f'\n\n<pasted_content id="2b6d">\n{pasted}\n</pasted_content id="2b6d">\n'}},
            {"type": "user", "uuid": "u2", "cwd": str(tmp_path), "message": {"content": f'olha isto\n\n<pasted_content id="9f">\nlinha colada\n</pasted_content id="9f">'}},
            {"type": "attachment", "uuid": "q1", "attachment": {"type": "queued_command", "prompt": f'<pasted_content id="1">\nna fila {video}\n</pasted_content id="1">'}},
        ]) + "\n", encoding="utf-8")  # fmt: skip
        you = [i for i in conversa.read(str(path), "claude").items if i["tipo"] == "voce"]
        assert [i["texto"] for i in you] == [pasted, "olha isto\n\nlinha colada", f"na fila {video}"]
        assert [a["nome"] for a in you[0]["anexos"]] == ["gravação-da-tela.mp4"] and you[2]["anexos"][0]["tipo"] == "video"
    finally:
        conversa.set_attachments_root(None)
