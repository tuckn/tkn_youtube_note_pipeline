"""Public configuration listing, provenance and read-only contract."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from youtube_note_pipeline.cli import build_parser, main
from youtube_note_pipeline.config import resolve_config
from youtube_note_pipeline.config_display import config_lines


def test_config_lines_keep_paths_copyable_and_escape_line_breaks() -> None:
    assert config_lines({
        "path": r"C:\Users\ExampleUser\profiles",
        "items": [{"active": True, "disabled": False, "unset": None}],
        "empty_list": [], "empty_mapping": {},
        "text": "日本語=message\r\n\t\x00\x0b\x85\u2028\u2029",
        "timeout": 60.5,
        "key\nwith\ttabs": [],
    }) == [
        r"path=C:\Users\ExampleUser\profiles",
        "items[0].active=true", "items[0].disabled=false", "items[0].unset=null",
        "empty_list=[]", "empty_mapping={}",
        r"text=日本語=message\r\n\t\u0000\u000b\u0085\u2028\u2029",
        "timeout=60.5",
        r"key\nwith\ttabs=[]",
    ]


def test_config_list_help_and_removed_show(capsys) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as help_exit:
        parser.parse_args(["config", "list", "--help"])
    assert help_exit.value.code == 0
    help_text = capsys.readouterr().out
    assert "--json" in help_text and "key=value" in help_text
    assert "without writing files or invoking AI" in help_text
    with pytest.raises(SystemExit) as old_exit:
        parser.parse_args(["config", "show"])
    assert old_exit.value.code == 2


@pytest.mark.parametrize("options", [[], ["--json"]])
def test_config_list_output_and_read_only_defaults(tmp_path, monkeypatch, capsys, options):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "absent-user" / "config.yaml"
    monkeypatch.setattr("youtube_note_pipeline.config.global_config_path", lambda: target)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "absent-home")
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("external process")))
    monkeypatch.setattr(
        "tkn_genai_bridge.Runtime.generate", Mock(side_effect=AssertionError("AI generation")),
    )
    before = set(tmp_path.rglob("*"))
    assert main(["config", "list", *options]) == 0
    captured = capsys.readouterr()
    assert captured.err == "[INFO] Showing resolved configuration\n"
    if options:
        payload = json.loads(captured.out)
        assert payload["sources"] == ["built-in defaults"]
        assert payload["effective_schema_version"] == "1.0.0"
        assert payload["source_schema_versions"] == []
        assert payload["winning_sources"]["raw_root"] == "built-in defaults"
    else:
        lines = captured.out.splitlines()
        raw_root = tmp_path / "absent-home/.tkn/youtube_note_pipeline/data/raw"
        assert f"values.raw_root={raw_root}" in lines
        assert "values.fallback_languages=[]" in lines
        assert "values.generation.profiles.codex.overrides={}" in lines
        assert "sources[0]=built-in defaults" in lines
        assert "effective_schema_version=1.0.0" in lines
    assert set(tmp_path.rglob("*")) == before


def write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_winning_sources_follow_nested_merge_and_selected_cli_profile(tmp_path, monkeypatch):
    user = tmp_path / "user.yaml"
    monkeypatch.setattr("youtube_note_pipeline.config.global_config_path", lambda: user)
    cwd_config = tmp_path / ".tkn/config.yaml"
    explicit = tmp_path / "explicit.yaml"
    write_config(user, {
        "schema_version": "1.0.0", "raw_root": "user-raw", "summary_root": "user-summary",
        "fallback_languages": ["ja", "en", "de"],
        "generation": {"profiles": {
            "codex": {"overrides": {"reasoning_effort": "high"}},
            "local": {"bridge_profile": "local-notes", "overrides": {"model": "original"}},
        }},
    })
    write_config(cwd_config, {
        "schema_version": "1.0.0", "raw_root": "cwd-raw",
        "generation": {"summary_profile": "default-en"},
    })
    write_config(explicit, {
        "schema_version": "1.0.0", "source_root": "explicit-source",
        "fallback_languages": ["fr"],
        "generation": {"profiles": {"local": {"overrides": {"timeout_seconds": 42}}}},
    })
    resolved = resolve_config(cwd=tmp_path, explicit_config=explicit, overrides={
        "profile": "local", "model": "cli-model", "bridge_profile": "cli-bridge",
        "provider_timeout_seconds": 60, "summary_profile": "default-ja",
        "reports_root": tmp_path / "cli-reports",
    })
    origins = resolved.winning_sources
    assert origins["schema_version"] == "built-in defaults"
    assert origins["raw_root"] == str(cwd_config)
    assert origins["source_root"] == str(explicit)
    assert origins["summary_root"] == str(user)
    assert origins["reports_root"] == "CLI options"
    assert origins["generation.active_profile"] == "CLI options"
    assert origins["generation.summary_profile"] == "CLI options"
    assert origins["generation.profiles.codex.bridge_profile"] == "built-in defaults"
    assert origins["generation.profiles.codex.overrides.reasoning_effort"] == str(user)
    for key in ("bridge_profile", "overrides.model", "overrides.timeout_seconds"):
        assert origins[f"generation.profiles.local.{key}"] == "CLI options"
    assert origins["fallback_languages[0]"] == str(explicit)
    assert "fallback_languages[1]" not in origins
    assert resolved.config.fallback_languages == ["fr"]
    assert resolved.source_schema_versions == [
        {"path": str(path), "schema_version": "1.0.0", "migrated": False}
        for path in (user, cwd_config, explicit)
    ]


@pytest.mark.parametrize("options", [[], ["--json"]])
def test_config_list_omits_credentials_from_inactive_overrides(
    tmp_path, monkeypatch, capsys, options,
):
    monkeypatch.chdir(tmp_path)
    user = tmp_path / "user.yaml"
    monkeypatch.setattr("youtube_note_pipeline.config.global_config_path", lambda: user)
    write_config(user, {"generation": {"profiles": {"inactive": {
        "bridge_profile": "unused", "overrides": {
            "api_key": "PRIVATE_KEY", "azure": {"client_secret": "PRIVATE_SECRET"},
            "model": "safe-model",
        },
    }}}})
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "PRIVATE_ENV")
    assert main(["config", "list", "--quiet", *options]) == 0
    captured = capsys.readouterr()
    assert "PRIVATE_" not in captured.out + captured.err
    assert "safe-model" in captured.out


def test_missing_source_schema_version_is_reported_as_null(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    user = tmp_path / "user.yaml"
    monkeypatch.setattr("youtube_note_pipeline.config.global_config_path", lambda: user)
    write_config(user, {"fallback_languages": []})
    assert main(["config", "list", "--quiet"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "source_schema_versions[0].schema_version=null" in lines
    assert "source_schema_versions[0].migrated=false" in lines


@pytest.mark.parametrize("version", [None, "99.0.0"])
def test_invalid_source_schema_cannot_be_hidden_by_later_layer(tmp_path, monkeypatch, version):
    user = tmp_path / "user.yaml"
    monkeypatch.setattr("youtube_note_pipeline.config.global_config_path", lambda: user)
    write_config(user, {"schema_version": version})
    write_config(tmp_path / ".tkn/config.yaml", {"schema_version": "1.0.0"})
    with pytest.raises(ValueError, match="schema_version"):
        resolve_config(cwd=tmp_path)
