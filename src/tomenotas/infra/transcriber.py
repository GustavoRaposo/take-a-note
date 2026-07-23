"""Audio transcription via whisper.cpp (subprocess)."""

import logging
import subprocess
from pathlib import Path

from ..domain.errors import TranscriptionError

log = logging.getLogger("tomenotas.transcriber")


class Transcriber:
    def __init__(
        self,
        whisper_bin: Path,
        whisper_model: Path,
        language: str = "pt",
        run=subprocess.run,
    ):
        self._whisper_bin = whisper_bin
        self._whisper_model = whisper_model
        self._language = language
        self._run = run

    def is_ready(self) -> bool:
        """False until the model file exists (downloaded on first run)."""
        return self._whisper_model.exists()

    def set_model(self, whisper_model: Path) -> None:
        """Switches the model; takes effect on the next transcribe()."""
        self._whisper_model = whisper_model

    def transcribe(self, wav_path: Path) -> str:
        """Transcribes the .wav and returns the text. Raises
        TranscriptionError (with a user-ready message) on any failure."""
        # Checks with specific messages (Fase 5), instead of the generic
        # "failed to transcribe" error:
        if not wav_path.exists():
            raise TranscriptionError(
                "Áudio da gravação não encontrado. O microfone está funcionando?"
            )
        if not self._whisper_model.exists():
            raise TranscriptionError(
                f"Modelo do whisper não encontrado: {self._whisper_model}"
            )

        log.info("transcribing %s", wav_path)
        out_base = wav_path.with_name("tmp_transcricao")
        cmd = [
            str(self._whisper_bin),
            "-m", str(self._whisper_model),
            "-l", self._language,
            "-f", str(wav_path),
            "-nt", "-otxt",
            "-of", str(out_base),
        ]
        try:
            self._run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except FileNotFoundError:
            raise TranscriptionError("Binário do whisper.cpp não encontrado.")

        out_file = out_base.with_suffix(".txt")
        if not out_file.exists():
            raise TranscriptionError("Falha ao transcrever o áudio.")

        text = out_file.read_text(encoding="utf-8", errors="replace").strip()
        out_file.unlink()
        return text
