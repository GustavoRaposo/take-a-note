"""Tests for tomenotas.infra.config."""

import json
from pathlib import Path

from tomenotas.infra.config import Config


def test_defaults_derive_from_base_dir(tmp_path, monkeypatch):
    from tomenotas.infra import config as config_mod

    # neutralize the .deb layout: this machine may have it installed
    monkeypatch.setattr(config_mod, "SYSTEM_SHARE_DIR", tmp_path / "nada")
    cfg = Config(base_dir=Path("/x/dados"))
    assert cfg.notes_dir == Path("/x/dados/notes")
    assert cfg.audio_tmp == Path("/x/dados/tmp_recording.wav")
    assert cfg.meeting_tmp == Path("/x/dados/tmp_meeting.wav")
    assert cfg.tts_tmp == Path("/x/dados/tmp_tts.wav")
    assert cfg.icons_dir == Path("/x/dados/icons")
    assert cfg.db_path == Path("/x/dados/notes.db")
    assert cfg.models_dir == Path("/x/dados/models")
    # models live in models_dir by default (downloaded on first run)
    assert cfg.whisper_model == Path("/x/dados/models/ggml-medium.bin")
    assert cfg.piper_model == Path("/x/dados/models/pt_BR-faber-medium.onnx")
    assert cfg.language == "pt"


def test_streaming_defaults():
    cfg = Config()
    assert cfg.stream_enabled is False
    assert cfg.stream_model == "base"
    # stream binary sits next to whisper-cli
    assert cfg.whisper_stream_bin == cfg.whisper_bin.parent / "whisper-stream"


def test_stream_model_path_lives_in_models_dir():
    cfg = Config(base_dir=Path("/x/dados"))
    assert cfg.stream_model_path == Path("/x/dados/models/ggml-base.bin")


def test_load_reads_streaming_settings(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "stream_enabled": True,
        "stream_model": "tiny",
    }))
    cfg = Config.load(config_file)
    assert cfg.stream_enabled is True
    assert cfg.stream_model == "tiny"


def test_load_rejects_unknown_stream_model(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"stream_model": "medium"}))
    # only tiny/base make sense for real-time; anything else → base
    assert Config.load(config_file).stream_model == "base"


def test_shortcut_backend_defaults_to_auto():
    assert Config().shortcut_backend == "auto"


def test_load_reads_shortcut_backend(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"shortcut_backend": "portal"}))
    assert Config.load(config_file).shortcut_backend == "portal"


def test_load_rejects_unknown_shortcut_backend(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"shortcut_backend": "banana"}))
    assert Config.load(config_file).shortcut_backend == "auto"


def test_alarm_defaults():
    cfg = Config()
    assert cfg.alarm_interval == 300  # 5 minutes
    assert cfg.alarm_sound == Path(
        "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
    )


def test_load_reads_alarm_settings(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "alarm_interval": 60,
        "alarm_sound": str(tmp_path / "toque.wav"),
    }))
    cfg = Config.load(config_file)
    assert cfg.alarm_interval == 60
    assert cfg.alarm_sound == tmp_path / "toque.wav"


def test_load_tolerates_bad_alarm_interval(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"alarm_interval": "nada"}))
    assert Config.load(config_file).alarm_interval == 300


def test_mirror_defaults_disabled_with_notes_dir():
    cfg = Config(base_dir=Path("/x/dados"))
    assert cfg.mirror_enabled is False
    assert cfg.mirror_dir == Path("/x/dados/notes")


def test_load_reads_mirror_settings(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "mirror_enabled": True,
        "mirror_dir": str(tmp_path / "espelho"),
    }))
    cfg = Config.load(config_file)
    assert cfg.mirror_enabled is True
    assert cfg.mirror_dir == tmp_path / "espelho"


# ---------------- .deb (system install) awareness ----------------

def test_system_install_wins_the_binary_defaults(tmp_path, monkeypatch):
    """With the .deb installed (/usr/lib/tomenotas, /usr/bin clients),
    the defaults must point there instead of the home-dir installs."""
    from tomenotas.infra import config as config_mod

    lib = tmp_path / "usr" / "lib" / "tomenotas"
    (lib / "piper").mkdir(parents=True)
    (lib / "whisper-cli").write_bytes(b"elf")
    (lib / "piper" / "piper").write_bytes(b"elf")
    usr_bin = tmp_path / "usr" / "bin"
    usr_bin.mkdir(parents=True)
    (usr_bin / "tomenotas-hotkey-record").write_text("#!/bin/bash\n")
    monkeypatch.setattr(config_mod, "SYSTEM_LIB_DIR", lib)
    monkeypatch.setattr(config_mod, "SYSTEM_BIN_DIR", usr_bin)

    cfg = Config()
    assert cfg.whisper_bin == lib / "whisper-cli"
    assert cfg.piper_bin == lib / "piper" / "piper"
    assert cfg.bin_dir == usr_bin


def test_without_system_install_home_defaults_apply(tmp_path, monkeypatch):
    from tomenotas.infra import config as config_mod

    monkeypatch.setattr(config_mod, "SYSTEM_LIB_DIR",
                        tmp_path / "nao-existe")
    monkeypatch.setattr(config_mod, "SYSTEM_BIN_DIR",
                        tmp_path / "nao-existe-bin")
    cfg = Config()
    assert cfg.whisper_bin == Path.home() / "whisper.cpp/build/bin/whisper-cli"
    assert cfg.piper_bin == Path.home() / "piper/piper"
    assert cfg.bin_dir == Path.home() / "tomenotas"


