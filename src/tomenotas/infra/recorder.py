"""Controle da gravação de áudio via arecord (ALSA)."""

import signal
import subprocess
from pathlib import Path

from ..domain.errors import RecorderError


class Recorder:
    def __init__(self, audio_tmp: Path, popen=subprocess.Popen):
        self.audio_tmp = audio_tmp
        self._popen = popen
        self._proc = None

    @property
    def is_recording(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.is_recording:
            raise RecorderError("já existe uma gravação em andamento")
        self.audio_tmp.parent.mkdir(parents=True, exist_ok=True)
        # FileNotFoundError (arecord ausente) propaga — o chamador decide
        # como avisar o usuário.
        self._proc = self._popen(
            ["arecord", "-f", "cd", "-t", "wav", str(self.audio_tmp)]
        )

    def stop(self, timeout: float = 5) -> None:
        proc = self._proc
        if proc is None:
            raise RecorderError("não há gravação em andamento")
        self._proc = None
        try:
            # SIGINT faz o arecord fechar o .wav corretamente antes de sair
            proc.send_signal(signal.SIGINT)
        except ProcessLookupError:
            return  # o processo já morreu sozinho (ex.: microfone sumiu)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def abort(self) -> None:
        """Encerra qualquer gravação pendente sem transcrever e limpa o tmp."""
        if self.is_recording:
            self.stop()
        self.audio_tmp.unlink(missing_ok=True)
