"""Testes de tomenotas.notify."""

import threading

from tomenotas.infra.notify import Notifier


class ProcFalso:
    def __init__(self, saida=""):
        self._saida = saida

    def communicate(self):
        return self._saida, ""


def test_send_usa_o_nome_do_app_tomenotas():
    chamadas = []
    notifier = Notifier(spawn=lambda cmd, **kw: chamadas.append(cmd))
    notifier.send("Título", "Corpo")
    assert chamadas == [
        ["notify-send", "--app-name=Tomenotas", "Título", "Corpo"]
    ]


def test_send_com_acao_dispara_callback_no_clique():
    chamadas = []
    clicou = threading.Event()

    def spawn(cmd, **kwargs):
        chamadas.append((cmd, kwargs))
        return ProcFalso("default\n")  # o usuário clicou na notificação

    notifier = Notifier(spawn=spawn)
    notifier.on_activate = clicou.set
    notifier.send("Nota criada", "olá")

    assert clicou.wait(timeout=2)
    (cmd, kwargs) = chamadas[0]
    assert "--action=default=Abrir" in cmd
    assert kwargs.get("stdout") is not None  # captura a escolha do usuário


def test_notificacao_dispensada_nao_dispara_callback():
    notifier = Notifier(spawn=lambda cmd, **kw: ProcFalso(""))
    cliques = []
    notifier.on_activate = lambda: cliques.append(1)
    notifier._espera_clique(ProcFalso(""))  # fechou sem clicar
    assert cliques == []


def test_notify_send_ausente_degrada_para_stderr(capsys):
    def spawn_quebrado(_cmd, **kwargs):
        raise FileNotFoundError

    notifier = Notifier(spawn=spawn_quebrado)
    notifier.send("Título", "Corpo")  # não deve levantar exceção
    assert "Título: Corpo" in capsys.readouterr().err

    notifier.on_activate = lambda: None
    notifier.send("Título", "Corpo")  # idem no caminho com ação
    assert "Título: Corpo" in capsys.readouterr().err
