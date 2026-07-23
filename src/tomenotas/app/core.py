"""Caso de uso central: máquina de estados idle → recording → transcribing.

Lógica pura e síncrona, sem GTK/D-Bus/threads — tudo de I/O entra por
injeção (recorder, transcriber, notes, notifier), o que torna o módulo
100% testável. A camada de cola (ui/daemon.py) decide o que roda em
thread. Importa apenas domain/ — nunca infra/ ou ui/.
"""

import logging

from ..domain.errors import TranscriptionError
from ..domain.note import preview
from ..domain.state import State, ToggleAction

log = logging.getLogger("tomenotas.core")


class DaemonCore:
    def __init__(self, recorder, transcriber, notes, notifier):
        self._recorder = recorder
        self._transcriber = transcriber
        self._notes = notes
        self._notifier = notifier
        self._state = State.IDLE
        # Observador de mudanças de estado (ícone da bandeja).
        # Atenção: finish_recording roda em thread — a cola faz GLib.idle_add.
        self.on_state_change = None

    @property
    def state(self) -> State:
        return self._state

    def _set_state(self, novo: State) -> None:
        if novo is self._state:
            return
        log.info("estado: %s -> %s", self._state.name, novo.name)
        self._state = novo
        if self.on_state_change is not None:
            self.on_state_change(novo)

    def toggle(self) -> ToggleAction:
        if self.state is State.IDLE:
            return self._start()
        if self.state is State.RECORDING:
            self._set_state(State.TRANSCRIBING)
            self._notifier.send("Gravação", "Transcrevendo...")
            return ToggleAction.STOP_REQUESTED
        # TRANSCRIBING: ignora o toque até a transcrição anterior acabar
        self._notifier.send(
            "Gravação", "Aguarde: ainda transcrevendo a nota anterior."
        )
        return ToggleAction.BUSY

    def _start(self) -> ToggleAction:
        try:
            self._recorder.start()
        except FileNotFoundError:
            log.error("arecord não encontrado")
            self._notifier.send(
                "Erro", "arecord não encontrado. Instale o pacote alsa-utils."
            )
            return ToggleAction.FAILED
        self._set_state(State.RECORDING)
        self._notifier.send(
            "Gravação", "Gravando... aperte o atalho de novo para parar."
        )
        return ToggleAction.STARTED

    def finish_recording(self) -> None:
        """Para o arecord, transcreve e salva a nota. Síncrono e lento —
        a cola chama isto numa thread para não travar o main loop."""
        try:
            self._recorder.stop()
            texto = self._transcriber.transcribe(self._recorder.audio_tmp)
        except TranscriptionError as erro:
            log.error("transcrição falhou: %s", erro)
            self._notifier.send("Erro", str(erro))
        else:
            caminho = self._notes.save(texto)
            log.info("nota criada: %s", caminho)
            self._notifier.send("Nota criada", preview(texto))
        finally:
            self._recorder.audio_tmp.unlink(missing_ok=True)
            self._set_state(State.IDLE)

    def shutdown(self) -> None:
        """Encerra limpo: aborta gravação pendente sem transcrever."""
        self._recorder.abort()
        self._set_state(State.IDLE)
