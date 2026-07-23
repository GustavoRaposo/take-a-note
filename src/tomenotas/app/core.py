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
    def __init__(self, recorder, transcriber, notes, notifier, player=None,
                 meeting_recorder=None, stream=None):
        self._recorder = recorder
        self._meeting_recorder = meeting_recorder  # mic + system audio
        self._active_recorder = recorder  # set per recording by toggle()
        self._transcriber = transcriber
        self._notes = notes
        self._notifier = notifier
        self._player = player  # used by read_current_note (Super+T)
        self._stream = stream  # live-preview transcriber (whisper-stream)
        self.stream_enabled = False  # set by the glue from config
        self._streaming = False
        self._state = State.IDLE
        self._pending_critical = False  # mode of the recording in course
        self._pending_meeting = False
        # Observer for state changes (tray icon).
        # Careful: finish_recording runs in a thread — the glue wraps
        # this with GLib.idle_add.
        self.on_state_change = None
        # Observer for saved notes (arms the critical alarm). Also fires
        # from the transcription thread — glue wraps with GLib.idle_add.
        self.on_note_saved = None
        # Observer for the live preview text (fires from the stream reader
        # thread — the glue wraps with GLib.idle_add).
        self.on_stream_text = None

    @property
    def is_streaming(self) -> bool:
        return self._streaming

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

    def toggle(self, critical: bool = False,
               meeting: bool = False) -> ToggleAction:
        """The hotkey that STARTS the recording sets its mode; any hotkey
        stops it. critical=True (Super+I): the saved note is born
        critical. meeting=True (Super+[): captures microphone + computer
        audio via the meeting recorder."""
        if self.state is State.IDLE:
            self._pending_critical = critical
            self._pending_meeting = meeting and self._meeting_recorder is not None
            self._active_recorder = (self._meeting_recorder
                                     if self._pending_meeting
                                     else self._recorder)
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
            self._active_recorder.start()
        except FileNotFoundError:
            log.error("recorder start failed: missing binary")
            self._notifier.send(
                "Erro",
                "Ferramentas de captura de reunião não encontradas "
                "(pactl/pw-record)."
                if self._pending_meeting else
                "arecord não encontrado. Instale o pacote alsa-utils.",
            )
            return ToggleAction.FAILED
        self._set_state(State.RECORDING)
        self._maybe_start_stream()
        self._notifier.send(
            "Gravação",
            "Gravando reunião (microfone + áudio do PC)... "
            "aperte o atalho de novo para parar."
            if self._pending_meeting else
            "Gravando... aperte o atalho de novo para parar.",
        )
        return ToggleAction.STARTED

    def _maybe_start_stream(self) -> None:
        """Live preview (whisper-stream), in parallel with arecord. Only
        for mic recordings (not meeting mode) and only if the small model
        is present. Preview only — never affects the saved note."""
        self._streaming = False
        if (not self.stream_enabled or self._pending_meeting
                or self._stream is None or not self._stream.is_ready()):
            return
        try:
            self._stream.start(self._emit_stream_text)
            self._streaming = True
        except Exception as error:  # a broken preview must not break recording
            log.warning("live stream failed to start: %s", error)

    def _emit_stream_text(self, text: str) -> None:
        if self.on_stream_text is not None:
            self.on_stream_text(text)

    def _stop_stream(self) -> None:
        if self._stream is not None:
            self._stream.stop()
        self._streaming = False

    def finish_recording(self) -> None:
        """Stops arecord, transcribes and saves the note. Synchronous and
        slow — the glue calls this in a thread to keep the main loop
        responsive."""
        self._stop_stream()  # end the live preview; the note comes next
        try:
            self._active_recorder.stop()
            text = self._transcriber.transcribe(
                self._active_recorder.audio_tmp)
        except TranscriptionError as error:
            log.error("transcription failed: %s", error)
            self._notifier.send("Erro", str(error))
        else:
            note = self._notes.save(text, critical=self._pending_critical)
            log.info("note created: %s (critical=%s)", note,
                     self._pending_critical)
            self._notifier.send(
                "Nota crítica criada" if self._pending_critical
                else "Nota criada",
                preview(text),
            )
            if self.on_note_saved is not None:
                self.on_note_saved(note)
        finally:
            self._active_recorder.audio_tmp.unlink(missing_ok=True)
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

    def read_current_critical(self) -> None:
        """Reads the most recent ACTIVE critical note aloud (Super+K).
        Synchronous and slow (TTS) — the glue calls it in a thread."""
        criticals = self._notes.active_criticals()
        if not criticals:
            self._notifier.send("Notas críticas",
                                "Nenhuma nota crítica ativa.")
            return
        try:
            self._player.play(criticals[0].text)
        except PlayerError as error:
            log.error("critical read-aloud failed: %s", error)
            self._notifier.send("Erro", str(error))

    def shutdown(self) -> None:
        """Clean shutdown: aborts any pending recording without transcribing."""
        self._stop_stream()
        self._active_recorder.abort()
        self._set_state(State.IDLE)
