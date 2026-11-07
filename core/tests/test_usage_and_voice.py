import io
import sys
import wave

import pytest
from fastapi.testclient import TestClient

from harness_core.app import create_app
from harness_core.codex_usage import parse_codex_limits, read_codex_limits
from harness_core.voice import AudioFormatError, Transcriber, wav_to_float32

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}

# Resposta real do `codex app-server` (account/rateLimits/read), sem dados da conta.
CODEX_RESULT = {
    "rateLimits": {
        "limitId": "codex",
        "primary": {"usedPercent": 12, "windowDurationMins": 300, "resetsAt": 1794080000},
        "secondary": {"usedPercent": 57, "windowDurationMins": 10080, "resetsAt": 1794400000},
        "planType": "plus",
    }
}


def make_wav(seconds: float, rate: int = 16000, channels: int = 1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x10" * int(seconds * rate) * channels)
    return buffer.getvalue()


class FakeTranscriber(Transcriber):
    """Transcritor sem modelo: exercita leitura do WAV, carga preguiçosa e a API."""

    def __init__(self, home):
        super().__init__(home, model_name="falso")
        self.loads = 0
        self.heard: list[int] = []

    def _load(self):
        self.loads += 1
        return object()

    def _run(self, audio, language):
        self.heard.append(len(audio))
        return f"texto em {language}"


# --- cota do Codex ---------------------------------------------------------


def test_parse_codex_limits_maps_windows_by_duration():
    assert parse_codex_limits(CODEX_RESULT) == {
        "five_hour": {"used_pct": 12.0, "resets_at": 1794080000},
        "seven_day": {"used_pct": 57.0, "resets_at": 1794400000},
        "plan": "plus",
    }


def test_parse_codex_limits_tolerates_missing_or_odd_fields():
    assert parse_codex_limits({}) == {}
    swapped = {"rateLimits": {"primary": {"usedPercent": 5, "windowDurationMins": 10080}}}
    assert parse_codex_limits(swapped) == {"seven_day": {"used_pct": 5.0, "resets_at": None}}
    assert parse_codex_limits({"rateLimits": {"primary": {"usedPercent": True}}}) == {}


FAKE_APP_SERVER = r"""
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        print(json.dumps({"method": "log", "params": {}}), flush=True)
        print(json.dumps({"id": msg["id"], "result": {"userAgent": "x"}}), flush=True)
    elif msg.get("method") == "account/rateLimits/read":
        print("lixo que nao e json", flush=True)
        print(json.dumps({"id": msg["id"], "result": RESULT}), flush=True)
"""


@pytest.mark.anyio
async def test_read_codex_limits_speaks_json_rpc(tmp_path):
    script = tmp_path / "codex"
    script.write_text(f"#!{sys.executable}\nRESULT = {CODEX_RESULT!r}\n{FAKE_APP_SERVER}", encoding="utf-8")
    script.chmod(0o755)
    limits = await read_codex_limits(str(script), {"PATH": "/usr/bin:/bin"}, timeout=10)
    assert limits["five_hour"]["used_pct"] == 12.0 and limits["plan"] == "plus"


@pytest.mark.anyio
async def test_read_codex_limits_gives_up_quietly(tmp_path):
    script = tmp_path / "codex"
    script.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    script.chmod(0o755)
    assert await read_codex_limits(str(script), {"PATH": "/usr/bin:/bin"}, timeout=5) is None


# --- voz -------------------------------------------------------------------


def test_wav_to_float32_accepts_only_16k_mono():
    audio = wav_to_float32(make_wav(0.5))
    assert len(audio) == 8000 and audio.dtype.name == "float32"
    assert abs(float(audio[0]) - 4096 / 32768) < 1e-6
    with pytest.raises(AudioFormatError):
        wav_to_float32(make_wav(0.5, rate=44100))
    with pytest.raises(AudioFormatError):
        wav_to_float32(make_wav(0.5, channels=2))
    with pytest.raises(AudioFormatError):
        wav_to_float32(b"nao sou um wav")


@pytest.fixture
def voice_client(settings, accounts):
    fake = FakeTranscriber(settings.home)
    with TestClient(create_app(settings, accounts=accounts, transcriber=fake, poll_codex=False)) as client:
        yield client, fake


def test_voice_endpoints(voice_client):
    client, fake = voice_client
    assert client.get("/voice", headers=AUTH).json() == {"model": "falso", "state": "idle", "error": None}
    assert client.post("/voice/transcribe", content=make_wav(1)).status_code == 401

    answer = client.post("/voice/transcribe", content=make_wav(1.5), headers=AUTH)
    assert answer.status_code == 200 and answer.json() == {"text": "texto em pt"}
    assert fake.heard == [24000]
    assert client.post("/voice/transcribe?language=en", content=make_wav(1), headers=AUTH).json()["text"] == "texto em en"
    assert fake.loads == 1  # o modelo carrega uma vez só
    assert client.get("/voice", headers=AUTH).json()["state"] == "ready"


def test_voice_ignores_clicks_and_rejects_bad_audio(voice_client):
    client, fake = voice_client
    assert client.post("/voice/transcribe", content=make_wav(0.1), headers=AUTH).json() == {"text": ""}
    assert fake.loads == 0  # clique sem fala nem carrega o modelo
    assert client.post("/voice/transcribe", content=make_wav(1, rate=48000), headers=AUTH).status_code == 400
    assert client.post("/voice/transcribe?language=portugues", content=make_wav(1), headers=AUTH).status_code == 422


# --- contas pela API -------------------------------------------------------


def test_accounts_api_add_activate_and_broadcast(settings, accounts):
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False)) as client:
        with client.websocket_connect(f"/events?token={TOKEN}") as events:
            hello = events.receive_json()
            assert hello["type"] == "hello" and hello["accounts"]["claude"]["active"] == "padrao"
            assert hello["usage"] == {"claude": {}, "codex": {}}

            created = client.post("/accounts/claude", json={"name": "Trabalho"}, headers=AUTH)
            assert created.status_code == 201 and created.json()["id"] == "trabalho"
            assert events.receive_json()["type"] == "accounts"

            assert client.post("/accounts/claude/trabalho/activate", headers=AUTH).json()["active"] is True
            changed = events.receive_json()
            assert changed["accounts"]["claude"]["active"] == "trabalho"

        assert client.get("/accounts", headers=AUTH).json()["claude"]["active"] == "trabalho"
        assert client.post("/accounts/gemini", json={"name": "x"}, headers=AUTH).status_code == 404
        assert client.post("/accounts/claude/fantasma/activate", headers=AUTH).status_code == 404
        assert client.post("/accounts/claude", json={"name": ""}, headers=AUTH).status_code == 422
        assert client.post("/sessions", json={"kind": "shell", "account": "x"}, headers=AUTH).status_code == 201
        assert client.post("/sessions", json={"kind": "gemini"}, headers=AUTH).status_code == 422


