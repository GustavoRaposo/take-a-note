"""Domain exceptions — their messages are shown to the user as-is
(hence in Portuguese)."""


class RecorderError(Exception):
    pass


class TranscriptionError(Exception):
    pass


class PlayerError(Exception):
    pass


class MigrationError(Exception):
    pass


class DownloadError(Exception):
    pass
