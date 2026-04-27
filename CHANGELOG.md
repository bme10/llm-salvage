# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-27

### Added
- Initial release.
- `ResponseParser` orchestrating structural correction, extraction, validation,
  and telemetry.
- Tagged (`[TAG]...[/TAG]`), JSON, hybrid, and assignment format extraction.
- Schema definition via plain dataclasses (`Schema`, `Field`, `FieldType`,
  `Formats`).
- `Schema.from_file()` classmethod loading YAML, JSON, or TOML schema
  definitions.
- `Field.default` for non-required fields.
- `Schema.key_aliases` for extra JSON-key-to-canonical-field mappings.
- `Schema.tag_aliases` for tag-name typo corrections.
- `Schema.wrapper_tags` for tags that contain other tags.
- `Schema.critical_codes` overriding the default set used by
  `ParseResult.ok`.
- Optional `adapters/pydantic.py` providing `Schema.from_pydantic()` and
  `ParseResult.to_pydantic()` when Pydantic is installed.
- Optional `adapters/json_repair.py` using the `json-repair` package when
  installed for more robust JSON repair.
- JSONL telemetry with `correction_summary()` and `model_profile()` helpers.
- `log_corrections_only` flag to skip telemetry events for clean parses.

[Unreleased]: https://github.com/bme10/llm-salvage/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bme10/llm-salvage/releases/tag/v0.1.0