# --- anexos, comando harness nos terminais e tag ----------------------------


def test_attachments_are_saved_privately_with_a_safe_name(settings, accounts):
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False)) as client:
        assert client.post("/attachments?name=x.png", content=b"1").status_code == 401
        answer = client.post("/attachments", params={"name": "../../Print da tela 1.png"}, content=b"\x89PNG", headers=AUTH)
        assert answer.status_code == 201
        saved = __import__("pathlib").Path(answer.json()["path"])
        assert saved.read_bytes() == b"\x89PNG"
        assert saved.parent.parent == settings.home / "anexos"
        assert saved.name.endswith("-Print-da-tela-1.png") and ".." not in saved.name
        assert oct(saved.stat().st_mode & 0o777) == "0o600"


def test_harness_command_works_inside_app_terminals(settings, accounts):
    import subprocess

    from harness_core.sessions import child_env

    with TestClient(create_app(settings, accounts=accounts, poll_codex=False)) as client:
        created = client.post("/sessions", json={"kind": "shell", "cwd": "/tmp", "tag": "float"}, headers=AUTH).json()
        assert created["tag"] == "float"
        assert client.post("/sessions", json={"kind": "shell", "tag": "Flutuante!"}, headers=AUTH).status_code == 422

    env = child_env(settings, "s1")
    assert env["PATH"].endswith(f":{settings.home / 'bin'}")
    venv_bin = str(__import__("pathlib").Path(sys.prefix) / "bin")
    assert venv_bin not in env["PATH"].split(":")  # o Python do núcleo não vaza para os terminais
    accounts.add("codex", "Pessoal")
    for comando in ("metis", "harness"):  # harness é o nome antigo, mantido como apelido
        out = subprocess.run([comando, "contas"], env=env, capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        assert "Pessoal" in out.stdout  # o atalho aponta para o HARNESS_HOME deste núcleo
