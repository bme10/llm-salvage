"""
Format detection and structured data extraction.

Tries extraction formats in schema-defined order. Returns a raw extracted
dict — semantic validation happens in ``validator.py``.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .corrector import repair_json
from .schema import FieldType, Formats, Schema

# ── Tagged format extraction ──────────────────────────────────────────────────

def extract_tagged(
    text: str,
    wrapper_tags: list[str] | None = None,
    probability_field: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Extract ``[TAG]...[/TAG]`` content into a dict.

    Also handles the common local-model pattern where closing tags are
    omitted and the next opening tag serves as an implicit closer::

        [SENTIMENT] neutral [CONFIDENCE] medium [SUMMARY] one sentence

    In this case the parser treats each ``[TAG]`` as ending at the next
    ``[TAG]`` or at end-of-text.

    Args:
        text:              Response text.
        wrapper_tags:      Tag names whose contents are recursed into rather
                           than treated as field values. Compared
                           case-insensitively.
        probability_field: Name of a field with FieldType.PROBABILITY, if any.
                           When this tag is found, its content is parsed as
                           probability weights.

    Returned keys are lowercased tag names.
    """
    corrections: list[str] = []
    result: dict[str, Any] = {}
    wrapper_set = {t.upper() for t in (wrapper_tags or [])}
    prob_tag = probability_field.upper() if probability_field else None

    # Primary pattern: properly closed [TAG]...[/TAG] pairs.
    pattern = r"\[([A-Z_]+)\](.*?)\[/\1\]"
    matches = re.findall(pattern, text, re.DOTALL)

    for tag, content in matches:
        key = tag.upper()
        if key in wrapper_set:
            inner_result, _ = extract_tagged(
                content,
                wrapper_tags=wrapper_tags,
                probability_field=probability_field,
            )
            result.update(inner_result)
        elif prob_tag is not None and key == prob_tag:
            weights = _extract_probability_weights(content.strip())
            result[probability_field] = weights if weights else content.strip()
        else:
            result[tag.lower()] = content.strip()

    # Fallback: if no properly-closed tags were found, try extracting
    # unclosed tags where each [TAG] runs until the next [TAG] or end
    # of text. This handles the common local-model pattern:
    #   [SENTIMENT] neutral [CONFIDENCE] medium [SUMMARY] one sentence
    if not result:
        unclosed_pattern = r"\[([A-Z_]+)\]\s*(.*?)(?=\[[A-Z_]+\]|$)"
        unclosed_matches = re.findall(unclosed_pattern, text, re.DOTALL)

        if len(unclosed_matches) >= 2:
            # Only use the fallback when there are multiple tag-like
            # patterns — a single [TAG] could be a false positive from
            # prose containing bracketed words.
            corrections.append("extracted_unclosed_tags")
            for tag, content in unclosed_matches:
                key = tag.upper()
                content = content.strip()
                if not content:
                    continue
                if key in wrapper_set:
                    inner_result, _ = extract_tagged(
                        content,
                        wrapper_tags=wrapper_tags,
                        probability_field=probability_field,
                    )
                    result.update(inner_result)
                elif prob_tag is not None and key == prob_tag:
                    weights = _extract_probability_weights(content)
                    result[probability_field] = weights if weights else content
                else:
                    result[tag.lower()] = content

    return result, corrections


# ── JSON format extraction ────────────────────────────────────────────────────

def _build_key_map(schema: Schema) -> dict[str, str]:
    """
    Build the effective JSON-key-to-canonical-field map for a schema.

    Each schema field name becomes a self-mapping (e.g. ``"verdict" ->
    "verdict"``). User-supplied ``key_aliases`` are merged on top, so a
    user can override a field name's self-match if they need to.

    All keys are lowercased for case-insensitive matching.
    """
    base = {name.lower(): name for name in schema.fields}
    aliases = {k.lower(): v for k, v in schema.key_aliases.items()}
    return {**base, **aliases}


def _flatten_json(data: dict, prefix: str = "") -> dict:
    """Recursively flatten nested JSON into dot-separated keys."""
    flat: dict[str, Any] = {}
    for k, v in data.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            flat.update(_flatten_json(v, key))
        else:
            flat[key] = v
    return flat


