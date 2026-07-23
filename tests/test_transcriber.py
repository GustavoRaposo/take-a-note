"""Tests for tomenotas.infra.transcriber."""

from pathlib import Path

import pytest

from tomenotas.domain.errors import TranscriptionError
from tomenotas.infra.transcriber import Transcriber


def make(tmp_path, run):
    """Transcriber with an existing model and .wav (the happy path needs
    both)."""
    model = tmp_path / "model.bin"
    model.write_bytes(b"ggml")
    wav = tmp_path / "tmp_recording.wav"
    wav.write_bytes(b"RIFF")
    return Transcriber(Path("/w/bin"), model, language="pt", run=run), wav


def test_successful_transcription(tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # whisper.cpp writes <out_base>.txt (flags -of + -otxt)
        (tmp_path / "tmp_transcricao.txt").write_text(
            "  olá mundo \n", encoding="utf-8"
        )

    t, wav = make(tmp_path, fake_run)
    text = t.transcribe(wav)

    assert text == "olá mundo"
    assert not (tmp_path / "tmp_transcricao.txt").exists()  # tmp cleaned
    (cmd,) = calls
    assert cmd[0] == "/w/bin"
    assert ["-m", str(tmp_path / "model.bin")] == cmd[1:3]
    assert ["-l", "pt"] == cmd[3:5]
    assert ["-f", str(wav)] == cmd[5:7]
    assert ["-nt", "-otxt", "-of", str(tmp_path / "tmp_transcricao")] == cmd[7:]


def test_whisper_without_output_raises(tmp_path):
    t, wav = make(tmp_path, lambda cmd, **kw: None)
    with pytest.raises(TranscriptionError, match="Falha ao transcrever"):
        t.transcribe(wav)


def test_missing_binary_raises(tmp_path):
    def broken_run(cmd, **kwargs):
        raise FileNotFoundError

    t, wav = make(tmp_path, broken_run)
    with pytest.raises(TranscriptionError, match="whisper.cpp não encontrado"):
        t.transcribe(wav)


def test_missing_model_has_specific_message(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    t = Transcriber(Path("/w/bin"), tmp_path / "not-downloaded.bin",
                    run=lambda cmd, **kw: None)
    with pytest.raises(TranscriptionError, match="Modelo do whisper não encontrado"):
        t.transcribe(wav)


def test_is_ready_reflects_model_presence(tmp_path):
    t, _ = make(tmp_path, lambda cmd, **kw: None)
    assert t.is_ready()
    missing = Transcriber(Path("/w/bin"), tmp_path / "nao-baixado.bin")
    assert not missing.is_ready()


def test_set_model_switches_the_model_used_by_transcribe(tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        (tmp_path / "tmp_transcricao.txt").write_text("oi", encoding="utf-8")

    t, wav = make(tmp_path, fake_run)
    other = tmp_path / "ggml-small.bin"
    other.write_bytes(b"ggml")

    t.set_model(other)
    t.transcribe(wav)

    (cmd,) = calls
    assert cmd[cmd.index("-m") + 1] == str(other)


def test_missing_wav_suggests_checking_the_microphone(tmp_path):
    t, wav = make(tmp_path, lambda cmd, **kw: None)
    wav.unlink()  # arecord failed (e.g. no microphone), no audio produced
    with pytest.raises(TranscriptionError, match="microfone"):
        t.transcribe(wav)
