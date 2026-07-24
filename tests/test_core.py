"""Tests for tomenotas.app.core — the daemon state machine."""

from datetime import datetime
from pathlib import Path

from tomenotas.app.core import DaemonCore
from tomenotas.domain.errors import TranscriptionError
from tomenotas.domain.state import State, ToggleAction
from tomenotas.infra.notes_db import SqliteNoteStore


class FakeRecorder:
    def __init__(self, audio_tmp: Path, fails_on_start=False):
        self.audio_tmp = audio_tmp
        self.fails_on_start = fails_on_start
        self.started = False
        self.stopped = False
        self.aborted = False

    def start(self):
        if self.fails_on_start:
            raise FileNotFoundError
        self.started = True

    def stop(self):
        self.stopped = True

    def abort(self):
        self.aborted = True


class FakeTranscriber:
    def __init__(self, text="texto transcrito", error=None, ready=True):
        self.text = text
        self.error = error
        self.ready = ready
        self.transcribed = []

    def is_ready(self):
        return self.ready

    def transcribe(self, wav_path):
        self.transcribed.append(wav_path)
        if self.error:
            raise self.error
        return self.text


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send(self, title, body):
        self.messages.append((title, body))


class FakePlayer:
    def __init__(self, error=None):
        self.error = error
        self.played = []

    def play(self, text):
        if self.error:
            raise self.error
        self.played.append(text)


class FakeStream:
    def __init__(self, ready=True):
        self._ready = ready
        self.started = False
        self.stopped = False
        self._on_text = None

    def is_ready(self):
        return self._ready

    def start(self, on_text):
        self.started = True
        self._on_text = on_text

    def stop(self):
        self.stopped = True

    def emit(self, text):  # simulate whisper-stream output
        if self._on_text:
            self._on_text(text)


class FakeWakeword:
    def __init__(self):
        self.started = False
        self.stopped = False
        self._on_detected = None

    @property
    def is_running(self):
        return self.started and not self.stopped

    def start(self, on_detected):
        self.started = True
        self.stopped = False
        self._on_detected = on_detected

    def stop(self):
        self.stopped = True

    def fire(self):  # simulate the wake word being heard
        if self._on_detected:
            self._on_detected()


def make_core(tmp_path, fails_on_start=False, transcription_error=None,
              text="texto transcrito", player_error=None, ready=True,
              stream_enabled=False, stream_ready=True):
    audio_tmp = tmp_path / "tmp_recording.wav"
    recorder = FakeRecorder(audio_tmp, fails_on_start=fails_on_start)
    meeting = FakeRecorder(tmp_path / "tmp_meeting.wav")
    transcriber = FakeTranscriber(text=text, error=transcription_error,
                                  ready=ready)
    notes = SqliteNoteStore(tmp_path / "notes.db", tmp_path / "notes",
                            now=lambda: datetime(2026, 7, 22, 15, 0, 38))
    notifier = FakeNotifier()
    core = DaemonCore(recorder, transcriber, notes, notifier,
                      player=FakePlayer(error=player_error),
                      meeting_recorder=meeting,
                      stream=FakeStream(ready=stream_ready),
                      wakeword=FakeWakeword())
    core.stream_enabled = stream_enabled
    return core, recorder, transcriber, notes, notifier


def test_toggle_while_idle_starts_recording(tmp_path):
    core, recorder, _, _, notifier = make_core(tmp_path)
    action = core.toggle()
    assert action is ToggleAction.STARTED
    assert core.state is State.RECORDING
    assert recorder.started
    assert notifier.messages == [
        ("Gravação", "Gravando... aperte o atalho de novo para parar.")
    ]


def test_toggle_without_arecord_warns_and_stays_idle(tmp_path):
    core, _, _, _, notifier = make_core(tmp_path, fails_on_start=True)
    action = core.toggle()
    assert action is ToggleAction.FAILED
    assert core.state is State.IDLE
    assert notifier.messages == [
        ("Erro", "arecord não encontrado. Instale o pacote alsa-utils.")
    ]


def test_toggle_without_model_warns_and_does_not_record(tmp_path):
    core, recorder, _, _, notifier = make_core(tmp_path, ready=False)
    action = core.toggle()
    assert action is ToggleAction.FAILED
    assert core.state is State.IDLE
    assert not recorder.started  # never even touched the microphone
    assert notifier.messages == [(
        "Erro",
        "O modelo de transcrição ainda não foi baixado. "
        "Abra o Tomenotas e baixe-o em Configurações.",
    )]


