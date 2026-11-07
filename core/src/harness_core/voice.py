"""Transcrição de voz local com Whisper (faster-whisper), sem API e sem custo.

A janela grava, converte para WAV 16 kHz mono e manda ao núcleo. O núcleo lê o WAV
com a biblioteca padrão (sem ffmpeg) e transcreve no próprio Mac. O modelo é baixado
na primeira vez para ~/.harness/modelos.
"""

from __future__ import annotations

import asyncio
import io
import os
import wave
from pathlib import Path

DEFAULT_MODEL = "small"
SAMPLE_RATE = 16000

# Ajuda o Whisper com termos em inglês no meio do português.
VOCABULARY = (
    "Conversa de programação em português com termos em inglês: diff, leads, commit, "
    "pull request, deploy, branch, worktree, merge, Claude, Codex, Brain, ClickUp, Slack, "
    "prompt, bug, testes, hook, frontend, backend."
)


class AudioFormatError(ValueError):
    pass


def wav_to_float32(data: bytes):
    """WAV PCM 16 bits, 16 kHz, mono → array float32 em [-1, 1]."""
    import numpy as np

    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if wav.getsampwidth() != 2 or wav.getnchannels() != 1 or wav.getframerate() != SAMPLE_RATE:
                raise AudioFormatError(
                    f"esperado WAV 16 bits mono {SAMPLE_RATE} Hz; veio {wav.getsampwidth() * 8} bits, "
                    f"{wav.getnchannels()} canais, {wav.getframerate()} Hz"
                )
            frames = wav.readframes(wav.getnframes())
    except wave.Error as exc:
        raise AudioFormatError(f"WAV inválido: {exc}") from exc
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


class Transcriber:
    def __init__(self, home: Path, model_name: str | None = None) -> None:
        self.model_name = model_name or os.environ.get("HARNESS_VOICE_MODEL") or DEFAULT_MODEL
        self.download_root = home / "modelos"
        self.state = "idle"  # idle → loading → ready | error
        self.error: str | None = None
        self._model = None
        self._lock = asyncio.Lock()

    def status(self) -> dict:
        return {"model": self.model_name, "state": self.state, "error": self.error}

    def _load(self):
        from faster_whisper import WhisperModel

        self.download_root.mkdir(parents=True, exist_ok=True)
        return WhisperModel(self.model_name, device="cpu", compute_type="int8", download_root=str(self.download_root))

    async def prepare(self) -> None:
        async with self._lock:
            if self._model is not None:
                return
            self.state, self.error = "loading", None
            try:
                self._model = await asyncio.get_running_loop().run_in_executor(None, self._load)
            except Exception as exc:  # download ou modelo quebrado
                self.state, self.error = "error", str(exc)
                raise
            self.state = "ready"

    def _run(self, audio, language: str) -> str:
        segments, _ = self._model.transcribe(
            audio, language=language, beam_size=5, initial_prompt=VOCABULARY, vad_filter=False
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    async def transcribe(self, wav_bytes: bytes, language: str = "pt") -> str:
        audio = wav_to_float32(wav_bytes)
        if len(audio) < SAMPLE_RATE // 4:
            return ""  # menos de 0,25 s: clique sem fala
        await self.prepare()
        return await asyncio.get_running_loop().run_in_executor(None, self._run, audio, language)
