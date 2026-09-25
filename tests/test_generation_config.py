import json
from importlib.resources import files
from unittest.mock import Mock

import pytest
import yaml

from youtube_note_pipeline.cli import main
from youtube_note_pipeline.config import PipelineConfig, public_config, resolve_config
from youtube_note_pipeline.pipeline import provider_for_config


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    user = tmp_path / "user.yaml"
    monkeypatch.setattr("youtube_note_pipeline.config.global_config_path", lambda: user)
    return tmp_path, user


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_nested_layers_and_cli_overrides_preserve_other_profiles(isolated):
    root, user = isolated
    write(user, {"generation": {"profiles": {
        "codex": {"overrides": {"reasoning_effort": "high", "timeout_seconds": 900}},
        "local": {"bridge_profile": "local-notes", "overrides": {"model": "original"}},
    }}})
    write(root / ".tkn/config.yaml", {"generation": {"summary_profile": "default-en"}})
    explicit = root / "explicit.yaml"
    write(explicit, {"generation": {"profiles": {
        "codex": {"overrides": {"timeout_seconds": 1200}},
        "local": {"overrides": {"timeout_seconds": 42}},
    }}})
    config = resolve_config(explicit_config=explicit, overrides={
        "profile": "local", "model": "cli-model", "provider_timeout_seconds": 60,
    }).config
    assert config.generation.active_profile == "local"
    assert config.summary_profile == "default-en"
    assert config.generation.selected.bridge_profile == "local-notes"
    assert config.generation.selected.overrides == {"model": "cli-model", "timeout_seconds": 60}
    assert config.generation.profiles["codex"].overrides == {
        "reasoning_effort": "high", "timeout_seconds": 1200,
    }


def test_legacy_settings_are_normalized_before_new_layer_overrides(isolated):
    root, user = isolated
    write(user, {
        "provider": "codex", "codex_executable": "fixture-codex",
        "model": "old-model", "provider_timeout_seconds": 600,
        "summary_profile": "default-en",
    })
    write(root / ".tkn/config.yaml", {"generation": {"profiles": {
        "codex": {"overrides": {"model": "new-model"}},
    }}})
    config = resolve_config().config
    assert config.generation.selected.legacy_provider == "codex"
    assert config.generation.selected.overrides == {
        "model": "new-model", "timeout_seconds": 600, "cli": {"executable": "fixture-codex"},
    }
    plan = provider_for_config(config).plan()
    assert plan["model"] == "new-model"
    assert plan["timeout_seconds"] == 600
    assert config.summary_profile == "default-en"
    assert "model" not in public_config(config)


def test_legacy_null_clears_prior_override_to_inherit_shared_setting(isolated):
    root, user = isolated
    write(root / "bridge.yaml", {"schema_version": "1.1.0", "profiles": {
        "codex-default": {"provider": "codex", "model": "shared", "timeout_seconds": 90},
    }})
    write(user, {"model": "old", "provider_timeout_seconds": 600})
    write(root / ".tkn/config.yaml", {"model": None, "provider_timeout_seconds": None})
    plan = provider_for_config(resolve_config().config).plan()
    assert plan["model"] == "shared"
    assert plan["timeout_seconds"] == 90


def test_config_show_resolves_selected_bridge_and_never_runs_ai(isolated, monkeypatch, capsys):
    root, user = isolated
    write(root / "bridge.yaml", {"schema_version": "1.1.0", "profiles": {
        "local-notes": {"provider": "ollama", "model": "fixture", "local_only": True},
    }})
    write(user, {"generation": {"profiles": {"local": {"bridge_profile": "local-notes"}}}})
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("external process")))
    monkeypatch.setattr(
        "tkn_genai_bridge.Runtime.generate", Mock(side_effect=AssertionError("AI generation")),
    )
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert main(["config", "show", "--profile", "local", "--quiet"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["values"]["generation"]["active_profile"] == "local"
    resolved = payload["generationResolved"]
    assert resolved["active_profile"] == "local"
    assert resolved["profile_name"] == "local-notes"
    assert resolved["provider"] == "ollama"
    assert resolved["model"] == "fixture"
    assert resolved["local_only"] is True
    assert resolved["will_call_provider"] is False
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("generation", [
    {"active_profile": "missing"},
    {"profiles": {"codex": {"bridge_profile": "missing"}}},
    {"profiles": {"codex": {"overrides": {"timeout_seconds": -1}}}},
    {"profiles": {"codex": {"overrides": {"unknown_setting": True}}}},
    {"profiles": None},
    {"profiles": {"codex": None}},
    None,
])
def test_invalid_configuration_show_fails_without_writes(isolated, capsys, generation):
    root, user = isolated
    reports = root / "reports"
    write(user, {"reports_root": str(reports), "generation": generation})
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert main(["config", "show", "--reports-root", str(reports), "--quiet"]) == 1
    assert capsys.readouterr().err
    assert not reports.exists()
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_mixed_old_and_new_ai_settings_are_rejected(isolated):
    _, user = isolated
    write(user, {"model": "old", "generation": {"active_profile": "codex"}})
    with pytest.raises(ValueError, match="do not mix"):
        resolve_config()


def test_packaged_example_and_public_config_roundtrip(isolated):
    _, user = isolated
    template = files("youtube_note_pipeline").joinpath("resources/config.example.yaml")
    parsed = yaml.safe_load(template.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == "1.0.0"
    assert "model" not in parsed
    write(user, parsed)
    config = resolve_config().config
    dumped = public_config(config)
    assert PipelineConfig.model_validate(dumped) == config
    assert dumped["generation"]["profiles"]["codex"] == {
        "bridge_profile": "codex-default", "overrides": {},
    }
    write(user, {"schema_version": "99.0.0"})
    with pytest.raises(ValueError, match="schema_version"):
        resolve_config()
