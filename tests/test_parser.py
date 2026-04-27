"""
Tests for the core parsing pipeline.

Covers the same scenarios the original handwritten test file did, but
restructured into pytest functions and with generic-domain examples
that don't tie the library to any one industry.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_salvage import (
    Field,
    FieldType,
    Formats,
    ResponseParser,
    Schema,
    correction_summary,
    model_profile,
    read_events,
)

# ── Shared schema for the bulk of tests ─────────────────────────────────────

SENTIMENT_SCHEMA = Schema(
    fields={
        "sentiment":   Field(choices=["positive", "negative", "neutral"]),
        "confidence":  Field(choices=["high", "medium", "low"]),
        "summary":     Field(min_length=20),
        "key_quote":   Field(required=False),
    },
    formats=[Formats.TAGGED, Formats.JSON],
)


@pytest.fixture
def parser() -> ResponseParser:
    return ResponseParser(SENTIMENT_SCHEMA, model="test")


# ── Tagged format ───────────────────────────────────────────────────────────

def test_tagged_clean(parser: ResponseParser) -> None:
    response = """
[SENTIMENT] positive [/SENTIMENT]
[CONFIDENCE] high [/CONFIDENCE]
[SUMMARY]
The product launch exceeded expectations across all key metrics including
revenue, user engagement, and press coverage.
[/SUMMARY]
[KEY_QUOTE] "best launch we've ever had" [/KEY_QUOTE]
"""
    result = parser.parse(response)
    assert result.ok
    assert result.data["sentiment"] == "POSITIVE"
    assert result.data["confidence"] == "HIGH"
    assert "exceeded expectations" in result.data["summary"]


def test_tagged_with_code_fences_stripped(parser: ResponseParser) -> None:
    response = """
```
[SENTIMENT] negative [/SENTIMENT]
[CONFIDENCE] medium [/CONFIDENCE]
[SUMMARY]
Customer feedback indicates significant frustration with the new pricing
model and reduced feature set in the standard tier.
[/SUMMARY]
```
"""
    result = parser.parse(response)
    assert result.ok
    assert result.data["sentiment"] == "NEGATIVE"
    assert "stripped_code_fences" in result.corrections


def test_tagged_lowercase_choice_normalized(parser: ResponseParser) -> None:
    response = """
[SENTIMENT] neutral [/SENTIMENT]
[CONFIDENCE] low [/CONFIDENCE]
[SUMMARY]
The response patterns suggest no clear directional preference among the
surveyed group, with feedback distributed evenly across categories.
[/SUMMARY]
"""
    result = parser.parse(response)
    assert result.ok
    assert result.data["sentiment"] == "NEUTRAL"


def test_tagged_with_alias_typo_fix() -> None:
    """Schemas can declare tag aliases for known typos."""
    schema = Schema(
        fields={
            "verdict":    Field(choices=["yes", "no", "maybe"]),
            "confidence": Field(choices=["high", "medium", "low"]),
            "reasoning":  Field(min_length=20),
        },
        tag_aliases={"VERDCT": "VERDICT", "REASONNING": "REASONING"},
    )
    parser = ResponseParser(schema)
    response = """
[VERDCT] yes [/VERDCT]
[CONFIDENCE] high [/CONFIDENCE]
[REASONNING]
The evidence strongly supports the conclusion based on multiple
independent data sources converging on the same answer.
[/REASONNING]
"""
    result = parser.parse(response)
    assert result.ok
    assert result.data["verdict"] == "YES"
    assert any(c.startswith("fixed_tag_") for c in result.corrections)


def test_tagged_unclosed_tag_auto_closed(parser: ResponseParser) -> None:
    """An unclosed tag at the end of a response gets auto-closed."""
    response = """
[SENTIMENT] positive [/SENTIMENT]
[CONFIDENCE] high [/CONFIDENCE]
[SUMMARY]
The library handles unclosed tags by appending the missing closer, which
is common when models truncate output near token limits.
"""
    result = parser.parse(response)
    assert result.ok
    assert any(c.startswith("closed_unclosed_") for c in result.corrections)


# ── JSON format ─────────────────────────────────────────────────────────────

def test_json_flat_structure(parser: ResponseParser) -> None:
    response = """
{
    "sentiment": "negative",
    "confidence": "high",
    "summary": "Several reviewers reported significant issues with the latest update affecting core workflows."
}
"""
    result = parser.parse(response)
    assert result.ok
    assert result.data["sentiment"] == "NEGATIVE"


def test_json_nested_structure_with_key_aliases() -> None:
    """Aliases let nested LLM-style JSON map to flat schema fields."""
    schema = Schema(
        fields={
            "topic":      Field(choices=["billing", "technical", "general"]),
            "priority":   Field(choices=["urgent", "normal", "low"]),
            "summary":    Field(min_length=10),
        },
        key_aliases={
            "category":      "topic",
            "urgency_level": "priority",
            "description":   "summary",
        },
    )
    parser = ResponseParser(schema)
    response = """
