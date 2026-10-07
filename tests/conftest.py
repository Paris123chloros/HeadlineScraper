import pytest


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """User .env files and host settings must not influence the test suite."""
    monkeypatch.chdir(tmp_path)
    for name in (
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "OLLAMA_TIMEOUT_SECONDS",
        "REPORT_TIMEZONE",
        "LOG_LEVEL",
        "DATA_DIR",
        "SOURCE_CATALOGUE",
    ):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
