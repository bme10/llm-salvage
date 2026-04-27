"""
Semantic validation of extracted data against a schema.

Validation happens after extraction and structural correction. It checks
meaning, not format. Returns a list of ValidationError describing what's
wrong; never raises and never modifies the original data dict.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .corrector import normalize_choice_value
from .schema import FieldType, Schema


@dataclass
class ValidationError:
    """A single validation failure for a field in the response."""

    field:   str
    code:    str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.code} — {self.message}"


def validate(
    data:   dict[str, Any],
    schema: Schema,
) -> tuple[dict[str, Any], list[str], list[ValidationError]]:
    """
    Validate extracted data against a schema.

    Returns:
        - normalized data (choice values uppercased, probabilities as
          dicts, week ranges as structured dicts, defaults filled in)
        - corrections applied during validation (e.g. case normalization,
          probability sum normalization)
        - list of ValidationError for fields that failed

    Never raises. Callers decide what to do with errors.
    """
    normalized: dict[str, Any] = dict(data)
    corrections: list[str] = []
    errors: list[ValidationError] = []

    for field_name, field_def in schema.fields.items():
        value = normalized.get(field_name)

        # ── Required / default handling ────────────────────────────────
        is_missing = value is None or (
            isinstance(value, str) and not value.strip()
        )

        if is_missing:
            if field_def.required:
                errors.append(ValidationError(
                    field=field_name,
                    code="missing_required",
                    message=f"Required field {field_name!r} was not found in the response",
                ))
                continue
            elif field_def.has_default:
                normalized[field_name] = field_def.default
                corrections.append(f"applied_default_{field_name}")
                continue
            else:
                # Optional, no default — drop from result rather than
                # leave a None entry.
                normalized.pop(field_name, None)
                continue

        # ── Type-specific validation ───────────────────────────────────
        if field_def.type == FieldType.CHOICE:
            normalized[field_name], val_errors, val_corrections = _validate_choice(
                field_name, value, field_def.choices
            )
            corrections.extend(val_corrections)
            errors.extend(val_errors)

        elif field_def.type == FieldType.STRING:
            normalized[field_name], val_errors, val_corrections = _validate_string(
                field_name, value, field_def
            )
            corrections.extend(val_corrections)
            errors.extend(val_errors)

        elif field_def.type == FieldType.PROBABILITY:
            normalized[field_name], val_errors, val_corrections = _validate_probability(
                field_name, value
            )
            corrections.extend(val_corrections)
            errors.extend(val_errors)

        elif field_def.type == FieldType.WEEK_RANGE:
            normalized[field_name] = _parse_week_range(value)

        elif field_def.type == FieldType.INTEGER:
            try:
                normalized[field_name] = int(str(value).strip())
            except (ValueError, TypeError):
                errors.append(ValidationError(
                    field=field_name,
                    code="invalid_integer",
                    message=f"Could not parse {value!r} as an integer",
                ))

        elif field_def.type == FieldType.FLOAT:
            try:
                normalized[field_name] = float(str(value).strip())
            except (ValueError, TypeError):
                errors.append(ValidationError(
                    field=field_name,
                    code="invalid_float",
                    message=f"Could not parse {value!r} as a float",
                ))

    return normalized, corrections, errors


# ── Per-type validators ──────────────────────────────────────────────────────

def _validate_choice(
    field_name: str,
    value:      Any,
    choices:    list[str],
) -> tuple[Any, list[ValidationError], list[str]]:
    """Validate a CHOICE field. Returns (normalized_value, errors, corrections)."""
    normalized_val, val_corrections = normalize_choice_value(str(value), choices)

    if normalized_val.upper() not in choices:
        return value, [ValidationError(
            field=field_name,
            code="invalid_choice",
            message=(
                f"Value {value!r} is not one of the allowed choices "
                f"{choices}. Closest correction attempt was {normalized_val!r}."
            ),
        )], val_corrections

    return normalized_val.upper(), [], val_corrections


def _validate_string(
    field_name: str,
    value:      Any,
    field_def,
) -> tuple[str, list[ValidationError], list[str]]:
    """Validate a STRING field. Returns (normalized_value, errors, corrections)."""
    text = str(value).strip()
    errors: list[ValidationError] = []
    corrections: list[str] = []

    # Check for unfilled template variables — these are typically prompt
    # placeholders that the model didn't fill in.
    unfilled = re.findall(r"\{[a-z_]+\}", text)
    if unfilled:
        errors.append(ValidationError(
            field=field_name,
            code="unfilled_template",
            message=(
                f"Field contains unfilled template variables: {unfilled}. "
                f"This usually means a prompt placeholder was emitted "
                f"verbatim rather than substituted."
            ),
        ))

    if field_def.min_length and len(text) < field_def.min_length:
        errors.append(ValidationError(
            field=field_name,
            code="too_short",
            message=(
                f"Field length {len(text)} is below the minimum "
                f"{field_def.min_length}"
            ),
        ))

    if field_def.max_length and len(text) > field_def.max_length:
        # Truncate silently — not an error, just a limit being enforced.
        text = text[: field_def.max_length]
        corrections.append(f"truncated_{field_name}")

    return text, errors, corrections


def _validate_probability(
    field_name: str,
    value:      Any,
) -> tuple[Any, list[ValidationError], list[str]]:
    """Validate a PROBABILITY field. Returns (normalized_value, errors, corrections)."""
    if not isinstance(value, dict):
        return value, [ValidationError(
            field=field_name,
            code="invalid_probability",
            message=(
                f"Expected a dict of label-to-int weights, "
                f"got {type(value).__name__}"
            ),
        )], []

    total = sum(value.values())
    errors: list[ValidationError] = []
    corrections: list[str] = []

    if not (98 <= total <= 102):  # allow ±2 for rounding
        errors.append(ValidationError(
            field=field_name,
            code="probability_sum",
            message=(
                f"Probability weights sum to {total}, expected ~100. "
                f"Weights: {value}"
            ),
        ))

    # Normalize to exactly 100 by adjusting the largest component, but
    # only when within a reasonable tolerance.
    if value and abs(total - 100) <= 5:
        largest_key = max(value, key=value.get)
        adjusted = dict(value)
        adjusted[largest_key] += (100 - total)
        if total != 100:
            corrections.append("normalized_probability_sum")
        return adjusted, errors, corrections

    return value, errors, corrections


def _parse_week_range(value: Any) -> dict[str, Any]:
    """Parse a WEEK_RANGE string like '2-4 weeks' into structured form."""
    text = str(value).strip()

    match = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*weeks?", text, re.IGNORECASE)
    if match:
        return {
            "min":  int(match.group(1)),
            "max":  int(match.group(2)),
            "unit": "weeks",
            "raw":  text,
        }

    # Single number — treat as min == max.
    match = re.search(r"(\d+)\s*weeks?", text, re.IGNORECASE)
    if match:
        n = int(match.group(1))
        return {"min": n, "max": n, "unit": "weeks", "raw": text}

    # Unparseable — preserve raw value, leave bounds unset.
    return {"min": None, "max": None, "unit": "weeks", "raw": text}
