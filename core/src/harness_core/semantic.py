"""Busca por significado do Brain: embeddings locais, sem API e sem gastar o plano.

Modelo: potion-multilingual-128M da MinishLab (model2vec, https://huggingface.co/minishlab/potion-multilingual-128M),
um modelo estático (tabela de vetores por pedaço de palavra, sem transformer): roda só com
numpy no Mac Intel e entende português. Cada texto vira 256 números; duas notas parecidas
no sentido ficam com vetores próximos (cosseno), mesmo sem palavra em comum.

Guardamos uma cópia local em float16 (~260 MB em disco) em ~/.harness/modelos. Carregado,
ele ocupa ~1,5 GB de memória (630 MB são o tokenizador de 500 mil pedaços), então:
- só o núcleo da MÊTIS carrega o modelo, sob demanda, e solta depois de 20 min parado;
- os vetores das notas ficam no brain.db, e o MCP e o hook de fora da MÊTIS usam esses
  vetores sem carregar nada (texto livre vai ao núcleo, se estiver aberto).

A régua: o cosseno cru tem um piso diferente para cada nota (0,2 a 0,4 de média), então o
que conta é quanto um vizinho se destaca da média daquela consulta (desvios-padrão, z).
Calibrado no vault do Pedro em 2026-11-08: z >= 2,5 costuma ser parente de verdade; entre
2 e 2,5 vem misturado, e é aí que entra o julgamento do modelo (sugestões) ou do agente.
"""

from __future__ import annotations

import gc
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

MODEL_ID = "minishlab/potion-multilingual-128M"
MODEL_URL = "https://huggingface.co/minishlab/potion-multilingual-128M"
LOCAL_NAME = "potion-multilingual-128M-f16"
DIM = 256
IDLE_UNLOAD = 20 * 60


def normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix[None, :]
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float16).tobytes()


def from_blobs(blobs: list[bytes]) -> np.ndarray:
    if not blobs:
        return np.zeros((0, DIM), dtype=np.float32)
    return normalize(np.frombuffer(b"".join(blobs), dtype=np.float16).reshape(len(blobs), -1).astype(np.float32))


def zscores(sims: np.ndarray) -> np.ndarray:
    """Quanto cada valor se destaca da média da coluna (uma coluna por consulta)."""
    mean = sims.mean(axis=0, keepdims=True)
    std = sims.std(axis=0, keepdims=True)
    std[std < 1e-6] = 1.0
    return (sims - mean) / std


class Embedder:
    """O modelo do núcleo: baixa, carrega sob demanda e solta quando fica parado."""

    def __init__(self, models_dir: Path, idle_unload: float = IDLE_UNLOAD, loader: Callable[[Path], object] | None = None) -> None:
        self.dir = Path(models_dir)
        self.local = self.dir / LOCAL_NAME
        self.idle_unload = idle_unload
        self._loader = loader or self._load_model
        self._model = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._loading = False
        self._downloading = False
        self._used = 0.0
        self.error = ""
        self.loads = 0

    # --- estado ------------------------------------------------------------------

    @property
    def installed(self) -> bool:
        return (self.local / "model.safetensors").exists()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def status(self) -> dict:
        if self._downloading:
            state = "baixando"
        elif self.error:
            state = "erro"
        elif not self.installed:
            state = "ausente"
        elif self._loading:
            state = "carregando"
        elif self.loaded:
            state = "pronto"
        else:
            state = "parado"  # instalado, fora da memória até a próxima consulta
        size = sum(p.stat().st_size for p in self.local.glob("*") if p.is_file()) if self.installed else 0
        return {"state": state, "model": MODEL_ID, "url": MODEL_URL, "error": self.error, "disk_mb": round(size / 1e6), "loads": self.loads}

    # --- download ----------------------------------------------------------------

    def download(self) -> None:
        """Baixa do Hugging Face, guarda em float16 e apaga a cópia do cache (roda numa thread)."""
        if self.installed or self._downloading:
            return
        self._downloading, self.error = True, ""

        def work() -> None:
            try:
                from huggingface_hub import snapshot_download
                from model2vec import StaticModel

                cache = self.dir / "hub"
                snapshot = snapshot_download(MODEL_ID, cache_dir=str(cache))
                model = StaticModel.from_pretrained(snapshot, quantize_to="float16", force_download=False)
                tmp = self.dir / (LOCAL_NAME + ".tmp")
                shutil.rmtree(tmp, ignore_errors=True)
                model.save_pretrained(str(tmp))
                tmp.rename(self.local)
                shutil.rmtree(cache / ("models--" + MODEL_ID.replace("/", "--")), ignore_errors=True)
            except Exception as exc:  # rede, disco, versão da biblioteca
                self.error = f"não consegui baixar o modelo: {exc}"
            finally:
                self._downloading = False

        threading.Thread(target=work, name="metis-modelo-download", daemon=True).start()

    # --- carga -------------------------------------------------------------------

    @staticmethod
    def _load_model(path: Path):
        from model2vec import StaticModel

        return StaticModel.from_pretrained(str(path), force_download=False)

    def _start_load(self) -> None:
        with self._lock:
            if self._model is not None or self._loading or not self.installed:
                return
            self._loading, self.error = True, ""
            self._ready.clear()

        def work() -> None:
            try:
                model = self._loader(self.local)
                with self._lock:
                    self._model = model
                    self._used = time.monotonic()
                    self.loads += 1
            except Exception as exc:
                self.error = f"não consegui carregar o modelo: {exc}"
            finally:
                self._loading = False
                self._ready.set()

        threading.Thread(target=work, name="metis-modelo", daemon=True).start()

    def encode(self, texts: list[str], wait: float = 30.0) -> np.ndarray | None:
        """Vetores normalizados, ou None se o modelo não está pronto dentro de `wait` segundos."""
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        if self._model is None:
            if not self.installed:
                return None
            self._start_load()
            if wait <= 0 or not self._ready.wait(wait):
                return None
        model = self._model
        if model is None:
            return None
        self._used = time.monotonic()
        return normalize(model.encode([t[:2000] for t in texts]))

    def tick(self) -> None:
        """Chamado pelo agendador: solta o modelo parado há mais de idle_unload segundos."""
        with self._lock:
            if self._model is not None and time.monotonic() - self._used > self.idle_unload:
                self._model = None
                gc.collect()
