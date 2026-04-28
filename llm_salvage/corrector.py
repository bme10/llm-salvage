"""
Deterministic correction pipeline.

Each corrector is a pure function:
    (text, ...) -> (corrected_text, list[str])

The list contains correction codes that were applied. Corrections never
raise — they either fix or pass through unchanged.
"""
from __future__ import annotations

import json
import re

# ── Structural corrections ────────────────────────────────────────────────────

def strip_code_fences(text: str) -> tuple[str, list[str]]:
    """Remove ``` and ~~~ wrappers, with or without a language tag."""
    corrections: list[str] = []
    original = text
    text = text.strip()

    # Remove opening fence with optional language tag.
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
    text = re.sub(r"^~~~[a-zA-Z]*\s*\n?", "", text)

    # Remove closing fence.
    text = re.sub(r"\n?```\s*$", "", text)
    text = re.sub(r"\n?~~~\s*$", "", text)

    text = text.strip()
    if text != original.strip():
        corrections.append("stripped_code_fences")

    return text, corrections


def normalize_line_endings(text: str) -> tuple[str, list[str]]:
    """Normalize CRLF and stray CR to LF."""
    corrections: list[str] = []
    original = text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text != original:
        corrections.append("normalized_line_endings")
    return text, corrections


def strip_bom(text: str) -> tuple[str, list[str]]:
    """Remove a leading byte-order mark, if present."""
    corrections: list[str] = []
    if text.startswith("\ufeff"):
        text = text[1:]
        corrections.append("stripped_bom")
    return text, corrections


# ── Tag corrections ───────────────────────────────────────────────────────────

def normalize_tag_names(
    text: str,
    tag_aliases: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """
    Apply tag-name aliases to fix typos and spacing variants.

    Args:
        text:        Response text containing ``[TAG]`` and ``[/TAG]`` markers.
        tag_aliases: Mapping from wrong-form to correct-form tag names
                     (uppercase keys and values).

    No-op when ``tag_aliases`` is empty or None.
    """
    corrections: list[str] = []
    if not tag_aliases:
        return text, corrections

    for wrong, correct in tag_aliases.items():
        # Match [WRONG], [/WRONG] patterns case-insensitively.
        pattern = rf"\[(/?)({re.escape(wrong)})\]"
        if re.search(pattern, text, re.IGNORECASE):
            text = re.sub(
                pattern,
                lambda m, c=correct: f"[{m.group(1)}{c}]",
                text,
                flags=re.IGNORECASE,
            )
            # Sanitize the correction code so it's safe in JSONL/logs.
            safe = wrong.lower().replace(" ", "_").replace("-", "_")
            corrections.append(f"fixed_tag_{safe}")

    return text, corrections


def close_unclosed_tags(
    text: str,
    known_tags: list[str],
) -> tuple[str, list[str]]:
    """
    If a known opening tag exists without a matching closing tag, insert it.

    Only acts on tags in ``known_tags`` to avoid false positives. The
    typical caller passes the schema's field names (uppercased).

    Closing tags are inserted *immediately before the next opening tag*
    rather than appended to the end of the document. This handles the
    mixed-closer pattern common in compact models::

        [VERDICT] foo
        [SEVERITY] bar
        [BLOCKING] yes [/BLOCKING]

    where only the last tag has a closer. Inserting closers before each
    subsequent tag lets the primary ``[TAG]...[/TAG]`` regex match each
    field independently rather than treating the entire document as one
    field's content.

    When *no* tags in the response have closers, this corrector does
    nothing — the response is using the fully-unclosed style and the
    extractor's fallback handles it better.
    """
    corrections: list[str] = []

    open_tags = [
        tag for tag in known_tags
        if re.search(rf"\[{tag}\]", text)
    ]
    closed_tags = [
        tag for tag in known_tags
        if re.search(rf"\[/{tag}\]", text)
    ]

    # If no tags have closers at all, leave the text alone — the
    # extractor's unclosed-tag fallback will handle this style.
    if open_tags and not closed_tags:
        return text, corrections

    # For each open tag that lacks a closer, insert the closer immediately
    # before the next opening tag (or at the end if it's the last field).
    for tag in open_tags:
        if re.search(rf"\[/{tag}\]", text):
            continue  # already has a closer

        # Find where [TAG] appears, then look for the next [ANY_TAG] after it.
        open_match = re.search(rf"\[{tag}\]", text)
        if not open_match:
            continue

        # Build a pattern that matches any opening tag that comes AFTER
        # the current tag's content starts.
        search_from = open_match.end()
        tail = text[search_from:]

        # Look for the next known opening tag in the tail.
        next_open = re.search(r"\[([A-Z_]+)\]", tail)
        if next_open:
            # Insert the closer just before the next opening tag.
            insert_pos = search_from + next_open.start()
            text = text[:insert_pos] + f"[/{tag}]\n" + text[insert_pos:]
        else:
            # This is the last field — append at the end.
            text += f"\n[/{tag}]"

        corrections.append(f"closed_unclosed_{tag.lower()}")

    return text, corrections


# ── Value corrections ─────────────────────────────────────────────────────────

def normalize_choice_value(
    value: str,
    choices: list[str],
) -> tuple[str, list[str]]:
    """
    Normalize a value to one of the allowed choices.

    Strategy, in order:
        1. Exact match (case-insensitive) — uppercase the value.
        2. Prefix match (e.g. ``"Bull"`` matches ``"BULLISH"``).
        3. Edit distance 1 — for values longer than 5 characters.

    Returns the normalized value plus any correction codes applied. On
    failure returns the original value unchanged; the validator will
    flag it.
    """
    corrections: list[str] = []
    upper = value.strip().upper()

    # Exact match.
    if upper in choices:
        if upper != value.strip():
            corrections.append(f"case_normalized_{upper}")
        return upper, corrections

    # Prefix match — handles "Bull" → "BULLISH" and "BULLI" → "BULLISH".
    for choice in choices:
        if choice.startswith(upper) or upper.startswith(choice[:4]):
            corrections.append(f"prefix_matched_{upper}_to_{choice}")
            return choice, corrections

    # Edit distance 1 for values long enough that the heuristic is reliable.
    if len(upper) > 5:
        for choice in choices:
            if len(choice) > 5 and _edit_distance(upper, choice) == 1:
                corrections.append(f"typo_corrected_{upper}_to_{choice}")
                return choice, corrections

    # No match — return original; validator will report invalid_choice.
    return value, corrections


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance — simple DP implementation."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,
                curr[j] + 1,
                prev[j] + (ca != cb),
            ))
        prev = curr
    return prev[len(b)]