def test_toggle_while_recording_requests_stop(tmp_path):
    core, _, _, _, notifier = make_core(tmp_path)
    core.toggle()
    action = core.toggle()
    assert action is ToggleAction.STOP_REQUESTED
    assert core.state is State.TRANSCRIBING
    assert notifier.messages[-1] == ("Gravação", "Transcrevendo...")


def test_toggle_while_transcribing_is_ignored(tmp_path):
    core, recorder, _, _, notifier = make_core(tmp_path)
    core.toggle()
    core.toggle()
    action = core.toggle()
    assert action is ToggleAction.BUSY
    assert core.state is State.TRANSCRIBING
    assert notifier.messages[-1] == (
        "Gravação", "Aguarde: ainda transcrevendo a nota anterior."
    )


def test_finish_saves_note_and_returns_to_idle(tmp_path):
    core, recorder, transcriber, notes, notifier = make_core(
        tmp_path, text="conteúdo da nota gravada"
    )
    recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle()
    core.toggle()

    core.finish_recording()

    assert recorder.stopped
    assert transcriber.transcribed == [recorder.audio_tmp]
    (note,) = notes.list()
    assert note.text == "conteúdo da nota gravada"
    assert note.created_at == "2026-07-22T15:00:38"
    assert notifier.messages[-1] == ("Nota criada", "conteúdo da nota gravada")
    assert not recorder.audio_tmp.exists()  # temp .wav removed
    assert core.state is State.IDLE


def test_finish_with_truncated_preview(tmp_path):
    text = "x" * 100
    core, _, _, _, notifier = make_core(tmp_path, text=text)
    core.toggle()
    core.toggle()
    core.finish_recording()
    assert notifier.messages[-1] == ("Nota criada", "x" * 60)


def test_finish_with_error_notifies_and_returns_to_idle(tmp_path):
    core, recorder, _, notes, notifier = make_core(
        tmp_path,
        transcription_error=TranscriptionError("Falha ao transcrever o áudio."),
    )
    recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle()
    core.toggle()

    core.finish_recording()

    assert notifier.messages[-1] == ("Erro", "Falha ao transcrever o áudio.")
    assert not notes.notes_dir.exists()  # no note created
    assert not recorder.audio_tmp.exists()  # tmp cleaned even on error
    assert core.state is State.IDLE


def test_toggle_critical_saves_a_critical_note(tmp_path):
    core, recorder, _, notes, notifier = make_core(tmp_path,
                                                   text="urgente!")
    recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle(critical=True)
    core.toggle()  # stopping with the normal hotkey keeps the mode
    core.finish_recording()

    (note,) = notes.list()
    assert note.critical is True
    assert notifier.messages[-1] == ("Nota crítica criada", "urgente!")


def test_toggle_normal_stays_normal_even_after_a_critical_one(tmp_path):
    core, recorder, _, notes, _ = make_core(tmp_path)
    recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle(critical=True)
    core.toggle()
    core.finish_recording()

    recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle()  # new recording, normal mode
    core.toggle()
    core.finish_recording()

    latest = notes.list()[0]
    assert latest.critical is False


def test_note_saved_observer_fires_with_the_note(tmp_path):
    core, recorder, _, _, _ = make_core(tmp_path, text="observada")
    saved = []
    core.on_note_saved = saved.append
    recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle(critical=True)
    core.toggle()
    core.finish_recording()
    assert [n.text for n in saved] == ["observada"]
    assert saved[0].critical is True


def test_read_current_critical_plays_the_latest_active(tmp_path):
    moments = iter([datetime(2026, 7, 22, 10, 0, 0),
                    datetime(2026, 7, 22, 11, 0, 0)])
    core, _, _, notes, _ = make_core(tmp_path)
    notes._now = lambda: next(moments)
    notes.save("crítica antiga", critical=True)
    notes.save("crítica nova", critical=True)

    core.read_current_critical()

    assert core._player.played == ["crítica nova"]


def test_read_current_critical_without_active_ones_warns(tmp_path):
    core, _, _, notes, notifier = make_core(tmp_path)
    notes.save("normal")  # not critical
    core.read_current_critical()
    assert notifier.messages == [
        ("Notas críticas", "Nenhuma nota crítica ativa.")
    ]


