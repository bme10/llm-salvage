# Known limitations

This document catalogs known limitations with their workarounds. As
of v0.1.1, the three significant v0.1.0 issues have been resolved.
This page is retained for the historical record and to document
remaining edge cases.

## Resolved in v0.1.1

The following were limitations in v0.1.0 and are fixed in v0.1.1.
If you are using v0.1.0, the workarounds below still apply; upgrade
to v0.1.1 for the fixes.

### Nested-dict probability fields in JSON (resolved)

In v0.1.0, a JSON response with a probability field as a nested
object such as
`{"confidence": {"high": 70, "medium": 20, "low": 10}}` was
extracted incorrectly because the parser flattened nested dicts
before type-aware extraction. The probability sub-keys leaked into
unrelated schema fields, and the intended probability field was
lost.

**v0.1.0 workaround:** encode probability as a string instead of a
nested dict:

```json
{ "confidence": "high=70 medium=20 low=10" }
```

**v0.1.1 fix:** probability fields are detected before flattening
at any depth of nesting, and their dict values are preserved
intact.

### YAML auto-conversion of `yes`/`no` to booleans (resolved)

In v0.1.0, a YAML schema with bare `yes` or `no` in a `choices`
list crashed during `Schema.from_file()` because PyYAML's
`safe_load` follows YAML 1.1 and auto-converts these to Python
booleans, which `Field.__post_init__` then rejected.

**v0.1.0 workaround:** quote the values explicitly:

```yaml
choices: ["yes", "no"]
```

**v0.1.1 fix:** booleans (and other non-string types) in
`choices` lists are coerced to strings during deserialization.
Bools become `"yes"` / `"no"` rather than `"True"` / `"False"`,
matching the most common reason to encounter them.

Quoting the values is still a perfectly fine practice — it makes
the YAML unambiguous to readers — and is harmless under v0.1.1.
But it's no longer required.

### Unclear error from `Schema.from_file()` on non-UTF-8 files (resolved)

In v0.1.0, loading a schema file saved with the system default
encoding (cp1252 on Windows) raised a bare `UnicodeDecodeError`
without much context.

**v0.1.0 workaround:** re-save the schema file as UTF-8 in your
editor.

**v0.1.1 fix:** `Schema.from_file()` catches `UnicodeDecodeError`
and re-raises with a message that names the file path, the
offending byte, and tells the user to re-save as UTF-8. The
underlying requirement (UTF-8 only) hasn't changed.

## Behavior changes in v0.1.1

### Bare numeric probability values are now rejected

In v0.1.0, a JSON response like `{"confidence": 50}` for a
probability-typed field was extracted as
`{"primary": 50, "remainder": 50}` — a two-bucket distribution with
invented labels.

In v0.1.1, this case returns no extracted probability and the
validator surfaces an `invalid_probability` error. Inventing data
that wasn't in the response is worse than honestly reporting it as
unparseable.

If you have prompts that legitimately produce single-number
probabilities, encode them as strings (`"50"` works through the
string-format path) or use a dict (`{"likely": 50, "unlikely": 50}`).

## Current limitations (v0.1.1)

None known at this time. If you hit a parsing case that should work
but doesn't, opening an issue with the response text and schema is
the most useful contribution — telemetry corpora from real workloads
beat invented test cases.
