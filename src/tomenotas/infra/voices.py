"""Piper voice management (switchable through the Configurações UI).

A voice is a .onnx file living in the same directory as the active
model (install.sh puts them in ~/piper/). Switching a voice applies
immediately to the injected Player (next play() uses it) and persists
`piper_model` in config.json, preserving the other keys written by
install.sh.
"""

import logging
from pathlib import Path

from .config import CONFIG_PATH, update_config_file
from .downloads import download_voice

log = logging.getLogger("tomenotas.voices")


class VoiceManager:
    def __init__(self, player, piper_model: Path,
                 config_path: Path | None = None):
        self._player = player
        self._current = Path(piper_model)
        self._config_path = Path(config_path) if config_path else CONFIG_PATH

    @property
    def voices_dir(self) -> Path:
        return self._current.parent

    def list_voices(self) -> list[str]:
        """Stems of the installed .onnx files (their .onnx.json
        companions are not voices)."""
        if not self.voices_dir.is_dir():
            return []
        return sorted(p.stem for p in self.voices_dir.glob("*.onnx"))

    def current_voice(self) -> str:
        return self._current.stem

    def set_voice(self, name: str) -> None:
        """Switches the active voice: applies to the player right away
        and persists in config.json. Raises ValueError (message shown to
        the user) if the .onnx does not exist."""
        path = self.voices_dir / f"{name}.onnx"
        if not path.is_file():
            raise ValueError(f"Voz não encontrada: {path}")
        self._current = path
        self._player.set_model(path)
        update_config_file("piper_model", str(path), self._config_path)
        log.info("voice switched to %s", name)

    def download_default(self, downloader, on_progress=None) -> str:
        """First-run helper: downloads the default pt_BR voice pair into
        voices_dir and activates it. Returns the voice name."""
        path = download_voice(downloader, self.voices_dir,
                              on_progress=on_progress)
        self.set_voice(path.stem)
        return path.stem
