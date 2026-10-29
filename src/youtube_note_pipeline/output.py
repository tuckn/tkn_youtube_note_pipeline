"""CLI-only result adapters; persisted artifacts and Python APIs stay independent."""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from typing import Any

from youtube_note_pipeline.config_display import config_lines


def public_result(
    result: dict[str, Any], *, command: str, exit_code: int, full_output: bool = False,
) -> dict[str, Any]:
    """Add CLI summaries and optionally condense unchanged migration rows."""
    payload = deepcopy(result)
    counts = payload.setdefault("counts", {})
    if not counts:
        if "stages" in payload:
            counts.update(Counter(stage["status"] for stage in payload["stages"]))
        elif command == "list":
            counts["videos"] = payload["count"]
        elif command in ("validate", "status"):
            counts["checked"] = 1
            counts["invalid"] = int(not payload["valid"])
        elif command == "config list":
            counts["sources"] = len(payload["sources"])
        elif command != "migrate-notes":
            counts[payload.get("status", "failed" if exit_code else "success")] = 1
    if "warnings" in payload:
        counts["warnings"] = len(payload["warnings"])
    if command == "migrate-notes":
        if "items" in payload:
            counts["total"] = len(payload["items"])
            if not full_output:
                total = len(payload["items"])
                payload["items"] = [
                    row for row in payload["items"] if row["status"] not in {"unchanged", "skipped"}
                ]
                omitted = total - len(payload["items"])
                if omitted:
                    payload["omitted_items"] = omitted
                    payload["details_hint"] = "Use --full-output (with or without --json)"
        payload.setdefault("status", "planned" if not exit_code else "failed")
    payload.setdefault("status", "success" if not exit_code else "failed")
    payload["outcome"] = "success" if not exit_code else "failed"
    if exit_code and any(counts.get(key, 0) for key in (
        "created", "updated", "unchanged", "planned", "skipped",
    )):
        payload["outcome"] = "partial_failure"
    return payload


def emit(result: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print("\n".join(config_lines(result)))