def test_read_current_critical_with_player_error_notifies(tmp_path):
    from tomenotas.domain.errors import PlayerError

    core, _, _, notes, notifier = make_core(
        tmp_path, player_error=PlayerError("Voz do Piper não encontrada: /x")
    )
    notes.save("urgente", critical=True)
    core.read_current_critical()
    assert notifier.messages == [
        ("Erro", "Voz do Piper não encontrada: /x")
    ]


def test_toggle_meeting_uses_the_meeting_recorder(tmp_path):
    core, mic, _, _, notifier = make_core(tmp_path, text="ata da reunião")
    meeting = core._meeting_recorder
    meeting.audio_tmp.write_bytes(b"RIFF")

    action = core.toggle(meeting=True)
    assert action is ToggleAction.STARTED
    assert meeting.started and not mic.started  # the mix recorder started
    assert "reunião" in notifier.messages[-1][1].lower()

    core.toggle()  # same stop hotkey ends it
    core.finish_recording()
    assert meeting.stopped
    assert not mic.stopped  # the mic recorder was never touched


def test_meeting_note_is_saved_normal_not_critical(tmp_path):
    core, _, _, notes, _ = make_core(tmp_path, text="reunião de equipe")
    core._meeting_recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle(meeting=True)
    core.toggle()
    core.finish_recording()
    (note,) = notes.list()
    assert note.text == "reunião de equipe"
    assert note.critical is False


def test_shutdown_aborts_the_active_meeting_recorder(tmp_path):
    core, mic, _, _, _ = make_core(tmp_path)
    meeting = core._meeting_recorder
    core.toggle(meeting=True)
    core.shutdown()
    assert meeting.aborted
    assert not mic.aborted


def test_live_stream_starts_with_recording_when_enabled(tmp_path):
    core, _, _, _, _ = make_core(tmp_path, stream_enabled=True)
    texts = []
    core.on_stream_text = texts.append

    core.toggle()  # idle -> recording
    assert core._stream.started
    assert core.is_streaming
    core._stream.emit("olá ao vivo")
    assert texts == ["olá ao vivo"]


def test_live_stream_stays_off_when_disabled(tmp_path):
    core, _, _, _, _ = make_core(tmp_path, stream_enabled=False)
    core.toggle()
    assert not core._stream.started
    assert not core.is_streaming


def test_live_stream_stays_off_in_meeting_mode(tmp_path):
    # meeting captures system audio via a mix; whisper-stream only hears
    # the mic, so streaming is skipped for meeting recordings
    core, _, _, _, _ = make_core(tmp_path, stream_enabled=True)
    core.toggle(meeting=True)
    assert not core._stream.started


def test_live_stream_skipped_when_small_model_missing(tmp_path):
    core, _, _, _, _ = make_core(tmp_path, stream_enabled=True,
                                 stream_ready=False)
    core.toggle()
    assert not core._stream.started
    assert not core.is_streaming


def test_stream_start_failure_does_not_break_recording(tmp_path):
    core, recorder, _, _, _ = make_core(tmp_path, stream_enabled=True)

    def boom(_on_text):
        raise RuntimeError("sem microfone para o stream")

    core._stream.start = boom
    action = core.toggle()

    assert action is ToggleAction.STARTED  # recording proceeds
    assert core.state is State.RECORDING
    assert recorder.started
    assert not core.is_streaming  # preview just didn't come up


def test_finish_stops_the_live_stream(tmp_path):
    core, recorder, _, _, _ = make_core(tmp_path, stream_enabled=True)
    recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle()
    core.toggle()
    core.finish_recording()
    assert core._stream.stopped
    assert not core.is_streaming


def test_shutdown_stops_the_live_stream(tmp_path):
    core, _, _, _, _ = make_core(tmp_path, stream_enabled=True)
    core.toggle()
    core.shutdown()
    assert core._stream.stopped


def test_shutdown_stops_wakeword_and_does_not_relaunch(tmp_path):
    core, _, _, _, _ = make_core(tmp_path)
    core.set_wakeword_enabled(True)
    assert core._wakeword.is_running
    core.shutdown()
    assert not core._wakeword.is_running  # stopped and not relaunched by IDLE


