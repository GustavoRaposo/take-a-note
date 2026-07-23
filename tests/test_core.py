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


def make_core(tmp_path, fails_on_start=False, transcription_error=None,
              text="texto transcrito", player_error=None, ready=True):
    audio_tmp = tmp_path / "tmp_recording.wav"
    recorder = FakeRecorder(audio_tmp, fails_on_start=fails_on_start)
    transcriber = FakeTranscriber(text=text, error=transcription_error,
                                  ready=ready)
    notes = SqliteNoteStore(tmp_path / "notes.db", tmp_path / "notes",
                            now=lambda: datetime(2026, 7, 22, 15, 0, 38))
    notifier = FakeNotifier()
    core = DaemonCore(recorder, transcriber, notes, notifier,
                      player=FakePlayer(error=player_error))
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
    note = notes.notes_dir / "2026-07-22_15-00-38.txt"
    assert note.read_text(encoding="utf-8") == "conteúdo da nota gravada"
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