def repair_json(text: str) -> tuple[str, list[str]]:
    """
    Attempt to repair common JSON formatting issues.

    Tries the ``json-repair`` package first if available, falling back to
    a small set of built-in heuristics. To use json-repair::

        pip install 'llm-salvage[repair]'

    Returns repaired text plus correction codes, or the original text and
    an empty list if repair was impossible.
    """
    # Already valid? Nothing to do.
    try:
        json.loads(text)
        return text, []
    except json.JSONDecodeError:
        pass

    # Try the json-repair package if installed — it handles many more cases
    # than the built-in heuristics below.
    repaired = _try_json_repair_package(text)
    if repaired is not None:
        return repaired, ["repaired_via_json_repair"]

    return _builtin_json_repair(text)


def _try_json_repair_package(text: str) -> str | None:
    """Use json-repair if installed, returning None if unavailable or unrepairable."""
    stripped = text.lstrip()

    # Don't waste cycles on text that obviously isn't JSON. json-repair is
    # permissive enough to turn arbitrary prose — including tagged content —
    # into valid-looking JSON, which produces misleading correction codes.
    if not stripped.startswith(("{", "[")):
        return None

    # `[TAG_NAME]` shapes look like JSON arrays to a naive prefix check
    # but are tagged content. Skip those explicitly.
    if re.match(r"\[[A-Z_]+\]", stripped):
        return None

    try:
        from json_repair import repair_json as _repair  # type: ignore[import-not-found]
    except ImportError:
        return None

    try:
        repaired = _repair(text)
        # Verify the result actually parses and isn't an empty stub.
        if not repaired or repaired in ("{}", "[]", '""'):
            return None
        json.loads(repaired)
        return repaired
    except Exception:  # noqa: BLE001 — defensive; we fall through to builtin
        return None


def _builtin_json_repair(text: str) -> tuple[str, list[str]]:
    """
    Built-in JSON repair using a small set of common-case heuristics.

    Used when the json-repair package isn't installed. Covers trailing
    commas, single quotes, and truncation at the last complete object.
    """
    # Remove trailing commas before } or ].
    attempt = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        json.loads(attempt)
        return attempt, ["removed_trailing_commas"]
    except json.JSONDecodeError:
        pass

    # Replace single quotes with double quotes — naive, but works for the
    # common case of LLMs emitting JS-style object literals.
    attempt = text.replace("'", '"')
    try:
        json.loads(attempt)
        return attempt, ["replaced_single_quotes"]
    except json.JSONDecodeError:
        pass

    # Truncate at the last complete object/array close.
    for end_char in ("}", "]"):
        idx = text.rfind(end_char)
        if idx > 0:
            attempt = text[: idx + 1]
            try:
                json.loads(attempt)
                return attempt, ["truncated_to_last_complete"]
            except json.JSONDecodeError:
                pass

    return text, []


# ── Correction pipeline ───────────────────────────────────────────────────────

def apply_structural_corrections(
    text: str,
    tag_aliases: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """
    Apply all structural corrections in order.

    Returns the corrected text and a flat list of all correction codes
    applied across the pipeline.
    """
    all_corrections: list[str] = []

    text, c = strip_bom(text);                                    all_corrections.extend(c)
    text, c = normalize_line_endings(text);                       all_corrections.extend(c)
    text, c = strip_code_fences(text);                            all_corrections.extend(c)
    text, c = normalize_tag_names(text, tag_aliases=tag_aliases); all_corrections.extend(c)

    return text, all_corrections