def _extract_probability_weights(value: Any) -> dict[str, int] | None:
    """
    Extract probability weights from multiple possible formats.

    Accepts:
      - dict: ``{"option_a": 60, "option_b": 40}``
      - string: ``"option_a=60 option_b=40"``
      - string: ``"60/40"`` or ``"60:40"``

    Returns ``None`` if no recognizable probability data was found. Output
    is a plain dict of label → int; the validator's PROBABILITY type
    handles sum normalization.

    Scalar values are not accepted — a probability distribution requires
    at least two named or positional buckets. A bare number like ``50``
    is ambiguous (50% of what?) and is treated as unparseable rather than
    silently inflated into a two-bucket distribution with invented labels.
    """
    if isinstance(value, dict):
        # Pass through dicts of label -> int directly.
        result: dict[str, int] = {}
        for k, v in value.items():
            try:
                result[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        return result if result else None

    if isinstance(value, str):
        # "label=NN" pairs — generic, no label assumptions.
        pairs = re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*[=:]\s*(\d+)", value)
        if pairs:
            return {label: int(n) for label, n in pairs}

        # "60/40" or "60:40" shorthand — anonymous two-bucket split.
        match = re.search(r"(\d+)\s*[/:](\d+)", value)
        if match:
            return {
                "primary":   int(match.group(1)),
                "secondary": int(match.group(2)),
            }

    return None


def _extract_text_value(value: Any) -> str:
    """Convert any value to a string, handling nested dicts gracefully."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        # Try common narrative/rationale keys first.
        for key in ("rationale", "narrative", "description", "text",
                    "summary", "content", "value"):
            if key in value:
                return str(value[key]).strip()
        # Fall back to joining all string values.
        parts = [str(v) for v in value.values() if isinstance(v, str)]
        return " ".join(parts).strip()
    if isinstance(value, list):
        return " ".join(str(item) for item in value).strip()
    return str(value).strip()


def _find_probability_fields(
    data:    dict,
    key_map: dict[str, str],
    schema:  Schema,
    prefix:  str = "",
) -> tuple[dict[str, Any], set[str]]:
    """
    Walk a parsed JSON tree looking for keys that map to probability-typed
    schema fields. When found, extract the value (which may be a nested dict,
    a string, or a number) without flattening it.

    Returns:
        - dict of canonical_field_name -> extracted weights
        - set of dot-joined paths that should be excluded from later flattening
          (so probability sub-keys don't leak into other fields)
    """
    found: dict[str, Any] = {}
    excluded_paths: set[str] = set()

    for k, v in data.items():
        path = f"{prefix}.{k}" if prefix else k
        canonical = key_map.get(k.lower())
        if canonical:
            field_def = schema.fields.get(canonical)
            if field_def and field_def.type == FieldType.PROBABILITY and canonical not in found:
                weights = _extract_probability_weights(v)
                if weights:
                    found[canonical] = weights
                    # Mark every key under this path as off-limits to the
                    # flattened scan, so e.g. "confidence.high" doesn't get
                    # routed to a `high` schema field.
                    excluded_paths.add(path)
                    continue

        # Recurse into nested dicts, but only when this key didn't already
        # claim a probability field.
        if isinstance(v, dict):
            inner_found, inner_excluded = _find_probability_fields(
                v, key_map, schema, prefix=path
            )
            for fk, fv in inner_found.items():
                if fk not in found:
                    found[fk] = fv
            excluded_paths.update(inner_excluded)

    return found, excluded_paths


def _find_opaque_fields(
    data:    dict,
    key_map: dict[str, str],
    schema:  Schema,
    prefix:  str = "",
) -> tuple[dict[str, Any], set[str]]:
    """
    Find STRING fields with opaque=True anywhere in the tree.

    For each match, store the entire raw value as a JSON string (so nested
    structure is preserved) and add the path to the exclusion set so the
    flat scan doesn't recurse into it.

    Returns:
        - dict of field_name -> JSON string of the field's value
        - set of paths to exclude from subsequent flat scanning
    """
    found: dict[str, Any] = {}
    excluded_paths: set[str] = set()

    for k, v in data.items():
        path = f"{prefix}.{k}" if prefix else k
        canonical = key_map.get(k.lower())
        if canonical:
            field_def = schema.fields.get(canonical)
            if (field_def
                and field_def.type == FieldType.STRING
                and field_def.opaque
                and canonical not in found):
                # Serialize nested structures back to JSON for storage;
                # plain scalars get stringified directly.
                if isinstance(v, (dict, list)):
                    found[canonical] = json.dumps(v)
                else:
                    found[canonical] = str(v)
                excluded_paths.add(path)
                continue

        # Recurse into nested dicts only if this key didn't claim an
        # opaque field. Lists aren't recursed because list items don't
        # have keys to match against the schema.
        if isinstance(v, dict):
            inner_found, inner_excluded = _find_opaque_fields(
                v, key_map, schema, prefix=path
            )
            for fk, fv in inner_found.items():
                if fk not in found:
                    found[fk] = fv
            excluded_paths.update(inner_excluded)

    return found, excluded_paths


def extract_json(
    text: str,
    schema: Schema,
) -> tuple[dict[str, Any], list[str]]:
    """
    Extract structured data from JSON text against a schema.

    JSON keys are matched against schema field names directly (case-
    insensitive) plus any aliases the schema declares. Nested JSON is
    flattened so that ``{"thesis": {"summary": "..."}}`` matches a
    schema field named ``summary`` either via the leaf key or via an
    alias on the parent path.

    Probability-typed fields are detected before flattening to preserve
    the structure of nested dict values like
    ``{"confidence": {"high": 70, "medium": 20, "low": 10}}``.
    """
    corrections: list[str] = []

    # Attempt JSON repair before parsing.
    text, repair_corrections = repair_json(text)
    corrections.extend(repair_corrections)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}, corrections

    if not isinstance(data, dict):
        return {}, corrections

    key_map = _build_key_map(schema)
    result: dict[str, Any] = {}

    # First pass: find probability-typed fields anywhere in the tree and
    # extract them without flattening. This must happen before the flat scan
    # to prevent nested probability sub-keys (e.g. "confidence.high") from
    # being routed to unrelated schema fields.
    prob_results, excluded_paths = _find_probability_fields(data, key_map, schema)
    result.update(prob_results)

    # Find opaque-marked fields and capture their entire content as a JSON
    # string. Their paths are excluded from the flat scan so nested keys
    # within don't get matched to other schema fields. This is the fix for
    # envelope-style schemas where one field contains arbitrary content
    # (code blocks, prompt templates, escaped JSON) that shouldn't be
    # parsed as part of the parent.
    opaque_results, opaque_excluded = _find_opaque_fields(data, key_map, schema)
    result.update(opaque_results)
    excluded_paths.update(opaque_excluded)

    # Second pass: flatten the rest of the tree and scan flat keys.
    flat = _flatten_json(data)

    # Scan all keys (including nested) for known mappings. Also check the
    # parent path so nested cases like "thesis.summary" can match either
    # via "summary" (leaf) or via "thesis" (parent alias).
    for raw_key, value in flat.items():
        # Skip anything under a path that was claimed by a probability field.
        if any(raw_key == p or raw_key.startswith(p + ".") for p in excluded_paths):
            continue

        parts  = raw_key.split(".")
        leaf   = parts[-1].lower()
        parent = parts[-2].lower() if len(parts) > 1 else ""

        canonical = key_map.get(leaf) or key_map.get(parent)
        if not canonical or canonical in result:
            continue

        field_def = schema.fields.get(canonical)
        if field_def is None:
            continue

        # Type-specific extraction.
        if field_def.type == FieldType.PROBABILITY:
            # Probability fields were handled in the first pass; if we got
            # here, _find_probability_fields didn't extract anything usable
            # (e.g. the value was a scalar or string). Try again on the flat
            # value as a fallback.
            weights = _extract_probability_weights(value)
            if weights:
                result[canonical] = weights
        elif field_def.type == FieldType.STRING:
            text_val = _extract_text_value(value)
            # Skip very short strings that are probably stray keys leaking
            # through, not actual content. The validator's min_length will
            # also catch these but skipping early avoids polluting the dict.
            if text_val and len(text_val) > 2:
                result[canonical] = text_val
        else:
            result[canonical] = _extract_text_value(value)

    if result:
        corrections.append("json_format_used")

    return result, corrections


# ── Assignment format extraction ──────────────────────────────────────────────

def extract_assignment(
    text: str,
    schema: Schema,
) -> tuple[dict[str, Any], list[str]]:
    """
    Extract ``key = value`` or ``key: value`` lines.

    Handles::

        verdict = bullish
        confidence: high
        probability = {"a": 60, "b": 40}
        timeline = "3-4 weeks"

    Two or more spaces between key and value also work as a separator,
    helping with column-aligned output.
    """
    corrections: list[str] = []
    result: dict[str, Any] = {}

    key_map = _build_key_map(schema)
    prob_field = next(
        (n for n, f in schema.fields.items() if f.type == FieldType.PROBABILITY),
        None,
    )

    # Match: "key = value", "key: value", or "key   value" (2+ spaces).
    # Requires 2+ spaces in the bare-separator form to avoid matching prose.
    pattern = r"^([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*[=:]\s*|\s{2,})(.+)$"
    for line in text.strip().split("\n"):
        match = re.match(pattern, line.strip())
        if not match:
            continue

        raw_key = match.group(1).strip().lower()
        value   = match.group(2).strip().strip('"').strip("'")

        canonical = key_map.get(raw_key)
        if not canonical:
            continue

        # Try JSON parse for complex values (dicts, lists).
        if value.startswith(("{", "[")):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass

        if canonical == prob_field:
            weights = _extract_probability_weights(value)
            result[canonical] = weights if weights else value
        else:
            result[canonical] = value

    if result:
        corrections.append("assignment_format_used")

    return result, corrections


# ── Markdown bullet-list extraction ──────────────────────────────────────────

def extract_markdown(
    text: str,
    schema: Schema,
) -> tuple[dict[str, Any], list[str]]:
    """
    Extract structured data from markdown bullet/bold-label format.

    Handles the common LLM pattern of responding with markdown instead of
    JSON or tagged output::

        * **Category:** Headphones
        * **Brand:** Sony
        * **Price:** 349
        * **Key Features:**
            * Noise cancelling
            * 30-hour battery life

    Also handles dash bullets and non-bold labels::

        - Category: Headphones
        - Brand: Sony

    And bold-only (no bullet) headers from reasoning models::

        **Category:** Headphones
        **Brand:** Sony

    Multi-line values (sub-bullets under a key) are joined into a single
    string, which satisfies ``min_length`` constraints on string fields.

    Keys are matched against schema field names and aliases
    case-insensitively. Spaces and underscores in keys are interchangeable
    (``key features`` matches ``key_features``).
    """
    corrections: list[str] = []
    result: dict[str, Any] = {}

    key_map = _build_key_map(schema)

    # Extend the key map to handle space-separated variants of underscore keys.
    # e.g. "key features" -> "key_features" -> canonical
    extended_key_map = dict(key_map)
    for k, v in key_map.items():
        space_variant = k.replace("_", " ")
        if space_variant != k:
            extended_key_map[space_variant] = v

    # Primary line pattern: optional bullet, optional bold around key, colon.
    # Captures:
    #   * **Key:** value      (bold key, bullet)
    #   - **Key:** value      (bold key, dash bullet)
    #   **Key:** value        (bold key, no bullet)
    #   * Key: value          (plain key, bullet)
    line_pattern = re.compile(
        r"^(?:[*\-]\s*)?\*{0,2}([^*\n:]{2,60}?)\*{0,2}\s*:\s*(.*?)$",
        re.MULTILINE,
    )

    # Sub-item pattern: indented bullets that continue the previous key's value.
    sub_pattern = re.compile(
        r"^[ \t]+[*\-+]\s+(.+)$",
        re.MULTILINE,
    )

    lines = text.splitlines()
    i = 0
    last_canonical: str | None = None
    last_value_lines: list[str] = []

    def flush_last() -> None:
        """Store the accumulated value for the last seen key."""
        if last_canonical and last_value_lines:
            joined = "; ".join(v.strip() for v in last_value_lines if v.strip())
            if joined and last_canonical not in result:
                result[last_canonical] = joined

    while i < len(lines):
        line = lines[i]

        m = line_pattern.match(line)
        if m:
            flush_last()
            raw_key = m.group(1).strip().strip("*").strip().lower()
            raw_val = m.group(2).strip().strip("*").strip()

            canonical = extended_key_map.get(raw_key)
            if canonical:
                last_canonical = canonical
                last_value_lines = [raw_val] if raw_val else []
            else:
                last_canonical = None
                last_value_lines = []
        elif last_canonical and sub_pattern.match(line):
            # Sub-bullet continuing previous key's value.
            sub_m = sub_pattern.match(line)
            if sub_m:
                last_value_lines.append(sub_m.group(1).strip())
        elif last_canonical and line.strip() and not line_pattern.match(line):
            # Continuation line (plain text after a key with no inline value).
            last_value_lines.append(line.strip())

        i += 1

    flush_last()

    # Store everything collected.
    for canonical, joined_value in result.copy().items():
        field_def = schema.fields.get(canonical)
        if field_def is None:
            del result[canonical]
            continue
        # Let the validator handle type coercion — store as string for now.
        # The validator's INTEGER/FLOAT handlers accept string input.
        result[canonical] = joined_value.strip()

    if result:
        corrections.append("markdown_format_used")

    return result, corrections

def detect_format(text: str) -> Formats:
    """
    Detect the primary format of the response.

    Returns ``HYBRID`` if the response contains both tagged and JSON
    sections; otherwise the dominant format. Falls back to ``TAGGED``
    when neither is clearly present.
    """
    has_tags = bool(re.search(r"\[[A-Z_]+\]", text))

    # Important: a tagged response starts with `[`, so a leading-bracket
    # check alone misclassifies tagged content as JSON. Treat a leading `[`
    # as JSON only when no tags are present in the response.
    stripped = text.lstrip()
    has_json = (
        stripped.startswith("{")
        or (stripped.startswith("[") and not has_tags)
    )
    has_assignment = bool(
        re.search(r"^[a-zA-Z_]+\s*[=:]\s*.+$", text, re.MULTILINE)
    )

    if has_tags and has_json:
        return Formats.HYBRID
    if has_tags:
        return Formats.TAGGED
    if has_json:
        return Formats.JSON

    # JSON buried in code fences (already stripped by structural pass, but
    # belt-and-braces).
    if re.search(r"```(?:json)?\s*\{", text, re.DOTALL):
        return Formats.JSON

    if has_assignment:
        # extract() will fall through to the assignment extractor.
        return Formats.TAGGED

    return Formats.TAGGED


def extract(
    text: str,
    schema: Schema,
) -> tuple[dict[str, Any], list[str]]:
    """
    Try extraction formats in schema-defined order.

    Returns the first non-empty extraction, plus all correction codes
    applied along the way. Falls through to assignment-format extraction
    as a final attempt.
    """
    all_corrections: list[str] = []

    detected = detect_format(text)

    # Reorder so the detected format is tried first.
    ordered = [detected] + [f for f in schema.formats if f != detected]
    seen: set[Formats] = set()
    ordered = [f for f in ordered if not (f in seen or seen.add(f))]

    # Find the probability field (if any) so the tagged extractor knows
    # which tag to parse as weights.
    prob_field = next(
        (n for n, f in schema.fields.items() if f.type == FieldType.PROBABILITY),
        None,
    )

    for fmt in ordered:
        if fmt == Formats.TAGGED:
            result, corrections = extract_tagged(
                text,
                wrapper_tags=schema.wrapper_tags,
                probability_field=prob_field,
            )
        elif fmt in (Formats.JSON, Formats.HYBRID):
            result, corrections = extract_json(text, schema)
            if not result and fmt == Formats.HYBRID:
                tag_result, tag_corrections = extract_tagged(
                    text,
                    wrapper_tags=schema.wrapper_tags,
                    probability_field=prob_field,
                )
                result.update(tag_result)
                corrections.extend(tag_corrections)
        else:
            continue

        all_corrections.extend(corrections)
        if result:
            return result, all_corrections

    # Final fallbacks — assignment then markdown.
    result, corrections = extract_assignment(text, schema)
    all_corrections.extend(corrections)
    if result:
        return result, all_corrections

    result, corrections = extract_markdown(text, schema)
    all_corrections.extend(corrections)
    if result:
        return result, all_corrections

    return {}, all_corrections
