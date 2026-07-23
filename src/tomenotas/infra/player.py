"""Reprodução de notas em voz alta: síntese com Piper + playback com paplay.

Espelha o fluxo do ler.sh: texto → piper (gera .wav temporário) → paplay.
A síntese é síncrona (bloqueia) — a camada de cola roda play() numa thread
para não travar a UI, como faz com a transcrição.
"""

import subprocess
from pathlib import Path

from ..domain.errors import PlayerError


class Player:
    def __init__(
        self,
        piper_bin: Path,
        piper_model: Path,
        tts_tmp: Path,
        run=subprocess.run,
        popen=subprocess.Popen,
    ):
        self._piper_bin = piper_bin
        self._piper_model = piper_model
        self._tts_tmp = tts_tmp
        self._run = run
        self._popen = popen
        self._proc = None

    @property
    def is_playing(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def play(self, texto: str) -> None:
        """Sintetiza o texto e inicia a reprodução (parando a anterior).
        Levanta PlayerError com mensagem pronta para o usuário."""
        if not texto.strip():
            raise PlayerError("A nota está vazia.")
        if not self._piper_model.exists():
            raise PlayerError(
                f"Voz do Piper não encontrada: {self._piper_model}"
            )
        self.stop()

        cmd = [
            str(self._piper_bin),
            "--model", str(self._piper_model),
            "--output_file", str(self._tts_tmp),
        ]
        try:
            self._run(
                cmd,
                input=texto.encode(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except FileNotFoundError:
            raise PlayerError("Binário do Piper não encontrado.")

        if not self._tts_tmp.exists():
            raise PlayerError("Falha ao sintetizar o áudio.")

        try:
            self._proc = self._popen(["paplay", str(self._tts_tmp)])
        except FileNotFoundError:
            self._tts_tmp.unlink(missing_ok=True)
            raise PlayerError(
                "paplay não encontrado. Instale o pacote pulseaudio-utils."
            )

    def stop(self) -> None:
        """Para a reprodução atual (se houver) e limpa o .wav temporário."""
        if self.is_playing:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        self._proc = None
        self._tts_tmp.unlink(missing_ok=True)
