"""Central use case: the idle → recording → transcribing state machine.

Pure, synchronous logic with no GTK/D-Bus/threads — all I/O comes in via
injection (recorder, transcriber, notes, notifier), which makes the
module 100% testable. The glue layer (ui/daemon.py) decides what runs in
a thread. Imports only domain/ — never infra/ or ui/.
"""

import logging

from ..domain.errors import PlayerError, TranscriptionError
from ..domain.note import preview
from ..domain.state import State, ToggleAction

log = logging.getLogger("tomenotas.core")


class DaemonCore:
    def __init__(self, recorder, transcriber, notes, notifier, player=None):
        self._recorder = recorder
        self._transcriber = transcriber
        self._notes = notes
        self._notifier = notifier
        self._player = player  # used by read_current_note (Super+T)
        self._state = State.IDLE
        # Observer for state changes (tray icon).
        # Careful: finish_recording runs in a thread — the glue wraps
        # this with GLib.idle_add.
        self.on_state_change = None

    @property
    def state(self) -> State:
        return self._state

    def _set_state(self, new: State) -> None:
        if new is self._state:
            return
        log.info("state: %s -> %s", self._state.name, new.name)
        self._state = new
        if self.on_state_change is not None:
            self.on_state_change(new)

    def toggle(self) -> ToggleAction:
        if self.state is State.IDLE:
            return self._start()
        if self.state is State.RECORDING:
            self._set_state(State.TRANSCRIBING)
            self._notifier.send("Gravação", "Transcrevendo...")
            return ToggleAction.STOP_REQUESTED
        # TRANSCRIBING: ignore the press until the previous transcription ends
        self._notifier.send(
            "Gravação", "Aguarde: ainda transcrevendo a nota anterior."
        )
        return ToggleAction.BUSY

    def _start(self) -> ToggleAction:
        # First-run: no point recording audio nobody can transcribe
        if not self._transcriber.is_ready():
            log.error("whisper model not downloaded yet")
            self._notifier.send(
                "Erro",
                "O modelo de transcrição ainda não foi baixado. "
                "Abra o Tomenotas e baixe-o em Configurações.",
            )
            return ToggleAction.FAILED
        try:
            self._recorder.start()
        except FileNotFoundError:
            log.error("arecord not found")
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
        """Stops arecord, transcribes and saves the note. Synchronous and
        slow — the glue calls this in a thread to keep the main loop
        responsive."""
        try:
            self._recorder.stop()
            text = self._transcriber.transcribe(self._recorder.audio_tmp)
        except TranscriptionError as error:
            log.error("transcription failed: %s", error)
            self._notifier.send("Erro", str(error))
        else:
            path = self._notes.save(text)
            log.info("note created: %s", path)
            self._notifier.send("Nota criada", preview(text))
        finally:
            self._recorder.audio_tmp.unlink(missing_ok=True)
            self._set_state(State.IDLE)

    def read_current_note(self) -> None:
        """Reads the most recent note aloud (Super+T — replaces the
        legacy ler.sh). Synchronous and slow (TTS synthesis) — the glue
        calls it in a thread. Messages match the old ler.sh."""
        notes = self._notes.list()
        if not notes:
            self._notifier.send("TTS", "Nenhuma nota disponível para ler.")
            return
        try:
            self._player.play(notes[0].text)
        except PlayerError as error:
            log.error("read-aloud failed: %s", error)
            self._notifier.send("Erro", str(error))

    def shutdown(self) -> None:
        """Clean shutdown: aborts any pending recording without transcribing."""
        self._recorder.abort()
        self._set_state(State.IDLE)
