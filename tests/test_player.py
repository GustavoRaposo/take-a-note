"""Testes de tomenotas.player — síntese TTS (Piper) + reprodução (paplay)."""

from pathlib import Path

import pytest

from tomenotas.domain.errors import PlayerError
from tomenotas.infra.player import Player


class PaplayFalso:
    def __init__(self):
        self.terminado = False
        self.encerrou = False

    def poll(self):
        return 0 if self.terminado else None

    def terminate(self):
        self.encerrou = True
        self.terminado = True

    def wait(self, timeout=None):
        return 0


def monta_player(tmp_path, sintetiza=True, piper_ausente=False,
                 paplay_ausente=False, voz_ausente=False):
    tts_tmp = tmp_path / "tmp_tts.wav"
    voz = tmp_path / "voz.onnx"
    if not voz_ausente:
        voz.write_bytes(b"onnx")
    execucoes = []
    spawns = []
    paplay = PaplayFalso()

    def run_falso(cmd, **kwargs):
        execucoes.append((cmd, kwargs))
        if piper_ausente:
            raise FileNotFoundError
        if sintetiza:
            tts_tmp.write_bytes(b"RIFFdados")

    def popen_falso(cmd):
        spawns.append(cmd)
        if paplay_ausente:
            raise FileNotFoundError
        return paplay

    player = Player(
        Path("/p/piper"), voz, tts_tmp,
        run=run_falso, popen=popen_falso,
    )
    return player, execucoes, spawns, paplay, tts_tmp


def test_play_sintetiza_e_toca(tmp_path):
    player, execucoes, spawns, _, tts_tmp = monta_player(tmp_path)
    player.play("olá mundo")

    (cmd, kwargs) = execucoes[0]
    assert cmd == ["/p/piper", "--model", str(tmp_path / "voz.onnx"),
                   "--output_file", str(tts_tmp)]
    assert kwargs["input"] == "olá mundo".encode()
    assert spawns == [["paplay", str(tts_tmp)]]
    assert player.is_playing


def test_play_com_texto_vazio_levanta_erro(tmp_path):
    player, execucoes, _, _, _ = monta_player(tmp_path)
    with pytest.raises(PlayerError, match="nota está vazia"):
        player.play("   \n")
    assert execucoes == []  # nem chegou a chamar o piper


def test_piper_ausente_levanta_erro(tmp_path):
    player, _, _, _, _ = monta_player(tmp_path, piper_ausente=True)
    with pytest.raises(PlayerError, match="Piper não encontrado"):
        player.play("texto")
    assert not player.is_playing


def test_voz_ausente_tem_mensagem_especifica(tmp_path):
    player, execucoes, _, _, _ = monta_player(tmp_path, voz_ausente=True)
    with pytest.raises(PlayerError, match="Voz do Piper não encontrada"):
        player.play("texto")
    assert execucoes == []  # nem tentou sintetizar


def test_sintese_sem_saida_levanta_erro(tmp_path):
    player, _, _, _, _ = monta_player(tmp_path, sintetiza=False)
    with pytest.raises(PlayerError, match="Falha ao sintetizar"):
        player.play("texto")


def test_paplay_ausente_levanta_erro_e_limpa_tmp(tmp_path):
    player, _, _, _, tts_tmp = monta_player(tmp_path, paplay_ausente=True)
    with pytest.raises(PlayerError, match="paplay não encontrado"):
        player.play("texto")
    assert not tts_tmp.exists()
    assert not player.is_playing


def test_stop_encerra_reproducao_e_limpa_tmp(tmp_path):
    player, _, _, paplay, tts_tmp = monta_player(tmp_path)
    player.play("texto")
    player.stop()
    assert paplay.encerrou
    assert not player.is_playing
    assert not tts_tmp.exists()


def test_stop_sem_reproducao_nao_levanta_erro(tmp_path):
    player, _, _, _, _ = monta_player(tmp_path)
    player.stop()  # não deve levantar exceção


def test_play_durante_reproducao_para_a_anterior(tmp_path):
    player, _, spawns, paplay, _ = monta_player(tmp_path)
    player.play("primeira")
    player.play("segunda")
    assert paplay.encerrou  # a primeira reprodução foi parada
    assert len(spawns) == 2


def test_is_playing_reflete_fim_da_reproducao(tmp_path):
    player, _, _, paplay, _ = monta_player(tmp_path)
    player.play("texto")
    assert player.is_playing
    paplay.terminado = True
    assert not player.is_playing
