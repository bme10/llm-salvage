# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## v0.1.3 — opaque fields for envelope schemas

One feature, one bug fix, both driven by real-world testing against an Agent Zero proxy logging 164+ live LLM interactions across varied agentic tasks (sentiment analysis, ticket classification, code execution, browser agent, memory recall, search synthesis).

### Added

**`Field.opaque` flag.** STRING fields can now opt out of nested-content scanning during JSON extraction:

```python
from llm_salvage import Field, FieldType, Schema

schema = Schema(fields={
    "tool_name": Field(type=FieldType.STRING, required=False),
    "tool_args": Field(type=FieldType.STRING, required=False, opaque=True),
})
```

When the parser encounters an opaque field with a nested dict or list value, it serializes the entire value to a JSON string and stops recursing into it. Sub-keys within the opaque field are not matched against other schema fields, and the validator's `unfilled_template` check is skipped (opaque content may legitimately contain `{placeholder}` tokens like Python f-strings).

The flag is supported in schema files via `opaque: true` on field definitions.

### Fixed

**Pass-1 false positive on envelope schemas.** Previously, a STRING field whose value contained tagged-format content as a string literal (e.g., a `code` sub-field with `[SENTIMENT] ... [/SENTIMENT]` examples) would have those nested tags extracted and added to `result.data` as if they were declared schema fields. With `opaque=True`, the parser correctly treats the field's content as data, not as parseable structure.

Discovered while logging Agent Zero responses where `tool_args.code` contained Python `print()` calls demonstrating output formats:

```json
{
  "tool_name": "code_execution_tool",
  "tool_args": {
    "code": "print(f'[SENTIMENT] {sentiment} [/SENTIMENT]')"
  }
}
```

Without `opaque=True`, the extractor would return `result.data["sentiment"]` populated from inside the `code` string. With `opaque=True`, only the declared fields appear in the result.

**Validator: `unfilled_template` skipped on opaque fields.** Previously, opaque content containing format-spec syntax like `f'{x}'` would falsely trigger an `unfilled_template` validation error. The check now respects the opaque flag.

### Tests

Five new tests covering the opaque field behavior:
- Opaque fields skip nested tag extraction
- Opaque fields skip unfilled_template validation
- Nested dicts in opaque fields are serialized as JSON strings
- Schema files support `opaque: true` round-trip
- Default for `opaque` is `False` (backward-compatible)

All 29 existing tests continue to pass — the opaque flag is opt-in and changes no default behavior.

### Install

```bash
pip install --upgrade llm-salvage
```

Or pin to v0.1.3:

```bash
pip install llm-salvage==0.1.3
```


## [0.1.2] - 2026-04-28

### Fixed
- Mixed-closer tag handling. Models that close only some tags (e.g. only
  the last field has `[/TAG]`) now parse correctly. `close_unclosed_tags`
  now inserts missing closers immediately before the next opening tag
  rather than appending them all at the end, allowing the primary regex
  to match each field independently.
- Fully-unclosed tag responses (where no fields have closing tags) are
  no longer disrupted by `close_unclosed_tags` — the corrector detects
  the all-unclosed pattern and defers to the extractor's fallback.

### Added
- Markdown bullet-list extraction. Responses formatted as `* **Key:** value`
  or `- **Key:** value` (common from llama3.1, gemma2, deepseek-r1 on
  freeform extraction prompts) now extract correctly via a new
  `extract_markdown` extractor. Sub-bullets are joined into a single
  string. Logs `markdown_format_used` correction code.

### Data
- Validated against 72 real responses from 12 local models (llama3.1:8b,
  qwen2.5:7b, gemma2:9b, mistral:7b, phi4:14b, deepseek-r1:8b,
  deepseek-r1:14b, qwen2.5-coder:7b, llama3.2:3b, phi3:mini,
  gemma4:e2b, gemma4:e4b). Parse success rate improved from 59/72 to
  66/72 across the test set.


## [0.1.1] - 2026-04-27

### Fixed
- Probability fields whose JSON values are nested dicts (e.g.
  `{"confidence": {"high": 70, "medium": 20, "low": 10}}`) are now
  extracted correctly at any depth of nesting. Previously the parser
  flattened nested dicts before type-aware extraction, causing
  probability sub-keys to leak into unrelated schema fields and the
  intended probability field to be lost.
- YAML schemas with bare `yes`/`no`/`true`/`false`/`on`/`off` in
  `choices` lists no longer crash. Bool values are coerced to the
  most natural string form (`yes`/`no` rather than `True`/`False`)
  during schema deserialization. JSON and TOML schemas were
  unaffected.
- `Schema.from_file()` now produces a clear, actionable error message
  when loading a non-UTF-8 file. Previously the bare
  `UnicodeDecodeError` from the standard library left the cause
  unclear; the new message names the file path, the offending byte,
  and instructs the user to re-save as UTF-8.

### Changed
- Scalar values (a bare `int` or `float`) are no longer accepted as
  probability weights. Previously a bare number like `50` was treated
  as a two-bucket distribution with invented `primary` and
  `remainder` labels — silently inventing data that wasn't in the
  response. Bare numbers are now treated as unparseable, and the
  validator's `invalid_probability` code surfaces them honestly.

## [0.1.0] - 2026-04-27

### Added
- Initial release.
- `ResponseParser` orchestrating structural correction, extraction,
  validation, and telemetry.
- Tagged (`[TAG]...[/TAG]`), JSON, hybrid, and assignment format
  extraction.
- Schema definition via plain dataclasses (`Schema`, `Field`,
  `FieldType`, `Formats`).
- `Schema.from_file()` classmethod loading YAML, JSON, or TOML schema
  definitions.
- `Field.default` for non-required fields, with normalization for
  CHOICE fields so result.data has consistent shape regardless of
  whether values were extracted or defaulted.
- `Schema.key_aliases` for extra JSON-key-to-canonical-field mappings.
- `Schema.tag_aliases` for tag-name typo corrections.
- `Schema.wrapper_tags` for tags that contain other tags.
- `Schema.critical_codes` overriding the default set used by
  `ParseResult.ok`.
- Optional `adapters/pydantic.py` providing `schema_from_pydantic()`
  and `to_pydantic()` when Pydantic is installed.
- Optional integration with the `json-repair` package when installed
  for more robust JSON repair.
- JSONL telemetry with `correction_summary()` and `model_profile()`
  helpers.
- `log_corrections_only` flag to skip telemetry events for clean
  parses.

[Unreleased]: https://github.com/bme10/llm-salvage/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/bme10/llm-salvage/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/bme10/llm-salvage/releases/tag/v0.1.0