```json
{
  "ticket": {
    "category": "billing",
    "urgency_level": "urgent",
    "description": "Customer was double-charged for the annual subscription renewal."
  },
  "metadata": {
    "received_at": "2026-01-15T10:30:00Z"
  }
}
```
"""
    result = parser.parse(response)
    assert result.ok
    assert result.data["topic"] == "BILLING"
    assert result.data["priority"] == "URGENT"


def test_json_trailing_comma_repaired(parser: ResponseParser) -> None:
    response = """
{
    "sentiment": "neutral",
    "confidence": "low",
    "summary": "Mixed feedback with no dominant pattern emerging from the data set so far.",
}
"""
    result = parser.parse(response)
    assert result.ok
    # Either the json-repair package or the builtin handles this.
    assert any(
        c in result.corrections
        for c in ("removed_trailing_commas", "repaired_via_json_repair")
    )


# ── Edge cases ──────────────────────────────────────────────────────────────

def test_empty_response_fails_cleanly(parser: ResponseParser) -> None:
    result = parser.parse("")
    assert not result.ok
    assert any(e.code == "no_content" for e in result.errors)


def test_garbage_response_fails_cleanly(parser: ResponseParser) -> None:
    result = parser.parse(
        "I think the answer is probably yes but I'm not entirely sure about it."
    )
    assert not result.ok


def test_unfilled_template_detected(parser: ResponseParser) -> None:
    response = """
[SENTIMENT] positive [/SENTIMENT]
[CONFIDENCE] high [/CONFIDENCE]
[SUMMARY] {summary_placeholder} [/SUMMARY]
"""
    result = parser.parse(response)
    assert not result.ok
    assert any(e.code == "unfilled_template" for e in result.errors)


def test_missing_required_field_fails(parser: ResponseParser) -> None:
    response = """
[CONFIDENCE] high [/CONFIDENCE]
[SUMMARY]
A summary that meets the minimum length requirement set by the schema.
[/SUMMARY]
"""
    result = parser.parse(response)
    assert not result.ok
    assert any(
        e.code == "missing_required" and e.field == "sentiment"
        for e in result.errors
    )


# ── Default values ──────────────────────────────────────────────────────────

def test_optional_field_with_default_filled_in() -> None:
    schema = Schema(
        fields={
            "topic":              Field(choices=["bug", "feature", "question"]),
            "needs_human_review": Field(required=False, default="no"),
        },
    )
    parser = ResponseParser(schema)
    response = "[TOPIC] bug [/TOPIC]"
    result = parser.parse(response)
    assert result.ok
    assert result.data["needs_human_review"] == "no"
    assert "applied_default_needs_human_review" in result.corrections


def test_optional_field_no_default_omitted() -> None:
    """Optional fields without defaults that are missing should be absent."""
    schema = Schema(
        fields={
            "topic":   Field(choices=["bug", "feature", "question"]),
            "details": Field(required=False),
        },
    )
    parser = ResponseParser(schema)
    response = "[TOPIC] feature [/TOPIC]"
    result = parser.parse(response)
    assert result.ok
    assert "details" not in result.data


# ── Critical codes override ─────────────────────────────────────────────────

def test_schema_can_override_critical_codes() -> None:
    """A schema can declare which error codes block ParseResult.ok."""
    # Default behavior — too_short is non-critical, parse is still ok.
    schema_default = Schema(
        fields={"summary": Field(min_length=100)},
    )
    parser_default = ResponseParser(schema_default)
    result = parser_default.parse("[SUMMARY] short [/SUMMARY]")
    assert result.ok is True  # too_short is non-critical by default
    assert any(e.code == "too_short" for e in result.errors)

    # Override — promote too_short to critical.
    schema_strict = Schema(
        fields={"summary": Field(min_length=100)},
        critical_codes=frozenset({
            "missing_required", "invalid_choice", "unfilled_template",
            "no_content", "too_short",
        }),
    )
    parser_strict = ResponseParser(schema_strict)
    result = parser_strict.parse("[SUMMARY] short [/SUMMARY]")
    assert result.ok is False


# ── Schema from file ────────────────────────────────────────────────────────

def test_schema_from_json_file(tmp_path: Path) -> None:
    schema_def = {
        "fields": {
            "sentiment": {"choices": ["positive", "negative", "neutral"]},
            "summary":   {"min_length": 10},
        },
        "formats": ["tagged", "json"],
    }
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema_def))

    schema = Schema.from_file(schema_path)
    assert "sentiment" in schema.fields
    assert schema.fields["sentiment"].type == FieldType.CHOICE
    assert schema.fields["summary"].min_length == 10


def test_schema_from_yaml_file(tmp_path: Path) -> None:
    pytest.importorskip("yaml")

    yaml_content = """
