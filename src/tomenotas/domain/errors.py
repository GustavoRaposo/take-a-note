"""Exceções do domínio — as mensagens são exibidas ao usuário como estão."""


class RecorderError(Exception):
    pass


class TranscriptionError(Exception):
    pass


class PlayerError(Exception):
    pass


class MigrationError(Exception):
    pass
