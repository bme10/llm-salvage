"""
Schema and Field definitions for LLM response parsing.

Schemas are plain dataclasses with no required dependencies. They can be
defined in code or loaded from YAML, JSON, or TOML files via
``Schema.from_file()``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class FieldType(str, Enum):
    """Supported field types for schema validation."""

    STRING      = "string"
    CHOICE      = "choice"       # enum of allowed values
    PROBABILITY = "probability"  # dict of label->int, sums to ~100
    WEEK_RANGE  = "week_range"   # "X-Y weeks" → {"min": X, "max": Y}
    INTEGER     = "integer"
    FLOAT       = "float"


class Formats(str, Enum):
    """Output formats the parser will attempt during extraction."""

    TAGGED = "tagged"  # [TAG]...[/TAG]
    JSON   = "json"    # {"key": "value"}
    HYBRID = "hybrid"  # mixed — try both


# Sentinel distinct from None — lets callers explicitly set a None default
# while still distinguishing "no default supplied" from "default is None".
_UNSET = object()


@dataclass
class Field:
    """
    Definition of a single expected output field.

    Args:
        type:       Field type. Inferred from other arguments when possible —
                    ``Field(choices=[...])`` is a CHOICE field;
                    ``Field(min_length=20)`` is a STRING field. Specify
                    explicitly when inference would be wrong.
        required:   If True, absence in the response produces an error.
                    If False, absence is silent unless ``default`` is set.
        choices:    For CHOICE type — allowed values. Comparison is
                    case-insensitive; values are normalized to uppercase.
        min_length: For STRING type — minimum character count.
        max_length: For STRING type — maximum character count. Values
                    exceeding this are truncated, not rejected.
        default:    Value used for optional fields that are missing from
                    the response. Ignored for required fields.
        opaque:     For STRING type — when True, the field's value is treated
                    as an opaque string and never scanned for nested tagged
                    or assignment-format content during extraction. Use this
                    for envelope-like fields whose contents may contain
                    markup-like text (code blocks, prompt templates, escaped
                    JSON) that should not be parsed as part of the parent
                    schema. Only meaningful for JSON-format extraction;
                    tagged-format extraction is structural and unaffected.
    """

    type:       FieldType = FieldType.STRING
    required:   bool      = True
    choices:    list[str] = field(default_factory=list)
    min_length: int       = 0
    max_length: int       = 0
    default:    Any       = _UNSET
    opaque:     bool      = False

    def __post_init__(self) -> None:
        if self.choices:
            self.type = FieldType.CHOICE
            # Normalize choices to uppercase for case-insensitive comparison.
            self.choices = [c.upper() for c in self.choices]

    @property
    def has_default(self) -> bool:
        """True when a default value was explicitly supplied."""
        return self.default is not _UNSET


# Codes considered critical by default — these prevent ParseResult.ok from
# being True even when corrections were applied. Schemas can override via
# ``Schema.critical_codes``.
DEFAULT_CRITICAL_CODES: frozenset[str] = frozenset({
    "missing_required",
    "invalid_choice",
    "unfilled_template",
    "no_content",
})


@dataclass
class Schema:
    """
    Defines the expected structure of an LLM response.

    Args:
        fields:         Dict of field_name -> Field.
        formats:        Ordered list of formats to attempt during extraction.
                        Defaults to ``[TAGGED, JSON]``.
        key_aliases:    Extra mappings from JSON keys to canonical field
                        names. The library auto-matches schema field names
                        directly; aliases handle legacy or domain-specific
                        keys (e.g. ``{"directional_bias": "verdict"}``).
        tag_aliases:    Mappings from tag-name typos or variants to their
                        canonical form (e.g. ``{"VERDCT": "VERDICT"}``).
                        Applied case-insensitively to ``[TAG]`` and
                        ``[/TAG]`` markers before extraction.
        wrapper_tags:   Tag names whose contents contain other tags worth
                        extracting (e.g. an outer ``[ANALYSIS]`` block
                        wrapping ``[VERDICT]``, ``[CONFIDENCE]`` etc.).
                        Wrapper-tag contents are recursed into rather
                        than treated as field values.
        critical_codes: Validation error codes that prevent ``ParseResult.ok``
                        from being True. Defaults to the most common
                        critical codes; override to customize per use case.
    """

    fields:         dict[str, Field]
    formats:        list[Formats]    = field(
        default_factory=lambda: [Formats.TAGGED, Formats.JSON]
    )
    key_aliases:    dict[str, str]   = field(default_factory=dict)
    tag_aliases:    dict[str, str]   = field(default_factory=dict)
    wrapper_tags:   list[str]        = field(default_factory=list)
    critical_codes: frozenset[str]   = field(
        default_factory=lambda: DEFAULT_CRITICAL_CODES
    )

    def __post_init__(self) -> None:
        # Normalize tag aliases to uppercase for consistent matching.
        self.tag_aliases = {
            k.upper(): v.upper() for k, v in self.tag_aliases.items()
        }
        # Normalize wrapper tags to uppercase.
        self.wrapper_tags = [t.upper() for t in self.wrapper_tags]
        # Coerce critical_codes to frozenset if a list/set was passed.
        if not isinstance(self.critical_codes, frozenset):
            self.critical_codes = frozenset(self.critical_codes)

    # ── File loading ──────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: Path | str) -> Schema:
        """
        Load a schema definition from a file.

        Supports YAML (.yaml, .yml), JSON (.json), and TOML (.toml) by
        extension. YAML support requires ``pip install 'llm-salvage[yaml]'``;
        TOML uses the standard library on Python 3.11+ and falls back to
        ``tomli`` on 3.10 if installed.

        Schema file format::

            fields:
              verdict:
                choices: [bullish, bearish, neutral]
              summary:
                min_length: 20
                max_length: 500
              priority:
                type: integer
                required: false
                default: 0

            formats: [tagged, json]
            key_aliases:
              directional_bias: verdict
            tag_aliases:
              VERDCT: VERDICT
            wrapper_tags: [analysis]
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {path}")

        suffix = path.suffix.lower()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # Most common cause: the file was saved with the system default
            # encoding (cp1252 on Windows) rather than UTF-8. Re-raise with
            # a clearer, actionable message.
            raise UnicodeDecodeError(
                exc.encoding,
                exc.object,
                exc.start,
                exc.end,
                (
                    f"Schema file {str(path)!r} is not valid UTF-8 "
                    f"(byte 0x{exc.object[exc.start]:02x} at position {exc.start}). "
                    f"Re-save the file as UTF-8. Most editors offer this option "
                    f"in their save dialog (look for 'Encoding' or 'Save with encoding')."
                ),
            ) from exc

        if suffix in (".yaml", ".yml"):
            data = _load_yaml(text)
        elif suffix == ".json":
            data = json.loads(text)
        elif suffix == ".toml":
            data = _load_toml(text)
        else:
            raise ValueError(
                f"Unsupported schema file extension: {suffix!r}. "
                f"Use .yaml, .yml, .json, or .toml."
            )

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Schema:
        """
        Build a Schema from a plain dict (as parsed from YAML/JSON/TOML).

        Field types in the dict can be strings (``"string"``, ``"choice"``,
        etc.) — they're converted to ``FieldType`` enum values automatically.
        """
        if "fields" not in data:
            raise ValueError("Schema definition must contain a 'fields' key")

        fields_dict = {}
        for name, field_def in data["fields"].items():
            if not isinstance(field_def, dict):
                raise ValueError(
                    f"Field {name!r} must be a dict, got {type(field_def).__name__}"
                )
            fields_dict[name] = _field_from_dict(field_def)

        formats = [Formats(f) for f in data.get("formats", ["tagged", "json"])]

        kwargs: dict[str, Any] = {
            "fields": fields_dict,
            "formats": formats,
            "key_aliases": data.get("key_aliases", {}),
            "tag_aliases": data.get("tag_aliases", {}),
            "wrapper_tags": data.get("wrapper_tags", []),
        }
        if "critical_codes" in data:
            kwargs["critical_codes"] = frozenset(data["critical_codes"])

        return cls(**kwargs)