def test_explicit_config_wins_over_system_install(tmp_path, monkeypatch):
    from tomenotas.infra import config as config_mod

    lib = tmp_path / "usr" / "lib" / "tomenotas"
    lib.mkdir(parents=True)
    (lib / "whisper-cli").write_bytes(b"elf")
    monkeypatch.setattr(config_mod, "SYSTEM_LIB_DIR", lib)

    cfg = Config(whisper_bin=Path("/opt/meu-whisper"))
    assert cfg.whisper_bin == Path("/opt/meu-whisper")


def test_icons_dir_falls_back_to_system_share(tmp_path, monkeypatch):
    from tomenotas.infra import config as config_mod

    share = tmp_path / "usr" / "share" / "tomenotas"
    (share / "icons").mkdir(parents=True)
    monkeypatch.setattr(config_mod, "SYSTEM_SHARE_DIR", share)

    # user-local icons absent -> system icons dir
    cfg = Config(base_dir=tmp_path / "dados")
    assert cfg.icons_dir == share / "icons"

    # user-local icons present (venv install) -> they win
    (tmp_path / "dados" / "icons").mkdir(parents=True)
    assert cfg.icons_dir == tmp_path / "dados" / "icons"


def test_explicit_model_paths_win_over_the_derived_defaults():
    cfg = Config(base_dir=Path("/x"),
                 whisper_model=Path("/w/ggml-small.bin"),
                 piper_model=Path("/p/voz.onnx"))
    assert cfg.whisper_model == Path("/w/ggml-small.bin")
    assert cfg.piper_model == Path("/p/voz.onnx")


def test_bin_dir_default_and_override(tmp_path, monkeypatch):
    from tomenotas.infra import config as config_mod

    monkeypatch.setattr(config_mod, "SYSTEM_BIN_DIR", tmp_path / "nada")
    assert Config().bin_dir == Path.home() / "tomenotas"
    monkeypatch.setenv("TOMENOTAS_BIN_DIR", "/opt/bin")
    assert Config.load(tmp_path / "nada.json").bin_dir == Path("/opt/bin")


def test_load_without_file_uses_defaults(tmp_path):
    cfg = Config.load(tmp_path / "inexistente.json")
    assert cfg == Config()


def test_load_reads_paths_from_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "whisper_bin": "/opt/whisper/main",
        "whisper_model": "/opt/whisper/ggml-small.bin",
        "piper_bin": "/opt/piper/piper",
        "piper_model": "/opt/piper/voz.onnx",
        "base_dir": str(tmp_path / "dados"),
        "language": "en",
    }))
    cfg = Config.load(config_file)
    assert cfg.whisper_bin == Path("/opt/whisper/main")
    assert cfg.whisper_model == Path("/opt/whisper/ggml-small.bin")
    assert cfg.piper_bin == Path("/opt/piper/piper")
    assert cfg.piper_model == Path("/opt/piper/voz.onnx")
    assert cfg.base_dir == tmp_path / "dados"
    assert cfg.language == "en"


def test_load_expands_tilde_in_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"whisper_bin": "~/w/main"}))
    cfg = Config.load(config_file)
    assert cfg.whisper_bin == Path.home() / "w/main"


def test_env_takes_precedence_over_json(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "whisper_bin": "/do/json",
        "language": "en",
    }))
    monkeypatch.setenv("TOMENOTAS_WHISPER_BIN", "/do/env")
    monkeypatch.setenv("TOMENOTAS_PIPER_BIN", "/do/env/piper")
    monkeypatch.setenv("TOMENOTAS_LANGUAGE", "es")
    cfg = Config.load(config_file)
    assert cfg.whisper_bin == Path("/do/env")
    assert cfg.piper_bin == Path("/do/env/piper")
    assert cfg.language == "es"


def test_invalid_json_warns_and_uses_defaults(tmp_path, caplog):
    config_file = tmp_path / "config.json"
    config_file.write_text("{ nada a ver")
    cfg = Config.load(config_file)
    assert cfg == Config()
    assert "invalid config" in caplog.text


# ---------------- update_config_file ----------------

def test_update_config_file_creates_file_and_parents(tmp_path):
    from tomenotas.infra.config import update_config_file

    target = tmp_path / "sub" / "config.json"
    update_config_file("piper_model", "/x/voz.onnx", target)
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "piper_model": "/x/voz.onnx"
    }


def test_update_config_file_preserves_other_keys(tmp_path):
    from tomenotas.infra.config import update_config_file

    target = tmp_path / "config.json"
    target.write_text(json.dumps({"whisper_bin": "/w", "language": "pt"}))
    update_config_file("whisper_model", "/m.bin", target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {"whisper_bin": "/w", "language": "pt",
                    "whisper_model": "/m.bin"}


def test_update_config_file_rewrites_invalid_content(tmp_path, caplog):
    from tomenotas.infra.config import update_config_file

    target = tmp_path / "config.json"
    target.write_text("{ nada a ver")
    update_config_file("language", "pt", target)
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "language": "pt"
    }
    assert "invalid config" in caplog.text
