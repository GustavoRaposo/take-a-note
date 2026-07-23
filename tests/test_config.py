"""Testes de tomenotas.config."""

import json
from pathlib import Path

from tomenotas.infra.config import Config


def test_padroes_derivam_de_base_dir():
    cfg = Config(base_dir=Path("/x/dados"))
    assert cfg.notes_dir == Path("/x/dados/notes")
    assert cfg.audio_tmp == Path("/x/dados/tmp_recording.wav")
    assert cfg.tts_tmp == Path("/x/dados/tmp_tts.wav")
    assert cfg.icons_dir == Path("/x/dados/icons")
    assert cfg.db_path == Path("/x/dados/notes.db")
    assert cfg.language == "pt"


def test_padroes_do_piper():
    cfg = Config()
    assert cfg.piper_bin == Path.home() / "piper/piper"
    assert cfg.piper_model == Path.home() / "piper/pt_BR-faber-medium.onnx"


def test_bin_dir_padrao_e_override(tmp_path, monkeypatch):
    assert Config().bin_dir == Path.home() / "bin"
    monkeypatch.setenv("TOMENOTAS_BIN_DIR", "/opt/bin")
    assert Config.load(tmp_path / "nada.json").bin_dir == Path("/opt/bin")


def test_load_sem_arquivo_usa_padroes(tmp_path):
    cfg = Config.load(tmp_path / "inexistente.json")
    assert cfg == Config()


def test_load_le_caminhos_do_json(tmp_path):
    arquivo = tmp_path / "config.json"
    arquivo.write_text(json.dumps({
        "whisper_bin": "/opt/whisper/main",
        "whisper_model": "/opt/whisper/ggml-small.bin",
        "piper_bin": "/opt/piper/piper",
        "piper_model": "/opt/piper/voz.onnx",
        "base_dir": str(tmp_path / "dados"),
        "language": "en",
    }))
    cfg = Config.load(arquivo)
    assert cfg.whisper_bin == Path("/opt/whisper/main")
    assert cfg.whisper_model == Path("/opt/whisper/ggml-small.bin")
    assert cfg.piper_bin == Path("/opt/piper/piper")
    assert cfg.piper_model == Path("/opt/piper/voz.onnx")
    assert cfg.base_dir == tmp_path / "dados"
    assert cfg.language == "en"


def test_load_expande_til_no_json(tmp_path):
    arquivo = tmp_path / "config.json"
    arquivo.write_text(json.dumps({"whisper_bin": "~/w/main"}))
    cfg = Config.load(arquivo)
    assert cfg.whisper_bin == Path.home() / "w/main"


def test_env_tem_precedencia_sobre_o_json(tmp_path, monkeypatch):
    arquivo = tmp_path / "config.json"
    arquivo.write_text(json.dumps({
        "whisper_bin": "/do/json",
        "language": "en",
    }))
    monkeypatch.setenv("TOMENOTAS_WHISPER_BIN", "/do/env")
    monkeypatch.setenv("TOMENOTAS_PIPER_BIN", "/do/env/piper")
    monkeypatch.setenv("TOMENOTAS_LANGUAGE", "es")
    cfg = Config.load(arquivo)
    assert cfg.whisper_bin == Path("/do/env")
    assert cfg.piper_bin == Path("/do/env/piper")
    assert cfg.language == "es"


def test_json_invalido_avisa_e_usa_padroes(tmp_path, caplog):
    arquivo = tmp_path / "config.json"
    arquivo.write_text("{ nada a ver")
    cfg = Config.load(arquivo)
    assert cfg == Config()
    assert "config inválida" in caplog.text
