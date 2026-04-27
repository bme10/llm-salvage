# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
