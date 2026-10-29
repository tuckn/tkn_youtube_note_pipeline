"""All CLI outcomes use the selected format without changing execution semantics."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from youtube_note_pipeline import cli
from youtube_note_pipeline.config import PipelineConfig
from youtube_note_pipeline.output import emit, public_result
from youtube_note_pipeline.pipeline import StageResult

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    config = PipelineConfig(**{name: tmp_path / name for name in (
        "raw_root", "source_root", "summary_root", "reports_root",
    )})
    monkeypatch.setattr(cli, "_resolved", lambda args: SimpleNamespace(config=config, sources=[]))
    return config


def decode(output, json_output):
    if json_output:
        return json.loads(output)
    return dict(line.split("=", 1) for line in output.splitlines())


@pytest.mark.parametrize("tokens", [
    ["--json", "config", "list"], ["config", "--json", "list"],
    ["config", "list", "--json"], ["--json", "list"], ["list", "--json"],
])
def test_json_and_detail_flags_survive_every_subcommand_level(tokens):
    args = cli.build_parser().parse_args(["--full-output", *tokens])
    assert args.json is True and args.full_output is True


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("tokens", [
    [], ["missing-command"], ["validate"], ["list", "--unknown"],
    ["config", "list", "--model"], ["--quiet", "config", "list", "--verbose"],
])
def test_argument_errors_are_one_selected_result(tokens, json_output, capsys):
    assert cli.main([*tokens, *(["--json"] if json_output else [])]) == 2
    captured = capsys.readouterr()
    result = decode(captured.out, json_output)
    assert result["status"] == "failed"
    assert result["error_type"] == "argument_error"
    assert captured.err and "Traceback" not in captured.err
    assert "\x1b" not in captured.out


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("verbosity", [[], ["--quiet"], ["--verbose"]])
@pytest.mark.parametrize("tty", [False, True])
def test_format_is_independent_of_logs_and_tty(
    isolated, json_output, verbosity, tty, monkeypatch, capsys,
):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: tty)
    monkeypatch.setattr(cli, "build_inventory", lambda *args: {
        "schema_version": "1.0", "count": 0, "items": [], "warnings": [],
    })
    assert cli.main([
        *verbosity, "list", *(["--json"] if json_output else []),
    ]) == 0
    captured = capsys.readouterr()
    assert decode(captured.out, json_output)["status"] == "success"
    assert "\x1b" not in captured.out
    if verbosity == ["--quiet"]:
        assert captured.err == ""
    else:
        assert "[INFO]" in captured.err
    if verbosity == ["--verbose"]:
        assert "[DEBUG]" in captured.err


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("command", [
    "ingest", "acquire", "import-raw", "build-source", "build-summary",
])
def test_stage_commands_expose_paths_details_and_counts(
    isolated, json_output, command, monkeypatch, capsys,
):
    path = Path(r"C:\path\to\長い フォルダ") / ("a" * 180 + ".md")
    stage = StageResult(path, "created", {"validated": True})
    report = Path("report.json")
    monkeypatch.setattr(cli, "provider_for_config", lambda config: object())
    monkeypatch.setattr(cli, "ingest", lambda *args, **kwargs: ([stage], report))
    monkeypatch.setattr(cli, "write_report", lambda *args, **kwargs: report)
    for name in ("run_acquire", "run_import", "build_source", "build_summary"):
        monkeypatch.setattr(cli, name, lambda *args, **kwargs: stage)
    arguments = {
        "ingest": ["https://youtu.be/abcdefghijk"],
        "acquire": ["https://youtu.be/abcdefghijk"],
        "import-raw": ["--metadata", "meta.json", "--captions", "captions.json3"],
        "build-source": ["manifest.json"], "build-summary": ["source.md"],
    }[command]
    assert cli.main([command, *arguments, *(["--json"] if json_output else [])]) == 0
    captured = capsys.readouterr()
    result = decode(captured.out, json_output)
    assert result["path"] == str(path)
    assert result["status"] == "created"
    if json_output:
        assert result["counts"] == {"created": 1}
        assert result["stages"][0]["details"] == {"validated": True}
    else:
        assert result["counts.created"] == "1"
        assert f"path={path}" in captured.out.splitlines()


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("command", ["validate", "status"])
def test_invalid_artifact_preserves_exit_one_and_separate_target(
    isolated, json_output, command, capsys,
):
    target = Path("missing source.md")
    assert cli.main([command, str(target), *(["--json"] if json_output else [])]) == 1
    result = decode(capsys.readouterr().out, json_output)
    assert result["path"] == str(target)
    assert result["status"] == "failed"
    assert result["outcome"] == "failed"


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("error", [OSError(5, "denied", "input.md"), RuntimeError("failed"),
                                    KeyboardInterrupt()])
def test_runtime_error_and_interrupt_preserve_format_and_exit(
    isolated, json_output, error, monkeypatch, capsys,
):
    monkeypatch.setattr(cli, "build_source", Mock(side_effect=error))
    expected = 130 if isinstance(error, KeyboardInterrupt) else 1
    assert cli.main([
        "build-source", "input.md", "--quiet", *(["--json"] if json_output else []),
    ]) == expected
    captured = capsys.readouterr()
    result = decode(captured.out, json_output)
    assert result["status"] == ("interrupted" if expected == 130 else "failed")
    targets = result["targets"] if json_output else {"manifest": result["targets.manifest"]}
    assert targets["manifest"] == "input.md"
    assert captured.err


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("yaml_text", [
    "password: PRIVATE_CREDENTIAL\n", "password: [PRIVATE_CREDENTIAL\n",
])
def test_configuration_error_omits_pydantic_input_values(
    tmp_path, monkeypatch, capsys, json_output, yaml_text,
):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "bad.yaml"
    config.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr("youtube_note_pipeline.config.global_config_path", lambda: config)
    assert cli.main(["config", "list", *(["--json"] if json_output else [])]) == 1
    captured = capsys.readouterr()
    assert "PRIVATE_CREDENTIAL" not in captured.out + captured.err
    assert decode(captured.out, json_output)["status"] == "failed"


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("full_output", [False, True])
def test_migration_detail_level_and_partial_failure_do_not_change_plan(
    isolated, json_output, full_output, monkeypatch, capsys,
):
    plan = {
        "schema_version": "1.0", "scope": "references", "source_root": "source",
        "summary_root": "summary", "counts": {"unchanged": 1, "skipped": 1, "blocked": 1},
        "items": [
            {"path": "unchanged.md", "status": "unchanged"},
            {"path": "other.md", "status": "skipped", "reason": "not a summary"},
            {"path": "attention.md", "status": "blocked", "reason": "ambiguous source"},
        ], "warnings": [],
    }
    original = deepcopy(plan)
    monkeypatch.setattr(cli, "plan_migration", lambda *args, **kwargs: plan)
    options = (["--json"] if json_output else []) + (["--full-output"] if full_output else [])
    assert cli.main(["migrate-notes", "--dry-run", *options]) == 1
    result = decode(capsys.readouterr().out, json_output)
    assert result["outcome"] == "partial_failure"
    if json_output:
        assert len(result["items"]) == (3 if full_output else 1)
        assert any(row["path"] == "attention.md" for row in result["items"])
    else:
        assert "ambiguous source" in result.values()
    assert ("details_hint" in result) is not full_output
    assert plan == original


@pytest.mark.parametrize("json_output", [False, True])
def test_failed_acquisition_exposes_reason_with_target(isolated, json_output, monkeypatch, capsys):
    stage = StageResult(Path("failed-manifest.json"), "failed", {"error": "captions unavailable"})
    monkeypatch.setattr(cli, "run_acquire", lambda *args: stage)
    monkeypatch.setattr(cli, "write_report", lambda *args: Path("report.json"))
    assert cli.main([
        "acquire", "https://youtu.be/abcdefghijk", *(["--json"] if json_output else []),
    ]) == 1
    result = decode(capsys.readouterr().out, json_output)
    assert result["path"] == "failed-manifest.json" and result["status"] == "failed"
    if json_output:
        assert result["stages"][0]["details"]["error"] == "captions unavailable"
    else:
        assert result["stages[0].details.error"] == "captions unavailable"


def test_json_writer_and_text_share_all_values(capsys):
    original = {"path": r"C:\path\to\folder with space\日本語.md", "nested": [None, True, {}, []],
                "message": "line\r\n\t\x1b[31m", "long_path": "x" * 400}
    result = public_result(original, command="test", exit_code=0)
    emit(result, json_output=True)
    assert json.loads(capsys.readouterr().out) == result
    emit(result, json_output=False)
    text = capsys.readouterr().out
    assert f"path={original['path']}" in text.splitlines()
    assert "long_path=" + "x" * 400 in text.splitlines()
    assert r"message=line\r\n\t\u001b[31m" in text.splitlines()


def test_empty_migration_counts_zero_items():
    result = public_result({"counts": {}, "items": [], "warnings": []},
                           command="migrate-notes", exit_code=0)
    assert result["counts"] == {"total": 0, "warnings": 0}


@pytest.mark.parametrize("json_output", [False, True])
def test_real_import_dry_run_pipe_and_redirect_are_read_only(tmp_path, json_output):
    root = tmp_path / "app"
    config = tmp_path / "test.yaml"
    config.write_text(json.dumps({
        "schema_version": "1.0.0", **{name: str(root / name) for name in (
            "raw_root", "source_root", "summary_root", "reports_root",
        )},
    }), encoding="utf-8")
    code = (
        "import sys; from pathlib import Path; "
        "Path.home = classmethod(lambda cls: Path.cwd() / 'missing-home'); "
        "from youtube_note_pipeline.cli import main; raise SystemExit(main(sys.argv[1:]))"
    )
    argv = [
        sys.executable, "-c", code, "import-raw", "--metadata",
        str(FIXTURES / "metadata.info.json"), "--captions", str(FIXTURES / "captions.ja.json3"),
        "--config", str(config), "--dry-run", *(["--json"] if json_output else []),
    ]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    piped = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True,
                           text=True, encoding="utf-8", check=True)
    result = decode(piped.stdout, json_output)
    assert result["status"] == "planned"
    assert not root.exists()
    redirect = tmp_path / "stdout.txt"
    with redirect.open("w", encoding="utf-8") as stream:
        redirected = subprocess.run(argv, cwd=tmp_path, env=env, stdout=stream,
                                    stderr=subprocess.PIPE, check=True)
    assert redirected.returncode == 0
    redirected_result = decode(redirect.read_text("utf-8"), json_output)
    # Each dry-run chooses its own capture timestamp; compare the stable target and data.
    redirected_path = Path(redirected_result.pop("path"))
    assert redirected_path.parent.parent == Path(result.pop("path")).parent.parent
    assert redirected_result == result
    assert not root.exists()


@pytest.mark.parametrize("json_output", [False, True])
def test_config_init_keeps_template_and_refuses_edits(tmp_path, monkeypatch, capsys, json_output):
    target = tmp_path / "new-user/config.yaml"
    monkeypatch.setattr("youtube_note_pipeline.config.global_config_path", lambda: target)
    options = ["--json"] if json_output else []
    assert cli.main(["config", "init", "--quiet", *options]) == 0
    result = decode(capsys.readouterr().out, json_output)
    assert result["path"] == str(target)
    assert result["status"] == "created"
    before = target.read_bytes()
    assert cli.main(["config", "init", "--quiet", *options]) == 0
    assert decode(capsys.readouterr().out, json_output)["status"] == "unchanged"
    assert target.read_bytes() == before
    target.write_text("# edited\n", encoding="utf-8")
    assert cli.main(["config", "init", "--quiet", *options]) == 1
    captured = capsys.readouterr()
    result = decode(captured.out, json_output)
    targets = result["targets"] if json_output else {"config": result["targets.config"]}
    assert targets["config"] == str(target)
    assert target.read_text("utf-8") == "# edited\n"


def test_ingest_failure_reports_completed_stage_and_separate_report(
    isolated, monkeypatch, capsys, tmp_path,
):
    report = tmp_path / "partial.json"
    report.write_text(json.dumps({"stages": [
        {"path": "manifest.json", "status": "created", "details": {}},
    ]}), encoding="utf-8")
    monkeypatch.setattr(cli, "ingest", Mock(side_effect=RuntimeError(
        f"summary failed; report={report}",
    )))
    assert cli.main(["--json", "ingest", "https://youtu.be/abcdefghijk", "--quiet"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["outcome"] == "partial_failure"
    assert result["report"] == str(report)
    assert result["error"] == "summary failed"
    assert result["counts"] == {"failed": 1, "created": 1}


@pytest.mark.parametrize("options", [["--json"], []])
@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_help_and_version_remain_informational(options, flag, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([*options, flag])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "tkn-youtube-note" in output
    assert not output.startswith("{") and "outcome=" not in output
