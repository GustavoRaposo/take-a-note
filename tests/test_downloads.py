"""Tests for tomenotas.infra.downloads — model downloads with progress."""

import json
from pathlib import Path

import pytest

from tomenotas.domain.errors import DownloadError
from tomenotas.infra.config import Config
from tomenotas.infra.downloads import (
    DEFAULT_VOICE,
    WHISPER_MODELS,
    Downloader,
    ModelManager,
    download_voice,
)


class FakeResponse:
    def __init__(self, data: bytes, content_length=...):
        self._data = data
        self._pos = 0
        length = len(data) if content_length is ... else content_length
        self.headers = ({} if length is None
                        else {"Content-Length": str(length)})

    def read(self, n):
        chunk = self._data[self._pos:self._pos + n]
        self._pos += n
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def opener_for(responses: dict):
    """url -> bytes/FakeResponse/Exception."""
    def opener(url):
        value = responses[url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, bytes):
            return FakeResponse(value)
        return value
    return opener


# ---------------- Downloader ----------------

def test_fetch_writes_file_and_reports_progress(tmp_path):
    data = b"x" * 5000
    downloader = Downloader(opener=opener_for({"http://m/a.bin": data}),
                            chunk_size=2048)
    progress = []
    dest = tmp_path / "models" / "a.bin"  # parent does not exist yet

    result = downloader.fetch("http://m/a.bin", dest,
                              on_progress=lambda d, t: progress.append((d, t)))

    assert result == dest
    assert dest.read_bytes() == data
    assert not dest.with_name("a.bin.part").exists()  # atomic: tmp renamed
    assert progress == [(2048, 5000), (4096, 5000), (5000, 5000)]


def test_fetch_without_content_length_reports_unknown_total(tmp_path):
    downloader = Downloader(
        opener=opener_for({"http://m/a.bin": FakeResponse(b"abc",
                                                          content_length=None)})
    )
    progress = []
    downloader.fetch("http://m/a.bin", tmp_path / "a.bin",
                     on_progress=lambda d, t: progress.append((d, t)))
    assert progress == [(3, None)]


def test_fetch_size_mismatch_raises_and_leaves_nothing(tmp_path):
    downloader = Downloader(
        opener=opener_for({"http://m/a.bin": FakeResponse(b"abc",
                                                          content_length=99)})
    )
    with pytest.raises(DownloadError, match="incompleto"):
        downloader.fetch("http://m/a.bin", tmp_path / "a.bin")
    assert list(tmp_path.iterdir()) == []  # no dest, no .part


def test_fetch_network_error_raises_download_error(tmp_path):
    downloader = Downloader(
        opener=opener_for({"http://m/a.bin": OSError("conexão recusada")})
    )
    with pytest.raises(DownloadError, match="Falha no download"):
        downloader.fetch("http://m/a.bin", tmp_path / "a.bin")
    assert list(tmp_path.iterdir()) == []


# ---------------- catalog ----------------

def test_whisper_catalog_covers_the_install_sizes():
    assert set(WHISPER_MODELS) == {"tiny", "base", "small", "medium",
                                   "large-v3"}
    for size, info in WHISPER_MODELS.items():
        assert info["url"].endswith(f"ggml-{size}.bin")
        assert info["label"]


def test_default_voice_urls_are_the_faber_pair():
    assert DEFAULT_VOICE["name"] == "pt_BR-faber-medium"
    assert DEFAULT_VOICE["onnx_url"].endswith("pt_BR-faber-medium.onnx")
    assert DEFAULT_VOICE["json_url"].endswith("pt_BR-faber-medium.onnx.json")


# ---------------- download_voice ----------------

def test_download_voice_fetches_the_onnx_and_json_pair(tmp_path):
    downloader = Downloader(opener=opener_for({
        DEFAULT_VOICE["onnx_url"]: b"onnx",
        DEFAULT_VOICE["json_url"]: b"{}",
    }))
    progress = []
    path = download_voice(downloader, tmp_path / "voices",
                          on_progress=lambda d, t: progress.append((d, t)))
    assert path == tmp_path / "voices" / "pt_BR-faber-medium.onnx"
    assert path.read_bytes() == b"onnx"
    assert (tmp_path / "voices" / "pt_BR-faber-medium.onnx.json").exists()
    assert progress  # progress was forwarded


