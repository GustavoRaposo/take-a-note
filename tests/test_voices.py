"""Tests for tomenotas.infra.voices — Piper voice discovery and switch."""

import json
from pathlib import Path

import pytest

from tomenotas.infra.config import Config
from tomenotas.infra.voices import VoiceManager


class FakePlayer:
    def __init__(self):
        self.models = []

    def set_model(self, path):
        self.models.append(path)


def make(tmp_path, voices=("pt_BR-faber-medium", "pt_BR-edresson-low"),
         current="pt_BR-faber-medium"):
    piper_dir = tmp_path / "piper"
    piper_dir.mkdir()
    for name in voices:
        (piper_dir / f"{name}.onnx").write_bytes(b"onnx")
        (piper_dir / f"{name}.onnx.json").write_text("{}", encoding="utf-8")
    player = FakePlayer()
    manager = VoiceManager(
        player, piper_dir / f"{current}.onnx",
        config_path=tmp_path / "config" / "config.json",
    )
    return manager, player


def test_list_voices_lists_onnx_stems_sorted(tmp_path):
    manager, _ = make(tmp_path)
    # the .onnx.json companion files must not show up as voices
    assert manager.list_voices() == [
        "pt_BR-edresson-low", "pt_BR-faber-medium",
    ]


def test_list_voices_without_directory_returns_empty(tmp_path):
    manager = VoiceManager(FakePlayer(), tmp_path / "nowhere" / "v.onnx",
                           config_path=tmp_path / "config.json")
    assert manager.list_voices() == []


def test_current_voice_is_the_model_stem(tmp_path):
    manager, _ = make(tmp_path)
    assert manager.current_voice() == "pt_BR-faber-medium"


def test_set_voice_applies_to_player_and_persists(tmp_path):
    manager, player = make(tmp_path)
    manager.set_voice("pt_BR-edresson-low")

    new_model = tmp_path / "piper" / "pt_BR-edresson-low.onnx"
    assert player.models == [new_model]
    assert manager.current_voice() == "pt_BR-edresson-low"
    # persisted: a fresh Config.load picks up the new voice
    cfg = Config.load(tmp_path / "config" / "config.json")
    assert cfg.piper_model == new_model


def test_set_voice_preserves_other_config_keys(tmp_path):
    manager, _ = make(tmp_path)
    config_file = tmp_path / "config" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({
        "whisper_bin": "/opt/whisper/main",
        "language": "pt",
    }), encoding="utf-8")

    manager.set_voice("pt_BR-edresson-low")

    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["whisper_bin"] == "/opt/whisper/main"
    assert data["language"] == "pt"
    assert data["piper_model"] == str(
        tmp_path / "piper" / "pt_BR-edresson-low.onnx"
    )


def test_set_voice_unknown_raises_and_changes_nothing(tmp_path):
    manager, player = make(tmp_path)
    with pytest.raises(ValueError, match="Voz não encontrada"):
        manager.set_voice("fantasma")
    assert player.models == []
    assert manager.current_voice() == "pt_BR-faber-medium"
    assert not (tmp_path / "config" / "config.json").exists()


def test_set_voice_with_invalid_config_rewrites_it(tmp_path, caplog):
    manager, _ = make(tmp_path)
    config_file = tmp_path / "config" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{ nada a ver", encoding="utf-8")

    manager.set_voice("pt_BR-edresson-low")

    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["piper_model"].endswith("pt_BR-edresson-low.onnx")
    assert "invalid config" in caplog.text


def test_download_default_fetches_pair_and_activates_the_voice(tmp_path):
    from tomenotas.infra.downloads import DEFAULT_VOICE

    class FakeDownloader:
        def __init__(self):
            self.fetched = []

        def fetch(self, url, dest, on_progress=None):
            self.fetched.append(url)
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b"data")
            if on_progress:
                on_progress(4, 4)
            return Path(dest)

    piper_dir = tmp_path / "piper"
    piper_dir.mkdir()
    player = FakePlayer()
    manager = VoiceManager(player, piper_dir / "pt_BR-faber-medium.onnx",
                           config_path=tmp_path / "config.json")

    progress = []
    name = manager.download_default(FakeDownloader(),
                                    on_progress=lambda d, t: progress.append((d, t)))

    assert name == "pt_BR-faber-medium"
    assert manager.current_voice() == "pt_BR-faber-medium"
    assert player.models == [piper_dir / "pt_BR-faber-medium.onnx"]
    assert (piper_dir / "pt_BR-faber-medium.onnx.json").exists()
    assert progress
    assert DEFAULT_VOICE["name"] == "pt_BR-faber-medium"
    cfg_piper = json.loads(
        (tmp_path / "config.json").read_text(encoding="utf-8")
    )["piper_model"]
    assert cfg_piper == str(piper_dir / "pt_BR-faber-medium.onnx")


def test_set_voice_with_non_dict_config_rewrites_it(tmp_path):
    manager, _ = make(tmp_path)
    config_file = tmp_path / "config" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("[1, 2]", encoding="utf-8")

    manager.set_voice("pt_BR-edresson-low")

    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["piper_model"].endswith("pt_BR-edresson-low.onnx")
