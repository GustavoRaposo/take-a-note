"""Tomenotas configuration.

Replaces the old sed-patching done by install.sh: paths come from
~/.config/tomenotas/config.json (written by the installer), with
overrides via environment variables (TOMENOTAS_*) — handy in tests and
debugging.
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("tomenotas.config")

CONFIG_PATH = Path("~/.config/tomenotas/config.json").expanduser()

# .deb install locations (Fase B): when the package is installed, the
# binaries/clients/icons live here and win the home-dir defaults below.
SYSTEM_LIB_DIR = Path("/usr/lib/tomenotas")
SYSTEM_BIN_DIR = Path("/usr/bin")
SYSTEM_SHARE_DIR = Path("/usr/share/tomenotas")


@dataclass(frozen=True)
class Config:
    # None → resolved in __post_init__: system (.deb) paths when
    # installed, otherwise the install.sh home-dir layout
    whisper_bin: Path | None = None
    # None → resolved to models_dir in __post_init__ (models are
    # downloaded on first run; old installs point elsewhere via json)
    whisper_model: Path | None = None
    piper_bin: Path | None = None
    piper_model: Path | None = None
    base_dir: Path = Path.home() / ".local/share/tomenotas"
    bin_dir: Path | None = None
    language: str = "pt"
    # .txt mirror of the notes: opt-in plain-text export (see notes_db)
    mirror_enabled: bool = False
    mirror_dir: Path | None = None  # None → notes_dir in __post_init__
    # critical-notes alarm (app/alarm.py)
    alarm_interval: int = 300  # seconds between notifications
    alarm_sound: Path | None = None  # None → freedesktop default below
    # keyboard-shortcut backend: "auto" | "gsettings" | "portal"
    shortcut_backend: str = "auto"
    # wake word (always-on voice trigger): opt-in, off by default (privacy)
    wakeword_enabled: bool = False
    wakeword_threshold: float = 0.5
    # live transcription (whisper-stream): opt-in preview during recording
    stream_enabled: bool = False
    stream_model: str = "base"  # tiny/base — must keep up in real time

    def __post_init__(self):
        if self.whisper_bin is None:
            system = SYSTEM_LIB_DIR / "whisper-cli"
            object.__setattr__(self, "whisper_bin",
                               system if system.exists() else
                               Path.home() / "whisper.cpp/build/bin/whisper-cli")
        if self.piper_bin is None:
            system = SYSTEM_LIB_DIR / "piper" / "piper"
            object.__setattr__(self, "piper_bin",
                               system if system.exists() else
                               Path.home() / "piper/piper")
        if self.bin_dir is None:
            # where the hotkey clients live (targets of the keybindings)
            system = SYSTEM_BIN_DIR / "tomenotas-hotkey-record"
            object.__setattr__(self, "bin_dir",
                               SYSTEM_BIN_DIR if system.exists() else
                               Path.home() / "tomenotas")
        if self.whisper_model is None:
            object.__setattr__(self, "whisper_model",
                               self.models_dir / "ggml-medium.bin")
        if self.piper_model is None:
            object.__setattr__(self, "piper_model",
                               self.models_dir / "pt_BR-faber-medium.onnx")
        if self.mirror_dir is None:
            object.__setattr__(self, "mirror_dir", self.notes_dir)
        if self.alarm_sound is None:
            object.__setattr__(self, "alarm_sound", Path(
                "/usr/share/sounds/freedesktop/stereo/"
                "alarm-clock-elapsed.oga"
            ))

    @property
    def models_dir(self) -> Path:
        return self.base_dir / "models"

    @property
    def notes_dir(self) -> Path:
        return self.base_dir / "notes"

    @property
    def audio_tmp(self) -> Path:
        return self.base_dir / "tmp_recording.wav"

    @property
    def meeting_tmp(self) -> Path:
        return self.base_dir / "tmp_meeting.wav"

    @property
    def tts_tmp(self) -> Path:
        return self.base_dir / "tmp_tts.wav"

    @property
    def icons_dir(self) -> Path:
        local = self.base_dir / "icons"  # install.sh (venv) layout wins
        if local.is_dir():
            return local
        system = SYSTEM_SHARE_DIR / "icons"  # .deb layout
        return system if system.is_dir() else local

    @property
    def db_path(self) -> Path:
        return self.base_dir / "notes.db"

    @property
    def whisper_stream_bin(self) -> Path:
        # the live-transcription binary sits next to whisper-cli
        return self.whisper_bin.parent / "whisper-stream"

    @property
    def stream_model_path(self) -> Path:
        return self.models_dir / f"ggml-{self.stream_model}.bin"

    @property
    def wakeword_model_path(self) -> Path:
        # the custom "Tomenotas" wake-word ONNX model; a user-local copy
        # (e.g. a retrain) wins, else the one shipped by the .deb, else the
        # local path as the default (nothing there yet).
        local = self.models_dir / "tomenotas-ww.onnx"
        if local.is_file():
            return local
        system = SYSTEM_SHARE_DIR / "models" / "tomenotas-ww.onnx"
        return system if system.is_file() else local

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Loads the config from json (if present), with env var overrides.

        An invalid json does not take the daemon down: it warns and falls
        back to the defaults (the user can still record).
        """
        path = path or CONFIG_PATH
        data: dict = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log.warning("invalid config at %s, using defaults", path)
                data = {}

        default = cls()

        def path_for(key: str, env_var: str,
                     default_value: Path | None) -> Path | None:
            raw = os.environ.get(env_var) or data.get(key)
            return Path(raw).expanduser() if raw else default_value

        return cls(
            whisper_bin=path_for(
                "whisper_bin", "TOMENOTAS_WHISPER_BIN", default.whisper_bin
            ),
            # None → __post_init__ derives from the loaded base_dir
            whisper_model=path_for(
                "whisper_model", "TOMENOTAS_WHISPER_MODEL", None
            ),
            piper_bin=path_for("piper_bin", "TOMENOTAS_PIPER_BIN", default.piper_bin),
            piper_model=path_for(
                "piper_model", "TOMENOTAS_PIPER_MODEL", None
            ),
            base_dir=path_for("base_dir", "TOMENOTAS_BASE_DIR", default.base_dir),
            bin_dir=path_for("bin_dir", "TOMENOTAS_BIN_DIR", default.bin_dir),
            language=os.environ.get("TOMENOTAS_LANGUAGE")
            or data.get("language")
            or default.language,
            mirror_enabled=bool(data.get("mirror_enabled", False)),
            mirror_dir=path_for("mirror_dir", "TOMENOTAS_MIRROR_DIR", None),
            alarm_interval=_int_or(data.get("alarm_interval"), 300),
            alarm_sound=path_for("alarm_sound", "TOMENOTAS_ALARM_SOUND",
                                 None),
            shortcut_backend=_one_of(
                os.environ.get("TOMENOTAS_SHORTCUT_BACKEND")
                or data.get("shortcut_backend"),
                ("auto", "gsettings", "portal"), "auto",
            ),
            stream_enabled=bool(data.get("stream_enabled", False)),
            stream_model=_one_of(data.get("stream_model"),
                                 ("tiny", "base"), "base"),
            wakeword_enabled=bool(data.get("wakeword_enabled", False)),
            wakeword_threshold=_float_or(data.get("wakeword_threshold"), 0.5),
        )


def _one_of(raw, allowed: tuple, default: str) -> str:
    return raw if raw in allowed else default


def _int_or(raw, default: int) -> int:
    try:
        value = int(raw)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _float_or(raw, default: float) -> float:
    try:
        value = float(raw)
        return value if 0.0 < value <= 1.0 else default
    except (TypeError, ValueError):
        return default


def update_config_file(key: str, value: str | bool | int,
                       path: Path | None = None) -> None:
    """Sets a single key in config.json, preserving the other keys
    (creating the file if needed). Invalid content is rewritten with a
    warning — the same tolerance Config.load has when reading."""
    path = path or CONFIG_PATH
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("invalid config at %s, rewriting", path)
            data = {}
    if not isinstance(data, dict):
        data = {}
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
