"""Testes de tomenotas.status — mapeamento estado → ícone/tooltip e pulso."""

from tomenotas.domain.state import Pulsador, State, icone, pulsa, tooltip


def test_icones_por_estado():
    assert icone(State.IDLE) == "tomenotas-idle"
    assert icone(State.RECORDING) == "tomenotas-recording"
    assert icone(State.TRANSCRIBING) == "tomenotas-transcribing"


def test_tooltips_por_estado():
    assert tooltip(State.IDLE) == "Ocioso"
    assert tooltip(State.RECORDING) == "Gravando..."
    assert tooltip(State.TRANSCRIBING) == "Transcrevendo..."


def test_pulsa_somente_em_atividade():
    assert not pulsa(State.IDLE)
    assert pulsa(State.RECORDING)
    assert pulsa(State.TRANSCRIBING)


def test_pulsador_alterna_entre_forte_e_apagado():
    p = Pulsador()
    assert p.proximo(State.RECORDING) == "tomenotas-recording-dim"
    assert p.proximo(State.RECORDING) == "tomenotas-recording"
    assert p.proximo(State.RECORDING) == "tomenotas-recording-dim"


def test_pulsador_em_estado_sem_pulso_reseta_e_devolve_o_principal():
    p = Pulsador()
    p.proximo(State.TRANSCRIBING)  # entra na variante apagada
    assert p.proximo(State.IDLE) == "tomenotas-idle"
    # resetou: a próxima alternância recomeça pela variante apagada
    assert p.proximo(State.RECORDING) == "tomenotas-recording-dim"
