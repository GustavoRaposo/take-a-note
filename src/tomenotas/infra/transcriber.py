"""Transcrição de áudio via whisper.cpp (subprocess)."""

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

    def transcribe(self, wav_path: Path) -> str:
        """Transcreve o .wav e devolve o texto. Levanta TranscriptionError
        (com mensagem pronta para o usuário) em qualquer falha."""
        # Checagens com mensagens específicas (Fase 5), em vez do erro
        # genérico de "falha ao transcrever":
        if not wav_path.exists():
            raise TranscriptionError(
                "Áudio da gravação não encontrado. O microfone está funcionando?"
            )
        if not self._whisper_model.exists():
            raise TranscriptionError(
                f"Modelo do whisper não encontrado: {self._whisper_model}"
            )

        log.info("transcrevendo %s", wav_path)
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

        texto = out_file.read_text(encoding="utf-8", errors="replace").strip()
        out_file.unlink()
        return texto
