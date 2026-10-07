import json

import pytest
from pydantic import ValidationError

from motorsport_research.cli import main
from motorsport_research.config import Settings


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("report_timezone", "Unknown/Timezone"),
        ("report_timezone", "../UTC"),
        ("ollama_base_url", "ftp://localhost"),
        ("ollama_base_url", "http://user:private-password@localhost"),
        ("ollama_base_url", "http://localhost?token=private-token"),
        ("ollama_base_url", "http://localhost#fragment"),
        ("ollama_model", "  "),
        ("ollama_model", "model name"),
        ("ollama_timeout_seconds", 0),
        ("ollama_timeout_seconds", 121),
        ("qwen_timeout_seconds", 0),
        ("qwen_timeout_seconds", 121),
        ("qwen_max_input_bytes", 4001),
        ("qwen_max_output_tokens", 2049),
        ("qwen_max_attempts", 4),
        ("qwen_max_chunks", 65),
        ("log_level", "INVALID"),
    ],
)
def test_reject_invalid_settings(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_env_file_and_environment_precedence(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "OLLAMA_MODEL=file-model:4b\nREPORT_TIMEZONE=UTC\nDASHBOARD_PORT=9000\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OLLAMA_MODEL", "environment-model:4b")
    settings = Settings()
    assert settings.ollama_model == "environment-model:4b"
    assert settings.report_timezone == "UTC"


def test_cli_config_and_safe_error(monkeypatch, capsys):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    assert main(["config"]) == 0
    assert json.loads(capsys.readouterr().out)["log_level"] == "WARNING"
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://user:private-password@localhost")
    assert main(["config"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "OLLAMA_BASE_URL" in output.err
    assert "private-password" not in output.err
