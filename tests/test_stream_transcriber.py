"""Tests for tomenotas.infra.stream_transcriber — live preview via
whisper-stream.

The pure parser (which turns whisper-stream's stdout — where a window is
overwritten with \\r/ANSI and finalized with \\n — into growing text) is
tested directly; the subprocess pump is tested with a fake stdout, and
the lifecycle with an injected popen. The real binary needs SDL2 + a mic,
validated manually."""

import subprocess

from tomenotas.infra.stream_transcriber import (
    StreamOutputParser,
    StreamTranscriber,
)


# ---------------- parser ----------------

def test_newline_commits_lines_and_text_grows():
    p = StreamOutputParser()
    assert p.feed("olá mundo\n") == "olá mundo"
    assert p.feed("como vai\n") == "olá mundo\ncomo vai"


def test_partial_line_without_newline_is_shown():
    p = StreamOutputParser()
    assert p.feed("olá mun") == "olá mun"
    assert p.feed("do\n") == "olá mundo"


def test_carriage_return_overwrites_the_current_line():
    p = StreamOutputParser()
    p.feed("parcial")
    assert p.feed("\rparcial completo") == "parcial completo"


def test_ansi_clear_line_is_stripped_and_resets_the_line():
    p = StreamOutputParser()
    p.feed("lixo")
    assert p.feed("\033[2Kolá") == "olá"


def test_noise_markers_are_filtered():
    p = StreamOutputParser()
    out = p.feed("[Start speaking]\n"
                 "### Transcription 0 END\n"
                 "conteúdo real\n")
    assert out == "conteúdo real"


def test_timestamp_prefix_is_stripped():
    p = StreamOutputParser()
    out = p.feed("[00:00:00.000 --> 00:00:02.000]   olá mundo\n")
    assert out == "olá mundo"


def test_new_block_replaces_the_preview(tmp_path=None):
    # each "### Transcription N START" re-decodes the whole window, so the
    # latest block replaces the shown text (no cross-block duplication)
    p = StreamOutputParser()
    p.feed("### Transcription 0 START | t0 = 0 ms | t1 = 2000 ms\n")
    assert p.feed("[00:00:00.000 --> 00:00:02.000]   olá\n") == "olá"
    p.feed("### Transcription 1 START | t0 = 0 ms | t1 = 5000 ms\n")
    out = p.feed("[00:00:00.000 --> 00:00:05.000]   olá tudo bem\n")
    assert out == "olá tudo bem"  # replaced, not "olá\nolá tudo bem"


def test_multiple_segments_in_a_block_accumulate():
    p = StreamOutputParser()
    p.feed("### Transcription 2 START | t0 = 0 ms | t1 = 12000 ms\n")
    p.feed("[00:00:00.000 --> 00:00:07.000]   primeira parte\n")
    out = p.feed("[00:00:07.000 --> 00:00:12.000]   segunda parte\n")
    assert out == "primeira parte\nsegunda parte"


def test_parses_the_real_whisper_stream_output():
    # exact stdout captured from the compiled whisper-stream (base, pt-BR)
    real = (
        "[Start speaking]\n\n"
        "### Transcription 0 START | t0 = 0 ms | t1 = 2002 ms\n\n"
        "[00:00:00.000 --> 00:00:02.000]   [MÚSICA DE FUNDO]\n\n"
        "### Transcription 0 END\n\n"
        "### Transcription 1 START | t0 = 0 ms | t1 = 7613 ms\n\n"
        "[00:00:00.000 --> 00:00:07.440]   Olá, isto é um teste de "
        "transcrição ao vivo do Tomenotas funcionando em português.\n\n"
        "### Transcription 1 END\n\n"
    )
    p = StreamOutputParser()
    out = p.feed(real)
    assert out == ("Olá, isto é um teste de transcrição ao vivo do "
                   "Tomenotas funcionando em português.")


def test_empty_and_whitespace_lines_are_dropped():
    p = StreamOutputParser()
    assert p.feed("olá\n\n   \nmundo\n") == "olá\nmundo"


# ---------------- pump (reads stdout → on_text) ----------------

