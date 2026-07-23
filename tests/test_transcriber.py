"""Testes de tomenotas.transcriber."""

from pathlib import Path

import pytest

from tomenotas.domain.errors import TranscriptionError
from tomenotas.infra.transcriber import Transcriber


def monta(tmp_path, run):
    """Transcriber com modelo e .wav existentes (o caminho feliz exige)."""
    modelo = tmp_path / "model.bin"
    modelo.write_bytes(b"ggml")
    wav = tmp_path / "tmp_recording.wav"
    wav.write_bytes(b"RIFF")
    return Transcriber(Path("/w/bin"), modelo, language="pt", run=run), wav


def test_transcricao_com_sucesso(tmp_path):
    chamadas = []

    def run_falso(cmd, **kwargs):
        chamadas.append(cmd)
        # o whisper.cpp escreve <out_base>.txt (flag -of + -otxt)
        (tmp_path / "tmp_transcricao.txt").write_text(
            "  olá mundo \n", encoding="utf-8"
        )

    t, wav = monta(tmp_path, run_falso)
    texto = t.transcribe(wav)

    assert texto == "olá mundo"
    assert not (tmp_path / "tmp_transcricao.txt").exists()  # limpou o tmp
    (cmd,) = chamadas
    assert cmd[0] == "/w/bin"
    assert ["-m", str(tmp_path / "model.bin")] == cmd[1:3]
    assert ["-l", "pt"] == cmd[3:5]
    assert ["-f", str(wav)] == cmd[5:7]
    assert ["-nt", "-otxt", "-of", str(tmp_path / "tmp_transcricao")] == cmd[7:]


def test_whisper_sem_saida_levanta_erro(tmp_path):
    t, wav = monta(tmp_path, lambda cmd, **kw: None)
    with pytest.raises(TranscriptionError, match="Falha ao transcrever"):
        t.transcribe(wav)


def test_binario_ausente_levanta_erro(tmp_path):
    def run_quebrado(cmd, **kwargs):
        raise FileNotFoundError

    t, wav = monta(tmp_path, run_quebrado)
    with pytest.raises(TranscriptionError, match="whisper.cpp não encontrado"):
        t.transcribe(wav)


def test_modelo_ausente_tem_mensagem_especifica(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    t = Transcriber(Path("/w/bin"), tmp_path / "nao-baixado.bin",
                    run=lambda cmd, **kw: None)
    with pytest.raises(TranscriptionError, match="Modelo do whisper não encontrado"):
        t.transcribe(wav)


def test_wav_ausente_sugere_verificar_microfone(tmp_path):
    t, wav = monta(tmp_path, lambda cmd, **kw: None)
    wav.unlink()  # o arecord falhou (ex.: sem microfone) e não gerou áudio
    with pytest.raises(TranscriptionError, match="microfone"):
        t.transcribe(wav)
