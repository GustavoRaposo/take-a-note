"""Model downloads for the first-run flow (Fase A of the .deb plan).

The STT/TTS models are no longer downloaded by install.sh: the daemon
offers them on first use (Configurações → Modelo de transcrição / Voz).
Downloads stream to a `.part` file and are renamed atomically, so an
interrupted download never leaves a corrupt model behind. This does not
break the "100% offline" rule: it is a one-time artifact fetch, not a
runtime AI service call.
"""

import logging
import urllib.request
from pathlib import Path

from ..domain.errors import DownloadError
from .config import update_config_file

log = logging.getLogger("tomenotas.downloads")

_WHISPER_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
# size -> download url + label shown in the UI (approximate sizes)
WHISPER_MODELS = {
    "tiny": {"url": f"{_WHISPER_BASE}/ggml-tiny.bin",
             "label": "tiny (~75 MB, mais rápido)"},
    "base": {"url": f"{_WHISPER_BASE}/ggml-base.bin",
             "label": "base (~142 MB)"},
    "small": {"url": f"{_WHISPER_BASE}/ggml-small.bin",
              "label": "small (~466 MB)"},
    "medium": {"url": f"{_WHISPER_BASE}/ggml-medium.bin",
               "label": "medium (~1.5 GB, recomendado)"},
    "large-v3": {"url": f"{_WHISPER_BASE}/ggml-large-v3.bin",
                 "label": "large-v3 (~2.9 GB, mais preciso)"},
}

_VOICE_BASE = ("https://huggingface.co/rhasspy/piper-voices/resolve/main"
               "/pt/pt_BR/faber/medium")
DEFAULT_VOICE = {
    "name": "pt_BR-faber-medium",
    "onnx_url": f"{_VOICE_BASE}/pt_BR-faber-medium.onnx",
    "json_url": f"{_VOICE_BASE}/pt_BR-faber-medium.onnx.json",
}


class Downloader:
    """Streams a URL to disk with progress callbacks and atomic rename."""

    def __init__(self, opener=urllib.request.urlopen, chunk_size=1 << 16):
        self._opener = opener
        self._chunk_size = chunk_size

    def fetch(self, url: str, dest: Path, on_progress=None) -> Path:
        """Downloads url into dest. on_progress(done_bytes, total_or_None)
        is called per chunk. Raises DownloadError (user-facing message)
        on network failure or size mismatch; on failure nothing is left
        on disk."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        done = 0
        try:
            with self._opener(url) as response:
                raw_total = response.headers.get("Content-Length")
                total = int(raw_total) if raw_total else None
                with open(part, "wb") as out:
                    while True:
                        chunk = response.read(self._chunk_size)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if on_progress is not None:
                            on_progress(done, total)
        except OSError as error:
            part.unlink(missing_ok=True)
            log.error("download failed: %s (%s)", url, error)
            raise DownloadError(
                f"Falha no download. Verifique sua conexão e tente de "
                f"novo. ({error})"
            ) from error
        if total is not None and done != total:
            part.unlink(missing_ok=True)
            log.error("download truncated: %s (%d of %d bytes)",
                      url, done, total)
            raise DownloadError(
                "Download incompleto (tamanho não confere). Tente novamente."
            )
        part.replace(dest)  # atomic: the final file is always complete
        log.info("downloaded %s (%d bytes)", dest.name, done)
        return dest


def download_voice(downloader: Downloader, voices_dir: Path,
                   on_progress=None, voice=None) -> Path:
    """Downloads a Piper voice pair (.onnx + .onnx.json) into voices_dir
    and returns the .onnx path. Progress reports the .onnx (the .json is
    a few KB)."""
    voice = voice or DEFAULT_VOICE
    voices_dir = Path(voices_dir)
    onnx = downloader.fetch(voice["onnx_url"],
                            voices_dir / f"{voice['name']}.onnx",
                            on_progress=on_progress)
    downloader.fetch(voice["json_url"],
                     voices_dir / f"{voice['name']}.onnx.json")
    return onnx


class ModelManager:
    """Whisper model switcher, symmetric to VoiceManager: downloads/uses
    a model size, applies it to the injected Transcriber right away and
    persists `whisper_model` in config.json."""

    def __init__(self, transcriber, whisper_model: Path, models_dir: Path,
                 downloader: Downloader, config_path: Path | None = None):
        self._transcriber = transcriber
        self._current = Path(whisper_model)
        self.models_dir = Path(models_dir)
        self.downloader = downloader
        self._config_path = config_path

    def model_path(self, size: str) -> Path:
        return self.models_dir / f"ggml-{size}.bin"

    def current_size(self) -> str:
        return self._current.stem.removeprefix("ggml-")

    def is_installed(self, size: str) -> bool:
        if self.model_path(size).exists():
            return True
        # the active model may live outside models_dir (old installs
        # keep it in ~/whisper.cpp/models via config.json)
        return size == self.current_size() and self._current.exists()

    def download(self, size: str, on_progress=None,
                 activate: bool = True) -> Path:
        """Downloads the model. By default makes it the active main model;
        activate=False just fetches it (used for the small live-stream
        model, which must not replace the main transcription model)."""
        info = WHISPER_MODELS[size]
        path = self.downloader.fetch(info["url"], self.model_path(size),
                                     on_progress=on_progress)
        if activate:
            self._activate(path)
        return path

    def use(self, size: str) -> None:
        """Switches to an already-installed model."""
        if not self.is_installed(size):
            raise ValueError(f"Modelo {size} ainda não baixado.")
        path = (self.model_path(size) if self.model_path(size).exists()
                else self._current)
        self._activate(path)

    def _activate(self, path: Path) -> None:
        self._current = path
        self._transcriber.set_model(path)
        update_config_file("whisper_model", str(path), self._config_path)
        log.info("whisper model switched to %s", path.name)
