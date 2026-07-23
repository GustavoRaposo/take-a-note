"""Configuração do Tomenotas.

Substitui o antigo patch via sed do install.sh: os caminhos vêm de
~/.config/tomenotas/config.json (escrito pelo instalador), com override
por variáveis de ambiente (TOMENOTAS_*) — útil em testes e debug.
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("tomenotas.config")

CONFIG_PATH = Path("~/.config/tomenotas/config.json").expanduser()


@dataclass(frozen=True)
class Config:
    whisper_bin: Path = Path.home() / "whisper.cpp/build/bin/whisper-cli"
    whisper_model: Path = Path.home() / "whisper.cpp/models/ggml-medium.bin"
    piper_bin: Path = Path.home() / "piper/piper"
    piper_model: Path = Path.home() / "piper/pt_BR-faber-medium.onnx"
    base_dir: Path = Path.home() / ".local/share/tomenotas"
    bin_dir: Path = Path.home() / "bin"
    language: str = "pt"

    @property
    def notes_dir(self) -> Path:
        return self.base_dir / "notes"

    @property
    def audio_tmp(self) -> Path:
        return self.base_dir / "tmp_recording.wav"

    @property
    def tts_tmp(self) -> Path:
        return self.base_dir / "tmp_tts.wav"

    @property
    def icons_dir(self) -> Path:
        return self.base_dir / "icons"

    @property
    def db_path(self) -> Path:
        return self.base_dir / "notes.db"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Carrega a config do json (se existir), com override por env vars.

        Um json inválido não derruba o daemon: avisa no stderr e usa os
        padrões (o usuário ainda consegue gravar).
        """
        path = path or CONFIG_PATH
        data: dict = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log.warning("config inválida em %s, usando padrões", path)
                data = {}

        padrao = cls()

        def caminho(chave: str, env_var: str, valor_padrao: Path) -> Path:
            bruto = os.environ.get(env_var) or data.get(chave)
            return Path(bruto).expanduser() if bruto else valor_padrao

        return cls(
            whisper_bin=caminho(
                "whisper_bin", "TOMENOTAS_WHISPER_BIN", padrao.whisper_bin
            ),
            whisper_model=caminho(
                "whisper_model", "TOMENOTAS_WHISPER_MODEL", padrao.whisper_model
            ),
            piper_bin=caminho("piper_bin", "TOMENOTAS_PIPER_BIN", padrao.piper_bin),
            piper_model=caminho(
                "piper_model", "TOMENOTAS_PIPER_MODEL", padrao.piper_model
            ),
            base_dir=caminho("base_dir", "TOMENOTAS_BASE_DIR", padrao.base_dir),
            bin_dir=caminho("bin_dir", "TOMENOTAS_BIN_DIR", padrao.bin_dir),
            language=os.environ.get("TOMENOTAS_LANGUAGE")
            or data.get("language")
            or padrao.language,
        )
