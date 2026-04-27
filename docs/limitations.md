# Known limitations

This document catalogs known limitations in v0.1.0 with their
workarounds. Each is targeted for fix in v0.1.1 unless otherwise
noted.

## 1. Nested-dict probability fields in JSON

**Symptom.** When a JSON response has a probability field as a nested
object:

```json
{
  "verdict": "yes",
  "confidence": {"high": 70, "medium": 20, "low": 10}
}
```

…and the schema declares `confidence` as
`Field(type=FieldType.PROBABILITY)`, the extracted result is wrong.
The parser flattens nested JSON before scanning for fields, so
`confidence.high`, `confidence.medium`, `confidence.low` become
individual flat keys. The leaf `high` matches an unrelated schema
field (or no field), and the `confidence` field never gets
populated correctly.

**Cause.** `_flatten_json` runs before type-aware extraction. A fix
would detect probability-typed fields prior to flattening and
preserve their structure.

**Workaround.** Encode probability as a string in the JSON instead of
a nested dict:

```json
{
  "verdict": "yes",
  "confidence": "high=70 medium=20 low=10"
}
```

The parser's string-format probability extraction handles this
correctly. Same applies to `key=value` and slash-separated formats
(`70/20/10` for two- or three-way splits).

For tagged-format responses, the issue doesn't arise — tagged
content with a probability tag is parsed correctly.

## 2. PyYAML auto-conversion of `yes`/`no` to booleans

**Symptom.** A YAML schema with bare `yes` or `no` in a `choices`
list crashes during `Schema.from_file()`:

```yaml
fields:
  blocking:
    choices: [yes, no]   # Crashes: AttributeError on bool
```

**Cause.** PyYAML's `safe_load` follows YAML 1.1, which auto-converts
the bare words `yes`, `no`, `true`, `false`, `on`, `off`, `y`, `n`
to Python booleans. When these reach `Field.__post_init__`, calling
`.upper()` on a bool raises `AttributeError`.

**Workaround.** Quote the values explicitly:

```yaml
fields:
  blocking:
    choices: ["yes", "no"]
    default: "no"
```

This applies to every place these words might appear: choices, defaults,
even values inside `key_aliases` and `tag_aliases` if those are bare
yes/no for some reason.

JSON and TOML schemas don't have this issue; only YAML.

A v0.1.1 fix could coerce `choices` items to strings during
`_field_from_dict` deserialization, with a debug-level log when
coercion happens.

## 3. CHOICE field defaults not normalized in v0.1.0 alpha

**Status: Fixed.** This was an issue in early v0.1.0 development but
was fixed before release. Defaults for CHOICE fields are now
normalized to the canonical (uppercase) form, matching what would
happen if the value had been parsed.

Documented here for the historical record and so anyone reading
older patches understands what was changed.

## 4. UTF-8 strictness vs system-default-encoded files

**Symptom.** `Schema.from_file()` raises `UnicodeDecodeError` when
loading a YAML/JSON/TOML file that contains non-ASCII characters
(em dashes, smart quotes, accented letters) and was saved with the
system default encoding rather than UTF-8.

**Cause.** `Schema.from_file()` reads with `encoding="utf-8"` (the
correct default for new files in 2026), but Windows Notepad and
some legacy editors save as cp1252 by default. The mismatch is
detected at read time.

**Workaround.** Re-save the schema file as UTF-8. Most modern
editors have a "Save with encoding" or similar option:

- **VS Code**: bottom-right encoding indicator → "Reopen with
  encoding" or "Save with encoding" → UTF-8.
- **Notepad** (Windows 10+): File → Save As → Encoding dropdown →
  UTF-8.
- **Sublime Text**: File → Save with Encoding → UTF-8.
- **vim**: `:set fileencoding=utf-8` then `:w`.

Once saved as UTF-8, the file loads correctly.

A v0.1.1 fix would catch `UnicodeDecodeError` and re-raise with a
clearer message that names the file path and suggests re-encoding.

## What this list is not

This document lists *known* limitations — issues we've seen,
understood, and have plans to fix. It is not:

- A complete list of edge cases the library doesn't handle.
- A list of features the library doesn't have (see the README for
  scope).
- A bug tracker (see GitHub Issues for those).

If you hit a parsing case that should work but doesn't, opening an
issue with the response text and schema is the most useful thing you
can do. Reproducible cases from real workloads are more valuable than
synthetic test cases.
