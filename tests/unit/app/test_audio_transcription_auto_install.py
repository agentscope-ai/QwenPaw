from copaw.agents.utils import audio_transcription as audio_transcription_module


def test_auto_install_local_whisper_dependencies_installs_python_package(
    monkeypatch,
):
    statuses = [
        {
            "available": False,
            "ffmpeg_installed": True,
            "whisper_installed": False,
        },
        {
            "available": True,
            "ffmpeg_installed": True,
            "whisper_installed": True,
        },
    ]

    monkeypatch.setattr(
        audio_transcription_module,
        "check_local_whisper_available",
        lambda: statuses.pop(0),
    )
    monkeypatch.setattr(
        audio_transcription_module,
        "_build_python_whisper_install_command",
        lambda: (["python", "-m", "pip", "install", "openai-whisper"], "pip"),
    )
    monkeypatch.setattr(
        audio_transcription_module,
        "_run_install_command",
        lambda command: {
            "command": " ".join(command),
            "ok": True,
            "output": "installed",
            "returncode": 0,
        },
    )

    result = (
        audio_transcription_module.auto_install_local_whisper_dependencies()
    )

    assert result["success"] is True
    assert result["status_after"]["whisper_installed"] is True
    assert result["operations"] == [
        {
            "name": "openai-whisper",
            "attempted": True,
            "installer": "pip",
            "command": "python -m pip install openai-whisper",
            "ok": True,
            "output": "installed",
            "returncode": 0,
        },
    ]


def test_auto_install_local_whisper_dependencies_reports_manual_ffmpeg_step(
    monkeypatch,
):
    statuses = [
        {
            "available": False,
            "ffmpeg_installed": False,
            "whisper_installed": True,
        },
        {
            "available": False,
            "ffmpeg_installed": False,
            "whisper_installed": True,
        },
    ]

    monkeypatch.setattr(
        audio_transcription_module,
        "check_local_whisper_available",
        lambda: statuses.pop(0),
    )
    monkeypatch.setattr(
        audio_transcription_module,
        "_build_ffmpeg_install_command",
        lambda system_name=None: (None, None, "Install ffmpeg manually."),
    )

    result = (
        audio_transcription_module.auto_install_local_whisper_dependencies()
    )

    assert result["success"] is False
    assert result["manual_steps"] == ["Install ffmpeg manually."]
    assert result["operations"] == [
        {
            "name": "ffmpeg",
            "attempted": False,
            "installer": None,
            "command": "",
            "ok": False,
            "output": "Install ffmpeg manually.",
            "returncode": None,
        },
    ]


def test_get_transcription_language_hints_for_simplified_chinese(monkeypatch):
    class _Agents:
        language = "zh"

    class _Config:
        agents = _Agents()

    monkeypatch.setattr("copaw.config.load_config", lambda: _Config())

    hints = audio_transcription_module._get_transcription_language_hints()
    assert hints["whisper_language"] is None
    assert hints["prompt"] is None


def test_get_transcription_language_hints_for_english_locale(monkeypatch):
    class _Agents:
        language = "en-US"

    class _Config:
        agents = _Agents()

    monkeypatch.setattr("copaw.config.load_config", lambda: _Config())

    hints = audio_transcription_module._get_transcription_language_hints()
    assert hints["whisper_language"] == "en"
    assert hints["prompt"] is None


def test_normalize_transcription_text_keeps_non_chinese():
    text = "Hello world"
    result = audio_transcription_module._normalize_transcription_text(
        text,
        "zh",
    )
    assert result == text


def test_normalize_transcription_text_converts_traditional_chinese(
    monkeypatch,
):
    class _DummyConverter:
        def convert(self, text):
            return text.replace("繁體", "繁体")

    monkeypatch.setattr(
        audio_transcription_module,
        "_get_opencc_t2s_converter",
        lambda: _DummyConverter(),
    )

    result = audio_transcription_module._normalize_transcription_text(
        "這是繁體中文",
        "zh",
    )
    assert result == "這是繁体中文"