def _field_from_dict(d: dict[str, Any]) -> Field:
    """
    Build a Field from a dict. Coerces 'type' from string to FieldType.

    YAML 1.1 auto-converts bare ``yes``/``no``/``on``/``off``/``true``/``false``
    to Python booleans. To allow these as choice values without schema authors
    having to remember to quote them, we coerce ``choices`` items and the
    ``default`` value to strings here. Schema authors writing JSON or TOML
    don't hit this issue.
    """
    kwargs: dict[str, Any] = {}

    if "type" in d:
        kwargs["type"] = FieldType(d["type"])
    if "required" in d:
        kwargs["required"] = bool(d["required"])
    if "choices" in d:
        # Coerce each choice to a string. Handles bool from YAML auto-conversion
        # (yes/no/true/false), int (e.g. status codes), and other non-string types
        # that schema authors might supply.
        kwargs["choices"] = [_choice_to_string(c) for c in d["choices"]]
    if "min_length" in d:
        kwargs["min_length"] = int(d["min_length"])
    if "max_length" in d:
        kwargs["max_length"] = int(d["max_length"])
    if "default" in d:
        # Coerce default similarly when the field looks choice-shaped, to keep
        # the default consistent with the (now string-coerced) choices.
        if "choices" in d and not isinstance(d["default"], (dict, list)):
            kwargs["default"] = _choice_to_string(d["default"])
        else:
            kwargs["default"] = d["default"]
    if "opaque" in d:
        kwargs["opaque"] = bool(d["opaque"])

    return Field(**kwargs)


def _choice_to_string(value: Any) -> str:
    """
    Convert a choice value to its string form, with YAML-bool aware mapping.

    Python ``True`` / ``False`` become ``"yes"`` / ``"no"`` rather than
    ``"True"`` / ``"False"``, since the most common reason to see a bool here
    is YAML's auto-conversion of bare ``yes``/``no``.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _load_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "Loading YAML schema files requires PyYAML. "
            "Install with: pip install 'llm-salvage[yaml]'"
        ) from exc
    result = yaml.safe_load(text)
    if not isinstance(result, dict):
        raise ValueError("YAML schema must be a mapping at the top level")
    return result


def _load_toml(text: str) -> dict[str, Any]:
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ImportError as exc:
            raise ImportError(
                "Loading TOML schema files on Python 3.10 requires tomli. "
                "Install with: pip install tomli"
            ) from exc
    return tomllib.loads(text)
