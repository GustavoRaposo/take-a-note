"""Tests for tomenotas.infra.notify."""

import threading

from tomenotas.infra.notify import Notifier


class FakeProc:
    def __init__(self, out=""):
        self._out = out

    def communicate(self):
        return self._out, ""


def test_send_uses_the_tomenotas_app_name():
    calls = []
    notifier = Notifier(spawn=lambda cmd, **kw: calls.append(cmd))
    notifier.send("Título", "Corpo")
    assert calls == [
        ["notify-send", "--app-name=Tomenotas", "Título", "Corpo"]
    ]


def test_send_includes_the_icon_when_set():
    calls = []
    notifier = Notifier(spawn=lambda cmd, **kw: calls.append(cmd),
                        icon="/x/icons/tomenotas-idle.svg")
    notifier.send("Título", "Corpo")
    assert calls == [[
        "notify-send", "--app-name=Tomenotas",
        "--icon=/x/icons/tomenotas-idle.svg", "Título", "Corpo",
    ]]


def test_send_with_action_fires_callback_on_click():
    calls = []
    clicked = threading.Event()

    def spawn(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return FakeProc("default\n")  # the user clicked the notification

    notifier = Notifier(spawn=spawn)
    notifier.on_activate = clicked.set
    notifier.send("Nota criada", "olá")

    assert clicked.wait(timeout=2)
    (cmd, kwargs) = calls[0]
    assert "--action=default=Abrir" in cmd
    assert kwargs.get("stdout") is not None  # captures the user's choice


def test_dismissed_notification_does_not_fire_callback():
    notifier = Notifier(spawn=lambda cmd, **kw: FakeProc(""))
    clicks = []
    notifier.on_activate = lambda: clicks.append(1)
    notifier._wait_click(FakeProc(""))  # closed without clicking
    assert clicks == []


def test_missing_notify_send_degrades_to_stderr(capsys):
    def broken_spawn(_cmd, **kwargs):
        raise FileNotFoundError

    notifier = Notifier(spawn=broken_spawn)
    notifier.send("Título", "Corpo")  # must not raise
    assert "Título: Corpo" in capsys.readouterr().err

    notifier.on_activate = lambda: None
    notifier.send("Título", "Corpo")  # same on the action path
    assert "Título: Corpo" in capsys.readouterr().err