def test_wakeword_listens_when_enabled_and_idle(tmp_path):
    core, _, _, _, _ = make_core(tmp_path)
    core.set_wakeword_enabled(True)
    assert core._wakeword.is_running


def test_wakeword_stays_off_when_disabled(tmp_path):
    core, _, _, _, _ = make_core(tmp_path)
    core.set_wakeword_enabled(False)
    assert not core._wakeword.is_running


def test_wakeword_pauses_while_recording_and_resumes_when_idle(tmp_path):
    core, recorder, _, _, _ = make_core(tmp_path)
    core.set_wakeword_enabled(True)
    assert core._wakeword.is_running

    recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle()  # idle -> recording: must stop listening (mic + self-trigger)
    assert not core._wakeword.is_running

    core.toggle()            # recording -> transcribing
    core.finish_recording()  # -> idle: listening resumes
    assert core._wakeword.is_running


def test_wakeword_detected_fires_the_observer(tmp_path):
    core, _, _, _, _ = make_core(tmp_path)
    fired = []
    core.on_wakeword = lambda: fired.append(True)
    core.set_wakeword_enabled(True)

    core._wakeword.fire()  # the wake word was heard
    assert fired == [True]


def test_disabling_wakeword_stops_listening(tmp_path):
    core, _, _, _, _ = make_core(tmp_path)
    core.set_wakeword_enabled(True)
    core.set_wakeword_enabled(False)
    assert not core._wakeword.is_running


def test_wakeword_enable_without_a_detector_is_a_noop(tmp_path):
    # no wake-word model/deps available → no detector injected
    core = DaemonCore(
        FakeRecorder(tmp_path / "a.wav"),
        FakeTranscriber(), SqliteNoteStore(tmp_path / "n.db", tmp_path / "n"),
        FakeNotifier(),
    )
    core.set_wakeword_enabled(True)  # must not raise
    core.toggle()  # state change also syncs — must not raise


def test_shutdown_aborts_recording(tmp_path):
    core, recorder, _, _, _ = make_core(tmp_path)
    core.toggle()
    core.shutdown()
    assert recorder.aborted
    assert core.state is State.IDLE


def test_read_current_note_plays_the_most_recent(tmp_path):
    moments = iter([datetime(2026, 7, 22, 10, 0, 0),
                    datetime(2026, 7, 22, 11, 0, 0)])
    core, _, _, notes, _ = make_core(tmp_path)
    notes._now = lambda: next(moments)
    notes.save("nota antiga")
    notes.save("nota mais recente")

    core.read_current_note()

    assert core._player.played == ["nota mais recente"]


def test_read_current_note_without_notes_warns(tmp_path):
    core, _, _, _, notifier = make_core(tmp_path)
    core.read_current_note()
    assert notifier.messages == [
        ("TTS", "Nenhuma nota disponível para ler.")
    ]


def test_read_current_note_with_player_error_notifies(tmp_path):
    from tomenotas.domain.errors import PlayerError

    core, _, _, notes, notifier = make_core(
        tmp_path, player_error=PlayerError("Voz do Piper não encontrada: /x")
    )
    notes.save("qualquer")
    core.read_current_note()
    assert notifier.messages == [
        ("Erro", "Voz do Piper não encontrada: /x")
    ]


def test_state_changes_notify_the_observer(tmp_path):
    core, _, _, _, _ = make_core(tmp_path)
    states = []
    core.on_state_change = states.append

    core.toggle()            # idle -> recording
    core.toggle()            # recording -> transcribing
    core.finish_recording()  # transcribing -> idle

    assert states == [State.RECORDING, State.TRANSCRIBING, State.IDLE]


def test_repeated_state_does_not_renotify(tmp_path):
    core, _, _, _, _ = make_core(tmp_path)
    states = []
    core.on_state_change = states.append
    core.shutdown()  # was already IDLE: no notification
    assert states == []


def test_observer_is_notified_on_shutdown_and_start_error(tmp_path):
    core, _, _, _, _ = make_core(tmp_path, fails_on_start=True)
    states = []
    core.on_state_change = states.append
    core.toggle()  # arecord failure: stays IDLE, no notification
    assert states == []

    core2, _, _, _, _ = make_core(tmp_path)
    states2 = []
    core2.on_state_change = states2.append
    core2.toggle()
    core2.shutdown()
    assert states2 == [State.RECORDING, State.IDLE]