# ---------------- ModelManager (whisper) ----------------

class FakeTranscriber:
    def __init__(self):
        self.models = []

    def set_model(self, path):
        self.models.append(path)


def make_manager(tmp_path, current="ggml-medium.bin", responses=None):
    models_dir = tmp_path / "models"
    transcriber = FakeTranscriber()
    downloader = Downloader(opener=opener_for(responses or {}))
    manager = ModelManager(
        transcriber, models_dir / current, models_dir, downloader,
        config_path=tmp_path / "config" / "config.json",
    )
    return manager, transcriber


def test_current_size_parses_the_model_stem(tmp_path):
    manager, _ = make_manager(tmp_path, current="ggml-small.bin")
    assert manager.current_size() == "small"


def test_is_installed_checks_models_dir_and_current_model(tmp_path):
    manager, _ = make_manager(tmp_path)
    assert not manager.is_installed("medium")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "ggml-tiny.bin").write_bytes(b"ggml")
    assert manager.is_installed("tiny")
    # current model outside models_dir (old install) also counts
    old = ModelManager(FakeTranscriber(), tmp_path / "old" / "ggml-base.bin",
                       tmp_path / "models", Downloader(opener=opener_for({})),
                       config_path=tmp_path / "c.json")
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "ggml-base.bin").write_bytes(b"ggml")
    assert old.is_installed("base")


def test_download_applies_to_transcriber_and_persists(tmp_path):
    manager, transcriber = make_manager(
        tmp_path, responses={WHISPER_MODELS["tiny"]["url"]: b"ggml-data"}
    )
    progress = []
    path = manager.download("tiny", on_progress=lambda d, t: progress.append((d, t)))

    assert path == tmp_path / "models" / "ggml-tiny.bin"
    assert path.read_bytes() == b"ggml-data"
    assert transcriber.models == [path]
    assert manager.current_size() == "tiny"
    assert progress
    cfg = Config.load(tmp_path / "config" / "config.json")
    assert cfg.whisper_model == path


def test_download_without_activate_only_fetches(tmp_path):
    # the stream model is downloaded without becoming the active main model
    manager, transcriber = make_manager(
        tmp_path, responses={WHISPER_MODELS["base"]["url"]: b"ggml-base"}
    )
    path = manager.download("base", activate=False)

    assert path.read_bytes() == b"ggml-base"
    assert transcriber.models == []          # main model untouched
    assert manager.current_size() == "medium"
    assert not (tmp_path / "config" / "config.json").exists()


def test_download_failure_changes_nothing(tmp_path):
    manager, transcriber = make_manager(
        tmp_path, responses={WHISPER_MODELS["tiny"]["url"]: OSError("rede")}
    )
    with pytest.raises(DownloadError):
        manager.download("tiny")
    assert transcriber.models == []
    assert manager.current_size() == "medium"
    assert not (tmp_path / "config" / "config.json").exists()


def test_download_unknown_size_raises(tmp_path):
    manager, _ = make_manager(tmp_path)
    with pytest.raises(KeyError):
        manager.download("gigante")


def test_use_switches_to_an_installed_model_and_persists(tmp_path):
    manager, transcriber = make_manager(tmp_path)
    (tmp_path / "models").mkdir()
    small = tmp_path / "models" / "ggml-small.bin"
    small.write_bytes(b"ggml")

    manager.use("small")

    assert transcriber.models == [small]
    assert manager.current_size() == "small"
    data = json.loads(
        (tmp_path / "config" / "config.json").read_text(encoding="utf-8")
    )
    assert data["whisper_model"] == str(small)


def test_use_missing_model_raises_and_changes_nothing(tmp_path):
    manager, transcriber = make_manager(tmp_path)
    with pytest.raises(ValueError, match="não baixado"):
        manager.use("tiny")
    assert transcriber.models == []
    assert manager.current_size() == "medium"
