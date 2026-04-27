"""
Telemetry — logs correction events to JSONL.

One JSON object per line, appended to a rotating log file. The caller
provides the log path; this module has no opinions about where logs
live or how they're rotated.

Logs at WARNING level when corrections were applied, at ERROR level
when validation failed.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def log_parse_event(
    log_path:     Path | str | None,
    model:        str,
    corrections:  list[str],
    errors:       list[Any],   # list of ValidationError; typed loosely to avoid circular import
    valid:        bool,
    task_id:      str = "",
    ticker:       str = "",
    task_type:    str = "",
    response_len: int = 0,
) -> None:
    """
    Log a parse event to the JSONL file and Python logger.

    Args:
        log_path:     Path to a .jsonl file. ``None`` skips file logging
                      (Python logging still happens).
        model:        Model name that produced the response.
        corrections:  Correction codes applied during parsing.
        errors:       ValidationError instances (or anything with ``.code``
                      and ``.field`` attributes).
        valid:        Whether the parse succeeded.
        task_id:      Optional task identifier.
        ticker:       Optional symbol/identifier (legacy field name).
        task_type:    Optional task category.
        response_len: Length of the original response in characters.
    """
    event = {
        "ts":           datetime.now(timezone.utc).isoformat(),
        "model":        model,
        "task_id":      task_id,
        "ticker":       ticker,
        "task_type":    task_type,
        "response_len": response_len,
        "valid":        valid,
        "corrections":  corrections,
        "error_codes":  [e.code for e in errors] if errors else [],
        "error_fields": [e.field for e in errors] if errors else [],
    }

    # Python logger.
    if corrections:
        logger.warning(
            "LLM parse corrections applied [%s/%s]: %s",
            model, task_type, ", ".join(corrections),
        )
    if not valid:
        logger.error(
            "LLM parse validation failed [%s/%s]: %s",
            model, task_type,
            "; ".join(str(e) for e in errors),
        )

    if log_path is None:
        return

    log_path = Path(log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError as exc:
        logger.warning("Could not write parse telemetry to %s: %s", log_path, exc)


def read_events(log_path: Path | str) -> list[dict]:
    """Read all events from a JSONL telemetry file."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []

    events: list[dict] = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed lines rather than abort the whole read.
                pass
    return events


def correction_summary(log_path: Path | str) -> dict[str, int]:
    """
    Summarize correction frequency from a telemetry log.

    Useful for identifying which corrections are most commonly needed
    across all logged parses, which suggests where prompt adjustments
    would have the biggest effect.

    Returns a dict of correction_code -> count, sorted by frequency
    descending.
    """
    events = read_events(log_path)
    summary: dict[str, int] = {}

    for event in events:
        for code in event.get("corrections", []):
            summary[code] = summary.get(code, 0) + 1

    return dict(sorted(summary.items(), key=lambda kv: kv[1], reverse=True))


def model_profile(log_path: Path | str, model: str) -> dict[str, Any]:
    """
    Build a behavior profile for a specific model from telemetry.

    Shows what corrections it consistently needs and what fraction of
    parses validated cleanly.

    Returns a dict with::

        {
            "model":          model name,
            "events":         total parses logged,
            "valid_pct":      percentage that validated cleanly,
            "corrections":    {code: count, ...} sorted descending,
            "top_correction": most frequent correction code,
        }
    """
    events = [e for e in read_events(log_path) if e.get("model") == model]
    if not events:
        return {"model": model, "events": 0}

    total = len(events)
    valid_count = sum(1 for e in events if e.get("valid"))

    corrections: dict[str, int] = {}
    for event in events:
        for code in event.get("corrections", []):
            corrections[code] = corrections.get(code, 0) + 1

    return {
        "model":          model,
        "events":         total,
        "valid_pct":      round(100 * valid_count / total, 1),
        "corrections":    dict(sorted(corrections.items(), key=lambda kv: kv[1], reverse=True)),
        "top_correction": max(corrections, key=corrections.get) if corrections else None,
    }
