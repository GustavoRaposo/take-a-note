"""Testes de tomenotas.core — a máquina de estados do daemon."""

from datetime import datetime
from pathlib import Path

from tomenotas.app.core import DaemonCore
from tomenotas.domain.errors import TranscriptionError
from tomenotas.domain.state import State, ToggleAction
from tomenotas.infra.notes_db import SqliteNoteStore


class RecorderFalso:
    def __init__(self, audio_tmp: Path, falha_no_start=False):
        self.audio_tmp = audio_tmp
        self.falha_no_start = falha_no_start
        self.iniciado = False
        self.parado = False
        self.abortado = False

    def start(self):
        if self.falha_no_start:
            raise FileNotFoundError
        self.iniciado = True

    def stop(self):
        self.parado = True

    def abort(self):
        self.abortado = True


class TranscriberFalso:
    def __init__(self, texto="texto transcrito", erro=None):
        self.texto = texto
        self.erro = erro
        self.transcreveu = []

    def transcribe(self, wav_path):
        self.transcreveu.append(wav_path)
        if self.erro:
            raise self.erro
        return self.texto


class NotifierFalso:
    def __init__(self):
        self.mensagens = []

    def send(self, titulo, corpo):
        self.mensagens.append((titulo, corpo))


def monta_core(tmp_path, falha_no_start=False, erro_transcricao=None,
               texto="texto transcrito"):
    audio_tmp = tmp_path / "tmp_recording.wav"
    recorder = RecorderFalso(audio_tmp, falha_no_start=falha_no_start)
    transcriber = TranscriberFalso(texto=texto, erro=erro_transcricao)
    notes = SqliteNoteStore(tmp_path / "notes.db", tmp_path / "notes",
                            now=lambda: datetime(2026, 7, 22, 15, 0, 38))
    notifier = NotifierFalso()
    core = DaemonCore(recorder, transcriber, notes, notifier)
    return core, recorder, transcriber, notes, notifier


def test_toggle_ocioso_inicia_gravacao(tmp_path):
    core, recorder, _, _, notifier = monta_core(tmp_path)
    acao = core.toggle()
    assert acao is ToggleAction.STARTED
    assert core.state is State.RECORDING
    assert recorder.iniciado
    assert notifier.mensagens == [
        ("Gravação", "Gravando... aperte o atalho de novo para parar.")
    ]


def test_toggle_sem_arecord_avisa_e_continua_ocioso(tmp_path):
    core, _, _, _, notifier = monta_core(tmp_path, falha_no_start=True)
    acao = core.toggle()
    assert acao is ToggleAction.FAILED
    assert core.state is State.IDLE
    assert notifier.mensagens == [
        ("Erro", "arecord não encontrado. Instale o pacote alsa-utils.")
    ]


def test_toggle_gravando_pede_parada(tmp_path):
    core, _, _, _, notifier = monta_core(tmp_path)
    core.toggle()
    acao = core.toggle()
    assert acao is ToggleAction.STOP_REQUESTED
    assert core.state is State.TRANSCRIBING
    assert notifier.mensagens[-1] == ("Gravação", "Transcrevendo...")


def test_toggle_durante_transcricao_e_ignorado(tmp_path):
    core, recorder, _, _, notifier = monta_core(tmp_path)
    core.toggle()
    core.toggle()
    acao = core.toggle()
    assert acao is ToggleAction.BUSY
    assert core.state is State.TRANSCRIBING
    assert notifier.mensagens[-1] == (
        "Gravação", "Aguarde: ainda transcrevendo a nota anterior."
    )


def test_finish_salva_nota_e_volta_a_ocioso(tmp_path):
    core, recorder, transcriber, notes, notifier = monta_core(
        tmp_path, texto="conteúdo da nota gravada"
    )
    recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle()
    core.toggle()

    core.finish_recording()

    assert recorder.parado
    assert transcriber.transcreveu == [recorder.audio_tmp]
    nota = notes.notes_dir / "2026-07-22_15-00-38.txt"
    assert nota.read_text(encoding="utf-8") == "conteúdo da nota gravada"
    assert notifier.mensagens[-1] == ("Nota criada", "conteúdo da nota gravada")
    assert not recorder.audio_tmp.exists()  # .wav temporário apagado
    assert core.state is State.IDLE


def test_finish_com_preview_truncado(tmp_path):
    texto = "x" * 100
    core, _, _, _, notifier = monta_core(tmp_path, texto=texto)
    core.toggle()
    core.toggle()
    core.finish_recording()
    assert notifier.mensagens[-1] == ("Nota criada", "x" * 60)


def test_finish_com_erro_notifica_e_volta_a_ocioso(tmp_path):
    core, recorder, _, notes, notifier = monta_core(
        tmp_path, erro_transcricao=TranscriptionError("Falha ao transcrever o áudio.")
    )
    recorder.audio_tmp.write_bytes(b"RIFF")
    core.toggle()
    core.toggle()

    core.finish_recording()

    assert notifier.mensagens[-1] == ("Erro", "Falha ao transcrever o áudio.")
    assert not notes.notes_dir.exists()  # nenhuma nota criada
    assert not recorder.audio_tmp.exists()  # tmp limpo mesmo com erro
    assert core.state is State.IDLE


def test_shutdown_aborta_gravacao(tmp_path):
    core, recorder, _, _, _ = monta_core(tmp_path)
    core.toggle()
    core.shutdown()
    assert recorder.abortado
    assert core.state is State.IDLE


def test_mudancas_de_estado_notificam_o_observador(tmp_path):
    core, _, _, _, _ = monta_core(tmp_path)
    estados = []
    core.on_state_change = estados.append

    core.toggle()            # idle -> recording
    core.toggle()            # recording -> transcribing
    core.finish_recording()  # transcribing -> idle

    assert estados == [State.RECORDING, State.TRANSCRIBING, State.IDLE]


def test_estado_repetido_nao_renotifica(tmp_path):
    core, _, _, _, _ = monta_core(tmp_path)
    estados = []
    core.on_state_change = estados.append
    core.shutdown()  # já estava IDLE: nenhuma notificação
    assert estados == []


def test_observador_e_notificado_no_shutdown_e_no_erro_de_start(tmp_path):
    core, _, _, _, _ = monta_core(tmp_path, falha_no_start=True)
    estados = []
    core.on_state_change = estados.append
    core.toggle()  # falha no arecord: permanece IDLE, sem notificação
    assert estados == []

    core2, _, _, _, _ = monta_core(tmp_path)
    estados2 = []
    core2.on_state_change = estados2.append
    core2.toggle()
    core2.shutdown()
    assert estados2 == [State.RECORDING, State.IDLE]