class FakeStdout:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def read(self, _n):
        return self._chunks.pop(0) if self._chunks else ""


def test_pump_feeds_chunks_and_reports_growing_text():
    updates = []
    t = StreamTranscriber("/x/whisper-stream", "/x/ggml-base.bin")
    t._pump(FakeStdout(["olá ", "mundo\n", "tudo bem\n", ""]),
            updates.append)
    assert updates[-1] == "olá mundo\ntudo bem"


# ---------------- lifecycle ----------------

class FakeProc:
    def __init__(self, stdout):
        self.stdout = stdout
        self.terminated = False
        self.killed = False
        self._done = False

    def poll(self):
        return 0 if self._done else None

    def terminate(self):
        self.terminated = True
        self._done = True

    def wait(self, timeout=None):
        self._done = True
        return 0

    def kill(self):
        self.killed = True
        self._done = True


def test_is_ready_checks_binary_and_model(tmp_path):
    (tmp_path / "whisper-stream").write_bytes(b"elf")
    (tmp_path / "ggml-base.bin").write_bytes(b"ggml")
    ready = StreamTranscriber(tmp_path / "whisper-stream",
                              tmp_path / "ggml-base.bin")
    assert ready.is_ready()
    missing = StreamTranscriber(tmp_path / "whisper-stream",
                               tmp_path / "nao-existe.bin")
    assert not missing.is_ready()


def test_start_launches_stream_and_pumps_then_stop_terminates(tmp_path):
    proc = FakeProc(FakeStdout(["ao vivo\n", ""]))
    cmds = []

    def popen(cmd, **kwargs):
        cmds.append(cmd)
        return proc

    updates = []
    t = StreamTranscriber(tmp_path / "whisper-stream",
                          tmp_path / "ggml-base.bin", popen=popen)
    t.start(updates.append)
    t.stop()  # joins the pump thread

    (cmd,) = cmds
    assert cmd[0] == str(tmp_path / "whisper-stream")
    assert "-m" in cmd and str(tmp_path / "ggml-base.bin") in cmd
    # language must be explicit (whisper-stream defaults to English)
    assert cmd[cmd.index("-l") + 1] == "pt"
    assert "-nt" not in cmd  # not a real whisper-stream flag
    assert updates[-1] == "ao vivo"
    assert proc.terminated
    assert not t.is_running


def test_stop_without_start_does_nothing(tmp_path):
    t = StreamTranscriber(tmp_path / "s", tmp_path / "m")
    t.stop()  # must not raise


def test_stop_kills_a_process_that_wont_terminate(tmp_path):
    proc = FakeProc(FakeStdout([""]))

    def hang(timeout=None):
        raise subprocess.TimeoutExpired(cmd="whisper-stream", timeout=timeout)

    proc.wait = hang  # terminate() then wait() times out → kill()
    t = StreamTranscriber(tmp_path / "s", tmp_path / "m",
                          popen=lambda cmd, **kw: proc)
    t.start(lambda _text: None)
    t.stop()
    assert proc.killed


def test_stop_kill_tolerates_process_dying_first(tmp_path):
    proc = FakeProc(FakeStdout([""]))

    def hang(timeout=None):
        raise subprocess.TimeoutExpired(cmd="whisper-stream", timeout=timeout)

    def gone():
        raise ProcessLookupError

    proc.wait = hang   # → kill()
    proc.kill = gone   # kill races with the process dying → swallowed
    t = StreamTranscriber(tmp_path / "s", tmp_path / "m",
                          popen=lambda cmd, **kw: proc)
    t.start(lambda _text: None)
    t.stop()  # must not raise


def test_stop_tolerates_an_already_dead_process(tmp_path):
    proc = FakeProc(FakeStdout([""]))

    def gone():
        raise ProcessLookupError

    proc.terminate = gone  # already dead → ProcessLookupError swallowed
    t = StreamTranscriber(tmp_path / "s", tmp_path / "m",
                          popen=lambda cmd, **kw: proc)
    t.start(lambda _text: None)
    t.stop()  # must not raise
