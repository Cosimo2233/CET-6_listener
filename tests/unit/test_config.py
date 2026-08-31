from pathlib import Path

import pytest

from cet6_listener.config import AppSettings


def test_config_loads_defaults_and_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("tts:\n  target: localhost:5000\n", encoding="utf-8")
    monkeypatch.setenv("TTS_TARGET", "example.test:1234")
    monkeypatch.setenv("TTS_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("TRANSLATION_MAX_TOKENS", "96")

    settings = AppSettings.load(config, tmp_path / "missing.env")

    assert settings.tts.target == "example.test:1234"
    assert settings.tts.timeout_seconds == 12.5
    assert settings.audio.sample_rate == 16000
    assert settings.asr.backend == "whisper_cpp"
    assert settings.translation.max_tokens == 96
    assert settings.translation.target_language == "Chinese"


def test_config_accepts_zipformer_npu_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("asr:\n  backend: zipformer_npu\ntts:\n  target: localhost:5000\n", encoding="utf-8")
    monkeypatch.setenv("ASR_NPU_MODEL_DIR", "/models/zipformer")

    settings = AppSettings.load(config, tmp_path / "missing.env")

    assert settings.asr.backend == "zipformer_npu"
    assert settings.asr.npu_model_dir == "/models/zipformer"


def test_config_rejects_unknown_fields(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("audio:\n  not_a_field: 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="未知字段"):
        AppSettings.load(config, tmp_path / "missing.env")