fields:
  sentiment:
    choices: [positive, negative, neutral]
  summary:
    min_length: 10
  priority:
    type: integer
    required: false
    default: 0

formats: [tagged, json]
key_aliases:
  category: sentiment
"""
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(yaml_content)

    schema = Schema.from_file(schema_path)
    assert "sentiment" in schema.fields
    assert schema.fields["priority"].type == FieldType.INTEGER
    assert schema.fields["priority"].has_default
    assert schema.key_aliases == {"category": "sentiment"}


# ── Telemetry ───────────────────────────────────────────────────────────────

def test_telemetry_writes_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "parses.jsonl"
    parser = ResponseParser(SENTIMENT_SCHEMA, log_path=log_path, model="test-model")

    parser.parse("""
{
    "sentiment": "positive",
    "confidence": "high",
    "summary": "All systems performing within expected parameters across the deployment."
}
""")

    events = read_events(log_path)
    assert len(events) == 1
    assert events[0]["model"] == "test-model"
    assert events[0]["valid"] is True


def test_log_corrections_only_skips_clean_parses(tmp_path: Path) -> None:
    # Use uppercase choices so the test's "clean" response truly needs no
    # corrections — including no case normalization.
    schema = Schema(fields={
        "sentiment":  Field(choices=["POSITIVE", "NEGATIVE", "NEUTRAL"]),
        "confidence": Field(choices=["HIGH", "MEDIUM", "LOW"]),
        "summary":    Field(min_length=20),
    })

    log_path = tmp_path / "parses.jsonl"
    parser = ResponseParser(
        schema,
        log_path=log_path,
        model="test-model",
        log_corrections_only=True,
    )

    # Clean parse — should NOT be logged.
    parser.parse("""
[SENTIMENT] POSITIVE [/SENTIMENT]
[CONFIDENCE] HIGH [/CONFIDENCE]
[SUMMARY]
A perfectly formed response that needed no corrections during parsing.
[/SUMMARY]
""")

    # Corrected parse — should be logged.
    parser.parse("""
```
[SENTIMENT] negative [/SENTIMENT]
[CONFIDENCE] medium [/CONFIDENCE]
[SUMMARY]
A response wrapped in code fences which the parser had to strip first.
[/SUMMARY]
```
""")

    events = read_events(log_path)
    assert len(events) == 1
    assert "stripped_code_fences" in events[0]["corrections"]


def test_model_profile_summary(tmp_path: Path) -> None:
    log_path = tmp_path / "parses.jsonl"
    parser = ResponseParser(SENTIMENT_SCHEMA, log_path=log_path, model="model-a")

    for _ in range(3):
        parser.parse("""
[SENTIMENT] positive [/SENTIMENT]
[CONFIDENCE] high [/CONFIDENCE]
[SUMMARY]
A response that consistently parses cleanly without any structural issues.
[/SUMMARY]
""")

    profile = model_profile(log_path, "model-a")
    assert profile["events"] == 3
    assert profile["valid_pct"] == 100.0


def test_correction_summary_aggregates(tmp_path: Path) -> None:
    log_path = tmp_path / "parses.jsonl"
    parser = ResponseParser(SENTIMENT_SCHEMA, log_path=log_path, model="model-a")

    for _ in range(2):
        parser.parse("""
```
[SENTIMENT] positive [/SENTIMENT]
[CONFIDENCE] high [/CONFIDENCE]
[SUMMARY]
A response wrapped in fences so the stripping correction is invoked.
[/SUMMARY]
```
""")

    summary = correction_summary(log_path)
    assert summary.get("stripped_code_fences", 0) >= 2

def test_choice_default_is_normalized() -> None:
    """Defaults for CHOICE fields should be normalized to canonical form."""
    schema = Schema(fields={
        "topic":    Field(choices=["bug", "feature"]),
        "priority": Field(choices=["high", "medium", "low"], required=False, default="medium"),
    })
    parser = ResponseParser(schema)
    result = parser.parse("[TOPIC] bug [/TOPIC]")
    assert result.ok
    # Default "medium" is normalized to canonical form "MEDIUM",
    # matching what would happen if the value had been parsed.
    assert result.data["priority"] == "MEDIUM"

    """
Tests added in v0.1.1 — append these to the bottom of tests/test_parser.py.

