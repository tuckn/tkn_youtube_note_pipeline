"""Auditable, backed-up reference and legacy-schema migrations; never regenerate text."""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from youtube_note_pipeline.io import atomic_write, sha256_bytes
from youtube_note_pipeline.naming import file_uri_to_path, path_to_file_uri
from youtube_note_pipeline.notes import split_note
from youtube_note_pipeline.raw import canonical_video_url
from youtube_note_pipeline.validation import validate_summary


def _metadata(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8-sig")
    metadata, _ = split_note(text)
    frontmatter = text.replace("\r\n", "\n").split("\n---\n", 1)[0]
    keys = re.findall(r"(?m)^([A-Za-z][A-Za-z0-9]*):", frontmatter)
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate Frontmatter keys")
    return metadata


def _uuid(value: object) -> str:
    return str(uuid.UUID(str(value)))


def patch_metadata(payload: bytes, changes: dict[str, Any]) -> bytes:
    """Patch only single-line managed fields; preserve body, BOM and line endings."""
    text = payload.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    boundary = text.find(newline + "---" + newline, 4)
    if boundary < 0:
        raise ValueError("missing Frontmatter delimiter")
    frontmatter, rest = text[:boundary], text[boundary:]
    for key, value in changes.items():
        line = f"{key}: {json.dumps(value, ensure_ascii=False)}"
        pattern = rf"(?m)^{re.escape(key)}:[^\r\n]*"
        if re.search(pattern, frontmatter):
            frontmatter = re.sub(pattern, line.replace("\\", "\\\\"), frontmatter)
        else:
            # Keep date / updated / noteId as the final three properties.
            marker = newline + "date:"
            if marker not in frontmatter:
                raise ValueError("cannot insert metadata without a date field")
            frontmatter = frontmatter.replace(marker, newline + line + marker, 1)
    result = (frontmatter + rest).encode("utf-8")
    return (b"\xef\xbb\xbf" if payload.startswith(b"\xef\xbb\xbf") else b"") + result


def plan_migration(source_root: Path, summary_root: Path) -> dict[str, Any]:
    source_root = source_root.absolute()
    summary_root = summary_root.absolute()
    if not source_root.is_dir() or not summary_root.is_dir():
        raise ValueError("migration source_root and summary_root must be existing directories")
    sources: dict[str, list[tuple[Path, dict[str, Any], bytes]]] = defaultdict(list)
    source_ids: Counter[str] = Counter()
    warnings: list[dict[str, str]] = []
    for path in sorted(source_root.rglob("*.md")):
        try:
            path.resolve().relative_to(source_root.resolve())
            payload = path.read_bytes()
            metadata = _metadata(payload)
            if metadata.get("type") != "transcript":
                continue
            video_id, _ = canonical_video_url(str(metadata.get("url") or ""))
            sources[video_id].append((path, metadata, payload))
            source_ids[_uuid(metadata.get("noteId"))] += 1
        except (OSError, UnicodeError, ValueError) as exc:
            warnings.append({"path": str(path), "error": str(exc)})
    items: list[dict[str, Any]] = []
    for path in sorted(summary_root.rglob("*.md")):
        item: dict[str, Any] = {"path": str(path), "status": "unchanged", "changes": {}}
        items.append(item)
        try:
            path.resolve().relative_to(summary_root.resolve())
            payload = path.read_bytes()
            metadata = _metadata(payload)
            item["before_sha256"] = sha256_bytes(payload)
            if metadata.get("type") not in ("summary", "webClip"):
                item.update(status="skipped", reason="not a summary")
                continue
            uri = str(metadata.get("source") or "")
            if not uri:
                item.update(status="skipped", reason="no source reference to repair")
                continue
            video_id, canonical_url = canonical_video_url(str(metadata.get("url") or ""))
            item["url"] = canonical_url
            item["note_id"] = _uuid(metadata.get("noteId"))
            candidates = sources.get(video_id, [])
            if len(candidates) != 1:
                raise ValueError(f"expected one source for video ID; found {len(candidates)}")
            source_path, source_metadata, source_bytes = candidates[0]
            source_id = _uuid(source_metadata.get("noteId"))
            if source_ids[source_id] != 1:
                raise ValueError("source noteId is not unique")
            if metadata.get("sourceNoteId") is not None and (
                _uuid(metadata["sourceNoteId"]) != source_id
            ):
                raise ValueError("sourceNoteId conflicts with the URL-matched source")
            try:
                old_path = file_uri_to_path(uri)
                old_is_current = old_path.resolve(strict=True) == source_path.resolve(strict=True)
                if not old_is_current:
                    old_metadata = _metadata(old_path.read_bytes())
                    if _uuid(old_metadata.get("noteId")) != source_id or (
                        canonical_video_url(str(old_metadata.get("url") or ""))[0] != video_id
                    ):
                        raise ValueError("existing source locator points to a different note")
            except FileNotFoundError:
                old_is_current = False
            changes: dict[str, Any] = {}
            if not old_is_current:
                changes["source"] = path_to_file_uri(source_path)
                changes["sourceNoteId"] = source_id
            legacy_version = str(metadata.get("schemaVersion"))
            if metadata.get("type") == "summary" and legacy_version in ("1.0", "2.0"):
                changes["schemaVersion"] = "1.1" if legacy_version == "1.0" else "3.0"
            if not changes:
                continue
            updated = patch_metadata(payload, changes)
            if "schemaVersion" in changes:
                errors = validate_summary(path, source_root, text=updated.decode("utf-8-sig"))
                if errors:
                    raise ValueError(
                        "migration does not satisfy target contract: " + "; ".join(errors)
                    )
            item.update(
                status="planned",
                changes=changes,
                before={key: metadata.get(key) for key in changes},
                after_sha256=sha256_bytes(updated),
                source_path=str(source_path),
                source_sha256=sha256_bytes(source_bytes),
                source_note_id=source_id,
            )
        except (OSError, UnicodeError, ValueError) as exc:
            item.update(status="blocked", reason=str(exc))
    return {
        "schema_version": "1.0",
        "source_root": str(source_root),
        "summary_root": str(summary_root),
        "counts": dict(Counter(item["status"] for item in items)),
        "items": items,
        "warnings": warnings,
    }


def apply_migration(plan: dict[str, Any], reports_root: Path) -> dict[str, Any]:
    """Recompute the plan and verify all approved bytes before any persistent write."""
    if (
        plan.get("schema_version") != "1.0"
        or not all(isinstance(plan.get(key), str) for key in ("source_root", "summary_root"))
        or not isinstance(plan.get("items"), list)
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and item.get("status") in ("planned", "unchanged", "blocked", "skipped")
            for item in plan.get("items", [])
        )
    ):
        raise ValueError("invalid migration plan format")
    paths = [item["path"] for item in plan["items"]]
    if len(paths) != len(set(paths)):
        raise ValueError("migration plan contains duplicate paths")
    source_root, summary_root = Path(plan["source_root"]), Path(plan["summary_root"])
    fresh = plan_migration(source_root, summary_root)
    fresh_by_path = {item["path"]: item for item in fresh["items"]}
    selected = [item for item in plan["items"] if item["status"] == "planned"]
    for item in selected:
        if fresh_by_path.get(item["path"]) != item:
            raise ValueError(f"migration plan is stale or modified: {item['path']}")
    if not selected:
        return {"status": "unchanged", "updated": 0, "counts": fresh["counts"]}
    run_root = (
        reports_root
        / "migrations"
        / (datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z") + "_" + uuid.uuid4().hex[:8])
    )
    atomic_write(run_root / "plan.json", json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    result: dict[str, Any] = {
        "status": "updated",
        "updated": 0,
        "backup_root": str(run_root),
        "counts": fresh["counts"],
        "files": [],
    }
    try:
        for index, item in enumerate(selected):
            path = Path(item["path"])
            payload = path.read_bytes()
            if (
                sha256_bytes(payload) != item["before_sha256"]
                or sha256_bytes(Path(item["source_path"]).read_bytes()) != item["source_sha256"]
            ):
                raise ValueError(f"file changed during migration: {path}")
            updated = patch_metadata(payload, item["changes"])
            if sha256_bytes(updated) != item["after_sha256"]:
                raise ValueError("migration result differs from the reviewed plan")
            backup = run_root / "backups" / f"{index:04d}.md"
            atomic_write(backup, payload)
            atomic_write(path, updated, overwrite=True)
            result["files"].append({"path": str(path), "backup": str(backup)})
            result["updated"] += 1
            atomic_write(run_root / "result.json", json.dumps(result, indent=2) + "\n", True)
    except Exception as exc:
        result.update(status="failed", error=str(exc))
        atomic_write(run_root / "result.json", json.dumps(result, indent=2) + "\n", True)
        raise RuntimeError(
            f"migration stopped; recovery report: {run_root / 'result.json'}"
        ) from exc
    return result
