"""v1.2.0: a conversa do Claude e do Codex desenhada a partir do transcript.

O terminal continua por baixo; a tela lê o JSONL da CLI e mostra mensagens, ferramentas,
imagens (coladas, devolvidas por ferramenta, geradas em arquivo), plano e marcos.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import conversa
from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.prefs import Prefs, PrefsError

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


def write_lines(path: Path, entries: list[dict], mode: str = "w") -> None:
    with open(path, mode, encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def by_type(items: list[dict], kind: str) -> list[dict]:
    return [i for i in items if i["tipo"] == kind]


@pytest.fixture
def claude_transcript(tmp_path: Path) -> tuple[Path, Path]:
    cwd = tmp_path / "repo"
    (cwd / "saida").mkdir(parents=True)
    (cwd / "saida" / "logo.png").write_bytes(b"png")
    path = tmp_path / "claude.jsonl"
    write_lines(path, [
        {"type": "api-request", "uuid": "x0"},
        {"type": "user", "uuid": "u1", "cwd": str(cwd), "timestamp": "2026-11-12T10:00:00Z",
         "message": {"content": [{"type": "text", "text": "[Image #1] olha esse print"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}]}},
        {"type": "user", "uuid": "u2", "isMeta": True, "message": {"content": "instruções da skill"}},
        {"type": "user", "uuid": "u3", "message": {"content": "<system-reminder>lembrete</system-reminder>"}},
        {"type": "assistant", "uuid": "a1", "message": {"content": [
            {"type": "thinking", "thinking": "Vou desenhar o fluxo."},
            {"type": "text", "text": "Fluxo:\n\n```mermaid\nflowchart LR\n  A-->B\n```\n\nSalvei a logo em `saida/logo.png`."},
            {"type": "tool_use", "id": "t-bash", "name": "Bash", "input": {"command": "ls saida", "description": "Lista a pasta"}},
            {"type": "tool_use", "id": "t-edit", "name": "Edit", "input": {"file_path": str(cwd / "app.py"), "old_string": "a = 1", "new_string": "a = 2"}},
            {"type": "tool_use", "id": "t-write", "name": "Write", "input": {"file_path": str(cwd / "saida" / "grafico.svg"), "content": "<svg/>"}},
            {"type": "tool_use", "id": "t-read", "name": "Read", "input": {"file_path": str(cwd / "saida" / "logo.png")}},
            {"type": "tool_use", "id": "t-todo", "name": "TodoWrite", "input": {"todos": [{"content": "Ler", "status": "completed"}, {"content": "Escrever", "status": "in_progress"}]}},
        ]}},
        {"type": "assistant", "uuid": "a1", "message": {"content": [{"type": "text", "text": "linha repetida"}]}},
        {"type": "assistant", "uuid": "side", "isSidechain": True, "message": {"content": [{"type": "text", "text": "subagente"}]}},
        {"type": "user", "uuid": "r1", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t-bash", "content": "logo.png\n"},
            {"type": "tool_result", "tool_use_id": "t-edit", "content": "erro: não achei", "is_error": True},
            {"type": "tool_result", "tool_use_id": "t-write", "content": "ok"},
            {"type": "tool_result", "tool_use_id": "t-read", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": PNG}}]},
            {"type": "tool_result", "tool_use_id": "t-todo", "content": "Todos have been modified"},
        ]}},
        {"type": "user", "uuid": "c1", "message": {"content": "<command-name>/model</command-name>\n<command-message>model</command-message>\n<command-args>opus</command-args>"}},
        {"type": "user", "uuid": "i1", "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}},
        {"type": "system", "uuid": "s1", "subtype": "turn_duration", "durationMs": 95_000},
        {"type": "system", "uuid": "s2", "subtype": "compact_boundary", "compactMetadata": {"trigger": "auto"}},
    ])  # fmt: skip
    return path, cwd


def test_claude_vira_mensagens_ferramentas_imagens_e_marcos(claude_transcript):
    path, cwd = claude_transcript
    state = conversa.read(str(path), "claude")
    items = state.items
    you = by_type(items, "voce")
    assert len(you) == 1 and you[0]["texto"] == "[Image #1] olha esse print"
    assert you[0]["imagens"][0]["ref"].endswith(":message.content.1")  # o print colado, por referência
    agent = by_type(items, "agente")
    assert len(agent) == 1 and "```mermaid" in agent[0]["texto"]  # a linha repetida (mesmo uuid) e o subagente ficam de fora
    assert agent[0]["imagens"] == [{"arquivo": str(cwd / "saida" / "logo.png"), "nome": "logo.png"}]  # caminho citado que existe
    assert by_type(items, "pensamento")[0]["texto"] == "Vou desenhar o fluxo."
    tools = {i["id"]: i for i in by_type(items, "ferramenta")}
    assert tools["t-bash"]["rotulo"] == "Lista a pasta" and tools["t-bash"]["saida"] == "logo.png\n" and tools["t-bash"]["estado"] == "ok"
    assert tools["t-edit"]["diff"] == [{"antes": "a = 1", "depois": "a = 2"}] and tools["t-edit"]["estado"] == "erro"
    assert tools["t-edit"]["rotulo"] == "Editou app.py"  # caminho curto, relativo à pasta da sessão
    assert tools["t-write"]["imagens"][0]["arquivo"].endswith("grafico.svg")  # imagem gerada em arquivo
    assert tools["t-read"]["imagens"][0]["ref"].endswith(":message.content.3.content.0")
    plan = by_type(items, "plano")[0]
    assert plan["passos"] == [{"texto": "Ler", "estado": "feito"}, {"texto": "Escrever", "estado": "andamento"}]
    events = [i["texto"] for i in by_type(items, "evento")]
    assert events == ["/model opus", "Interrompido por você", "Trabalhou por 1m 35s", "Conversa compactada automaticamente"]
    assert [i["n"] for i in items] == list(range(len(items)))


def test_imagem_do_transcript_sai_pela_referencia(claude_transcript):
    path, _cwd = claude_transcript
    state = conversa.read(str(path), "claude")
    pasted = by_type(state.items, "voce")[0]["imagens"][0]["ref"]
    data, media = conversa.imagem(str(path), pasted)
    assert media == "image/png" and data.startswith(b"\x89PNG")
    tool = next(i for i in state.items if i.get("id") == "t-read")["imagens"][0]["ref"]
    assert conversa.imagem(str(path), tool)[1] == "image/jpeg"
    assert conversa.imagem(str(path), "0:message.content.9") is None  # linha sem esse bloco
    assert conversa.imagem(str(path), "abc") is None


def test_leitura_incremental_so_devolve_o_que_mudou(tmp_path):
    path = tmp_path / "c.jsonl"
    write_lines(path, [
        {"type": "user", "uuid": "u1", "message": {"content": "roda os testes"}},
        {"type": "assistant", "uuid": "a1", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest"}}]}},
    ])  # fmt: skip
    first = conversa.page(conversa.read(str(path), "claude"))
    assert first["reset"] and [i["tipo"] for i in first["itens"]] == ["voce", "ferramenta"]
    assert first["itens"][1]["estado"] == "rodando"
    # O resultado chega, e a linha seguinte ainda está pela metade (sem \n): fica para depois.
    write_lines(path, [{"type": "user", "uuid": "r1", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "3 passed"}]}}], "a")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"type": "assistant", "uuid": "a2", "message": {"content": [{"type": "text", "text": "Tudo')
    second = conversa.page(conversa.read(str(path), "claude"), first["fonte"], first["seq"])
    assert not second["reset"] and [(i["n"], i["estado"]) for i in second["itens"]] == [(1, "ok")]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(' passou."}]}}\n')
    third = conversa.page(conversa.read(str(path), "claude"), second["fonte"], second["seq"])
    assert [(i["n"], i["texto"]) for i in third["itens"]] == [(2, "Tudo passou.")]
    assert conversa.page(conversa.read(str(path), "claude"), third["fonte"], third["seq"])["itens"] == []
    # Rolar para cima: as anteriores a um item.
    older = conversa.page(conversa.read(str(path), "claude"), antes=2, limite=1)
    assert older["inicio"] == 1 and [i["n"] for i in older["itens"]] == [1]


def test_transcript_trocado_comeca_de_novo(tmp_path):
    path = tmp_path / "c.jsonl"
    write_lines(path, [{"type": "user", "uuid": "u1", "message": {"content": "primeira"}}])
    first = conversa.page(conversa.read(str(path), "claude"))
    path.unlink()
    write_lines(path, [{"type": "user", "uuid": "u9", "message": {"content": "outra conversa"}}, {"type": "user", "uuid": "u10", "message": {"content": "segunda"}}])
    again = conversa.page(conversa.read(str(path), "claude"), first["fonte"], first["seq"])
    assert again["reset"] and again["fonte"] != first["fonte"]
    assert [i["texto"] for i in again["itens"]] == ["outra conversa", "segunda"]


def test_codex_com_itens_prontos(tmp_path):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    path = tmp_path / "rollout.jsonl"
    data_url = f"data:image/png;base64,{PNG}"
    write_lines(path, [
        {"type": "session_meta", "payload": {"id": "th-1", "cwd": str(cwd)}},
        {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "<skills_instructions>…"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>…</environment_context>"}]}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "id": "um1", "content": [{"type": "text", "text": "x"}]}}},
        {"type": "response_item", "payload": {"type": "message", "id": "m1", "role": "user", "content": [
            {"type": "input_text", "text": "faz a tela igual"}, {"type": "input_text", "text": "<image name=[Image #1]>"},
            {"type": "input_image", "image_url": data_url}, {"type": "input_text", "text": "</image>"}]}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "c1", "name": "exec", "input": "const r = await tools.exec_command({cmd: 'cat a'})"}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "CommandExecution", "id": "e1", "command": ["/bin/zsh", "-lc", "sed -n 1,10p README.md"],
            "parsed_cmd": [{"type": "read", "name": "README.md", "path": "README.md"}], "aggregated_output": "# Projeto", "exit_code": 0, "status": "completed"}}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "CommandExecution", "id": "e2", "command": ["/bin/zsh", "-lc", "npm test"],
            "parsed_cmd": [{"type": "unknown", "cmd": "npm test"}], "aggregated_output": "1 failed", "exit_code": 1, "status": "completed"}}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "FileChange", "id": "f1", "changes": {str(cwd / "a.ts"): {"type": "update", "unified_diff": "-a\n+b"}}, "status": "completed"}}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "ImageView", "id": "v1", "path": str(cwd / "tela.png")}}},
        {"type": "response_item", "payload": {"type": "function_call", "call_id": "p1", "name": "update_plan", "arguments": json.dumps({"plan": [{"step": "Ler", "status": "completed"}, {"step": "Fazer", "status": "pending"}]})}},
        {"type": "response_item", "payload": {"type": "image_generation_call", "id": "ig1", "result": PNG, "revised_prompt": "um logo"}},
        {"type": "response_item", "payload": {"type": "message", "id": "m2", "role": "assistant", "content": [{"type": "output_text", "text": "Pronto."}]}},
        {"type": "event_msg", "payload": {"type": "task_complete", "duration_ms": 2500}},
    ])  # fmt: skip
    state = conversa.read(str(path), "codex")
    kinds = [(i["tipo"], i.get("categoria") or i.get("evento") or "") for i in state.items]
    assert kinds == [
        ("voce", ""), ("ferramenta", "leitura"), ("ferramenta", "comando"), ("ferramenta", "edicao"), ("ferramenta", "imagem"),
        ("plano", ""), ("ferramenta", "imagem"), ("agente", ""), ("evento", "duracao"),
    ]  # fmt: skip
    you = state.items[0]
    assert you["texto"] == "faz a tela igual" and you["imagens"][0]["ref"].endswith(":payload.content.2")
    assert conversa.imagem(str(path), you["imagens"][0]["ref"])[1] == "image/png"
    read, test = state.items[1], state.items[2]
    assert read["rotulo"] == "Leu README.md" and test["estado"] == "erro" and test["detalhe"] == "npm test"
    assert state.items[3]["rotulo"] == "Editou a.ts" and "+b" in state.items[3]["patch"]
    assert state.items[4]["imagens"][0]["arquivo"] == str(cwd / "tela.png")
    generated = state.items[6]["imagens"][0]
    assert conversa.imagem(str(path), generated["ref"])[0].startswith(b"\x89PNG")
    assert state.items[8]["texto"] == "Trabalhou por 3s"


def test_codex_antigo_usa_as_chamadas_do_modelo(tmp_path):
    path = tmp_path / "rollout.jsonl"
    write_lines(path, [
        {"type": "session_meta", "payload": {"id": "th-2", "cwd": str(tmp_path)}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "lista"}]}},
        {"type": "response_item", "payload": {"type": "function_call", "call_id": "s1", "name": "shell", "arguments": json.dumps({"command": ["bash", "-lc", "ls"]})}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "s1", "output": json.dumps({"output": "a b"})}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "ap", "name": "apply_patch", "input": "*** Begin Patch\n*** Update File: src/a.ts\n-a\n+b\n*** End Patch"}},
    ])  # fmt: skip
    state = conversa.read(str(path), "codex")
    shell = state.get("s1")
    assert shell["categoria"] == "comando" and shell["detalhe"] == "ls" and shell["estado"] == "ok" and "a b" in shell["saida"]
    assert state.get("ap")["rotulo"] == "Editou src/a.ts"


def test_imagens_citadas_so_quando_existem(tmp_path):
    (tmp_path / "pasta com espaço").mkdir()
    real = tmp_path / "pasta com espaço" / "print.png"
    real.write_bytes(b"x")
    text = f"Anexo: '{real}' e `~/nao/existe.png`, mais ![logo](logo.png) e só nome.png"
    (tmp_path / "logo.png").write_bytes(b"x")
    found = conversa.images_in_text(text, str(tmp_path))
    assert found == [{"arquivo": str(real), "nome": "print.png"}]  # a do ![](…) já aparece no Markdown


def test_prefs_vista_do_agente(tmp_path):
    prefs = Prefs(tmp_path)
    assert prefs.get()["vista_agente"] == "conversa"
    assert prefs.update({"vista_agente": "terminal"})["vista_agente"] == "terminal"
    with pytest.raises(PrefsError):
        prefs.update({"vista_agente": "janela"})


def fake_argv(kind, settings):
    return {"claude": ["/bin/cat", "--claude"], "codex": ["/bin/cat", "--codex"]}.get(kind, ["/bin/cat"])


@pytest.fixture
def core(settings, accounts, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client, app


def test_rotas_da_conversa(core, claude_transcript, tmp_path):
    client, app = core
    path, cwd = claude_transcript
    session = client.post("/sessions", json={"kind": "claude", "cwd": str(cwd)}, headers=AUTH).json()
    url = f"/sessions/{session['id']}/conversa/itens"
    waiting = client.get(url, headers=AUTH).json()
    assert waiting["disponivel"] is False and waiting["itens"] == []  # sem statusline ainda
    app.state.manager.record_statusline(session["id"], {"session_id": "conv-1", "transcript_path": str(path)})
    answer = client.get(url, headers=AUTH).json()
    assert answer["disponivel"] and answer["cli"] == "claude" and answer["cwd"] == str(cwd)
    assert answer["total"] == len(answer["itens"]) and answer["itens"][0]["tipo"] == "voce"
    again = client.get(url, params={"fonte": answer["fonte"], "apos": answer["seq"]}, headers=AUTH).json()
    assert again["itens"] == [] and not again["reset"]
    # A imagem colada sai pela referência, com o token na URL (é um <img src>).
    ref = answer["itens"][0]["imagens"][0]["ref"]
    image = client.get("/conversa/imagem", params={"fonte": answer["fonte"], "ref": ref, "token": TOKEN})
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert client.get("/conversa/imagem", params={"fonte": answer["fonte"], "ref": ref}).status_code == 401
    other = tmp_path / "outro.jsonl"
    other.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    assert client.get("/conversa/imagem", params={"fonte": str(other), "ref": ref, "token": TOKEN}).status_code == 404  # transcript não aberto
    # Imagem no disco: só imagem.
    logo = client.get("/conversa/arquivo", params={"caminho": str(cwd / "saida" / "logo.png"), "token": TOKEN})
    assert logo.status_code == 200 and logo.headers["content-type"] == "image/png"
    (cwd / "segredo.txt").write_text("x", encoding="utf-8")
    assert client.get("/conversa/arquivo", params={"caminho": str(cwd / "segredo.txt"), "token": TOKEN}).status_code == 404
    assert client.get("/conversa/arquivo", params={"caminho": "saida/logo.png", "token": TOKEN}).status_code == 404  # só caminho absoluto
    shell = client.post("/sessions", json={"kind": "shell", "cwd": str(cwd)}, headers=AUTH).json()
    assert client.get(f"/sessions/{shell['id']}/conversa/itens", headers=AUTH).status_code == 400
    assert client.put("/ajustes", json={"vista_agente": "terminal"}, headers=AUTH).json()["vista_agente"] == "terminal"
    for sid in (session["id"], shell["id"]):
        client.delete(f"/sessions/{sid}", headers=AUTH)
    assert not os.path.exists(str(cwd / "nada"))


def test_rollout_do_codex_com_instrucoes_grandes_no_comeco_e_achado(tmp_path):
    """No Codex 0.154 a primeira mensagem vem depois de ~90 KB de instruções (skills, AGENTS.md):
    com só os 64 KB do começo, a conversa não era achada e a tela ficava vazia."""
    from harness_core.history import codex_rollout_for, list_sessions

    home = tmp_path / "codex"
    folder = home / "sessions" / "2026" / "11" / "12"
    folder.mkdir(parents=True)
    cwd = str(tmp_path / "repo")
    write_lines(folder / "rollout-2026-11-12T09-40-20-th-9.jsonl", [
        {"type": "session_meta", "payload": {"id": "th-9", "cwd": cwd, "timestamp": "2026-11-12T12:40:20Z", "source": "cli"}},
        {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "<skills_instructions>" + "x" * 90_000}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>…</environment_context>"}]}},
        {"type": "world_state", "payload": {"state": {"agents_md": {"text": "y" * 30_000}}}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "roda os testes do núcleo"}]}},
    ])  # fmt: skip
    write_lines(folder / "rollout-2026-11-12T09-40-21-guardiao.jsonl", [
        {"type": "session_meta", "payload": {"id": "guardiao", "cwd": cwd, "source": {"subagent": {"other": "guardian"}}}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "revise a ação"}]}},
    ])  # fmt: skip
    defaults = {"claude": tmp_path / "claude", "codex": home}
    found = list_sessions({}, cwd=cwd, defaults=defaults)
    assert [(i["id"], i["titulo"]) for i in found] == [("th-9", "roda os testes do núcleo")]  # o guardião fica de fora
    assert codex_rollout_for({}, cwd, 0, defaults)["id"] == "th-9"


def test_codex_retomado_mostra_a_conversa_antiga_antes_do_primeiro_turno(core, tmp_path):
    """Retomar pelo histórico (`codex resume <id>`): a conversa é a de antes, e o arquivo dela é
    mais velho que a sessão nova. Antes, ela só aparecia depois de o Codex fechar um turno."""
    client, app = core
    home = tmp_path / "codex"
    folder = home / "sessions" / "2026" / "11" / "11"
    folder.mkdir(parents=True)
    cwd = tmp_path / "repo"
    cwd.mkdir()
    rollout = folder / "rollout-2026-11-11T10-00-00-th-antiga.jsonl"
    write_lines(rollout, [
        {"type": "session_meta", "payload": {"id": "th-antiga", "cwd": str(cwd)}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "faz o login"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Feito."}]}},
    ])  # fmt: skip
    os.utime(rollout, (1_700_000_000, 1_700_000_000))  # bem antes da sessão nova
    app.state.cli_homes = {"claude": tmp_path / "claude", "codex": home}
    session = client.post("/sessions", json={"kind": "codex", "cwd": str(cwd), "resume": "th-antiga"}, headers=AUTH).json()
    assert app.state.manager.get(session["id"]).conversa == "th-antiga"
    answer = client.get(f"/sessions/{session['id']}/conversa/itens", headers=AUTH).json()
    assert answer["disponivel"] and [i["texto"] for i in answer["itens"]] == ["faz o login", "Feito."]
    fresh = client.post("/sessions", json={"kind": "codex", "cwd": str(cwd)}, headers=AUTH).json()
    assert client.get(f"/sessions/{fresh['id']}/conversa/itens", headers=AUTH).json()["disponivel"] is False  # sessão nova não pega a antiga
    for sid in (session["id"], fresh["id"]):
        client.delete(f"/sessions/{sid}", headers=AUTH)