Each test corresponds to a specific fix in v0.1.1.
"""

# ── v0.1.1: Nested-dict probability extraction ──────────────────────────────


def test_nested_probability_dict_top_level() -> None:
    """A probability field with a nested dict value at the JSON top level."""
    schema = Schema(fields={
        "verdict":    Field(choices=["yes", "no"]),
        "summary":    Field(min_length=10),
        "confidence": Field(type=FieldType.PROBABILITY, required=False),
    })
    parser = ResponseParser(schema)
    result = parser.parse("""
{
  "verdict": "yes",
  "summary": "A reasonably long summary text here.",
  "confidence": {"high": 70, "medium": 20, "low": 10}
}
""")
    assert result.ok
    assert result.data["confidence"] == {"high": 70, "medium": 20, "low": 10}


def test_nested_probability_dict_deeply_nested() -> None:
    """A probability field nested several levels deep in JSON."""
    schema = Schema(fields={
        "verdict":    Field(choices=["yes", "no"]),
        "summary":    Field(min_length=10),
        "confidence": Field(type=FieldType.PROBABILITY, required=False),
    })
    parser = ResponseParser(schema)
    result = parser.parse("""
{
  "verdict": "yes",
  "summary": "A reasonably long summary text here.",
  "analysis": {
    "breakdown": {
      "confidence": {"high": 60, "medium": 30, "low": 10}
    }
  }
}
""")
    assert result.ok
    assert result.data["confidence"] == {"high": 60, "medium": 30, "low": 10}


def test_probability_subkey_does_not_leak_to_other_fields() -> None:
    """Sub-keys of a probability dict shouldn't be routed to other schema fields."""
    schema = Schema(fields={
        # 'flagged' is both a top-level schema field AND a sub-key of the
        # nested probability dict. The top-level value should win.
        "flagged":    Field(choices=["yes", "no"]),
        "summary":    Field(min_length=10),
        "confidence": Field(type=FieldType.PROBABILITY, required=False),
    })
    parser = ResponseParser(schema)
    result = parser.parse("""
{
  "flagged": "no",
  "summary": "A reasonably long summary text here.",
  "confidence": {"flagged": 30, "borderline": 60, "clean": 10}
}
""")
    assert result.ok
    assert result.data["flagged"] == "NO"
    assert result.data["confidence"] == {"flagged": 30, "borderline": 60, "clean": 10}


# ── v0.1.1: YAML auto-boolean coercion ──────────────────────────────────────


def test_yaml_bare_yes_no_in_choices(tmp_path: Path) -> None:
    """YAML schemas with bare yes/no in choices should not crash."""
    pytest.importorskip("yaml")

    yaml_content = """
fields:
  blocking:
    choices: [yes, no]
    required: false
    default: no
"""
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(yaml_content, encoding="utf-8")

    schema = Schema.from_file(schema_path)
    # Choices are normalized to uppercase by Field.__post_init__.
    assert schema.fields["blocking"].choices == ["YES", "NO"]
    # Default was the bool False from YAML, coerced to the string "no".
    assert schema.fields["blocking"].default == "no"


def test_yaml_bare_booleans_in_choices(tmp_path: Path) -> None:
    """true/false also auto-convert in YAML and should be handled."""
    pytest.importorskip("yaml")

    yaml_content = """
fields:
  active:
    choices: [true, false]
    default: true
"""
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(yaml_content, encoding="utf-8")

    schema = Schema.from_file(schema_path)
    # Bool True/False coerce to "yes"/"no" rather than "True"/"False".
    assert schema.fields["active"].choices == ["YES", "NO"]
    assert schema.fields["active"].default == "yes"


# ── v0.1.1: Clearer error for non-UTF-8 schema files ────────────────────────


def test_schema_from_file_clear_error_on_non_utf8(tmp_path: Path) -> None:
    """Non-UTF-8 schema files produce a clear, actionable error."""
    schema_path = tmp_path / "schema.yaml"
    # 0x97 is the cp1252 encoding of the em dash; invalid UTF-8.
    schema_path.write_bytes(
        b"fields:\n  topic:\n    choices: [a, b]\n# em dash \x97 here\n"
    )

    with pytest.raises(UnicodeDecodeError) as exc_info:
        Schema.from_file(schema_path)

    # The clearer message names the file path and instructs the user.
    msg = exc_info.value.reason
    assert str(schema_path) in msg
    assert "UTF-8" in msg
    assert "Re-save" in msg


# ── v0.1.1: Scalar probability values are rejected ──────────────────────────


def test_scalar_probability_value_rejected() -> None:
    """A bare number for a probability field is no longer extracted."""
    schema = Schema(fields={
        "verdict":    Field(choices=["yes", "no"]),
        "summary":    Field(min_length=10),
        "confidence": Field(type=FieldType.PROBABILITY, required=False),
    })
    parser = ResponseParser(schema)
    result = parser.parse("""
{
  "verdict": "yes",
  "summary": "A reasonably long summary text here.",
  "confidence": 50
}
""")
    # The optional probability field is simply absent — no invented buckets.
    assert "confidence" not in result.data
    # The verdict and summary parsed cleanly.
    assert result.data["verdict"] == "YES"
