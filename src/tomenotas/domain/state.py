"""Estados do daemon e o mapeamento estado → ícone/tooltip da bandeja.

Os nomes de ícone referem-se aos SVGs em assets/icons/ (instalados pelo
install.sh em ~/.local/share/tomenotas/icons/). AppIndicator não anima
ícones, então o efeito de "pulsar" é simulado alternando entre a variante
forte e a apagada a cada tick (GLib.timeout_add na cola).
"""

from enum import Enum, auto


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    TRANSCRIBING = auto()


class ToggleAction(Enum):
    """O que o toggle fez — a cola usa isso para decidir o próximo passo
    (STOP_REQUESTED → rodar finish_recording() numa thread)."""

    STARTED = auto()
    STOP_REQUESTED = auto()
    BUSY = auto()
    FAILED = auto()


# estado -> (ícone principal, variante apagada do pulso ou None, tooltip)
_INFO = {
    State.IDLE: ("tomenotas-idle", None, "Ocioso"),
    State.RECORDING: (
        "tomenotas-recording", "tomenotas-recording-dim", "Gravando...",
    ),
    State.TRANSCRIBING: (
        "tomenotas-transcribing", "tomenotas-transcribing-dim",
        "Transcrevendo...",
    ),
}


def icone(estado: State) -> str:
    return _INFO[estado][0]


def tooltip(estado: State) -> str:
    return _INFO[estado][2]


def pulsa(estado: State) -> bool:
    return _INFO[estado][1] is not None


class Pulsador:
    """Alterna forte/apagado a cada chamada; estados sem pulso resetam."""

    def __init__(self):
        self._apagado = False

    def proximo(self, estado: State) -> str:
        principal, apagado, _ = _INFO[estado]
        if apagado is None:
            self._apagado = False
            return principal
        self._apagado = not self._apagado
        return apagado if self._apagado else principal
