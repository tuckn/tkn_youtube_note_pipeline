import pytest


@pytest.fixture(autouse=True)
def isolate_bridge_configuration(tmp_path, monkeypatch):
    """Tests must never depend on the user's shared connection settings."""
    monkeypatch.setattr(
        "tkn_genai_bridge.config.user_config_path", lambda: tmp_path / "bridge.yaml"
    )
