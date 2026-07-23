"""Testes de tomenotas.recorder."""

import signal
import subprocess

import pytest

from tomenotas.domain.errors import RecorderError
from tomenotas.infra.recorder import Recorder


class ProcessoFalso:
    """Simula um Popen do arecord."""

    def __init__(self, trava_no_wait=False, ja_morto=False):
        self.sinais = []
        self.morto = False
        self.encerrado = False
        self._trava_no_wait = trava_no_wait
        self._ja_morto = ja_morto
        self._esperas = 0

    def poll(self):
        return 0 if self.encerrado else None

    def send_signal(self, sig):
        if self._ja_morto:
            raise ProcessLookupError
        self.sinais.append(sig)

    def wait(self, timeout=None):
        self._esperas += 1
        # trava só na primeira espera (a com timeout); depois do kill, retorna
        if self._trava_no_wait and self._esperas == 1:
            raise subprocess.TimeoutExpired(cmd="arecord", timeout=timeout)
        self.encerrado = True
        return 0

    def kill(self):
        self.morto = True


def fabrica(proc, chamadas=None):
    def popen(cmd):
        if chamadas is not None:
            chamadas.append(cmd)
        return proc
    return popen


def test_start_invoca_arecord_e_cria_diretorio(tmp_path):
    tmp = tmp_path / "sub" / "tmp_recording.wav"
    chamadas = []
    recorder = Recorder(tmp, popen=fabrica(ProcessoFalso(), chamadas))
    recorder.start()
    assert chamadas == [["arecord", "-f", "cd", "-t", "wav", str(tmp)]]
    assert tmp.parent.is_dir()
    assert recorder.is_recording


def test_start_duplo_levanta_erro(tmp_path):
    recorder = Recorder(tmp_path / "a.wav", popen=fabrica(ProcessoFalso()))
    recorder.start()
    with pytest.raises(RecorderError):
        recorder.start()


def test_start_propaga_arecord_ausente(tmp_path):
    def popen_quebrado(_cmd):
        raise FileNotFoundError

    recorder = Recorder(tmp_path / "a.wav", popen=popen_quebrado)
    with pytest.raises(FileNotFoundError):
        recorder.start()
    assert not recorder.is_recording


def test_stop_envia_sigint_e_espera(tmp_path):
    proc = ProcessoFalso()
    recorder = Recorder(tmp_path / "a.wav", popen=fabrica(proc))
    recorder.start()
    recorder.stop()
    assert proc.sinais == [signal.SIGINT]
    assert proc.encerrado
    assert not recorder.is_recording


def test_stop_sem_gravacao_levanta_erro(tmp_path):
    recorder = Recorder(tmp_path / "a.wav", popen=fabrica(ProcessoFalso()))
    with pytest.raises(RecorderError):
        recorder.stop()


def test_stop_mata_processo_que_nao_encerra(tmp_path):
    proc = ProcessoFalso(trava_no_wait=True)
    recorder = Recorder(tmp_path / "a.wav", popen=fabrica(proc))
    recorder.start()
    recorder.stop(timeout=0.01)
    assert proc.morto


def test_stop_tolera_processo_ja_morto(tmp_path):
    proc = ProcessoFalso(ja_morto=True)
    recorder = Recorder(tmp_path / "a.wav", popen=fabrica(proc))
    recorder.start()
    recorder.stop()  # não deve levantar exceção
    assert not recorder.is_recording


def test_abort_para_gravacao_e_remove_tmp(tmp_path):
    tmp = tmp_path / "a.wav"
    tmp.write_bytes(b"RIFF")
    proc = ProcessoFalso()
    recorder = Recorder(tmp, popen=fabrica(proc))
    recorder.start()
    recorder.abort()
    assert proc.sinais == [signal.SIGINT]
    assert not tmp.exists()


def test_abort_sem_gravacao_so_limpa_tmp(tmp_path):
    tmp = tmp_path / "a.wav"
    tmp.write_bytes(b"RIFF")
    recorder = Recorder(tmp, popen=fabrica(ProcessoFalso()))
    recorder.abort()  # não deve levantar exceção
    assert not tmp.exists()
