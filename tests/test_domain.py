"""Testes de tomenotas.domain — regras puras."""

from datetime import datetime

from tomenotas.domain.note import preview
from tomenotas.domain.periodo import periodo_desde


def test_preview_trunca_em_60_caracteres():
    assert preview("a" * 100) == "a" * 60
    assert preview("curta") == "curta"


def test_periodo_desde_traduz_os_atalhos_da_ui():
    agora = datetime(2026, 7, 23, 14, 30, 45)
    assert periodo_desde("hoje", agora) == "2026-07-23T00:00:00"
    assert periodo_desde("7dias", agora) == "2026-07-16T14:30:45"
    assert periodo_desde("30dias", agora) == "2026-06-23T14:30:45"
    assert periodo_desde("", agora) is None
    assert periodo_desde("qualquer-coisa", agora) is None


def test_periodo_desde_sem_relogio_usa_agora():
    assert periodo_desde("hoje").endswith("T00:00:00")
