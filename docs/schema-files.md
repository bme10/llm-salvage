# Schema files

Schemas can be defined in YAML, JSON, or TOML files and loaded at
runtime via `Schema.from_file()`. This is useful when:

- The same schema is shared across multiple consumers (Python services,
  JavaScript clients reading the same definitions, documentation
  generators).
- Schemas are managed as configuration rather than code.
- You want non-developers to be able to read or edit the schema.

## File format detection

`Schema.from_file()` picks the parser by extension:

- `.yaml`, `.yml` — YAML (requires `pip install 'llm-salvage[yaml]'`)
- `.json` — JSON (no dependencies, uses the standard library)
- `.toml` — TOML (no dependencies on Python 3.11+, requires `tomli`
  on 3.10)

Anything else raises `ValueError`.

## Top-level structure

A schema file has at most six top-level keys:

```yaml
fields:          # required — dict of field_name -> field_def
formats:         # optional — list of formats to try, default [tagged, json]
key_aliases:     # optional — dict of JSON key -> canonical field name
tag_aliases:     # optional — dict of typo'd tag -> canonical tag
wrapper_tags:    # optional — list of tag names that contain other tags
critical_codes:  # optional — list of error codes that block ParseResult.ok
```

Only `fields` is required. Everything else has reasonable defaults.

## Field definitions

Each field can have these arguments:

| Argument     | Type    | Notes                                                                         |
|--------------|---------|-------------------------------------------------------------------------------|
| `type`       | string  | One of `string`, `choice`, `integer`, `float`, `probability`, `week_range`. Inferred when possible. |
| `required`   | boolean | Default `true`. Set to `false` to make absence non-fatal.                     |
| `choices`    | list    | List of allowed values for choice fields. Comparison is case-insensitive.     |
| `min_length` | integer | For string fields — minimum character count.                                  |
| `max_length` | integer | For string fields — maximum character count. Values exceeding this are truncated. |
| `default`    | any     | For optional fields — value used when the field is missing from the response. |

Type is inferred from other arguments:

- `choices: [...]` → `choice` (you don't need to specify `type`)
- `min_length: N` or `max_length: N` → `string`
- Otherwise → `string`

Specify `type` explicitly when inference would be wrong, e.g. for
integer or float fields with no other distinguishing arguments.

## Examples

### Minimal schema (JSON)

```json
{
  "fields": {
    "verdict": {
      "choices": ["yes", "no", "maybe"]
    },
    "summary": {
      "min_length": 20
    }
  }
}
```

### Full-featured schema (YAML)

```yaml
fields:
  verdict:
    choices: [bullish, bearish, neutral]

  confidence:
    choices: [high, medium, low]

  summary:
    min_length: 50
    max_length: 500

  priority:
    type: integer
    required: false
    default: 0

  needs_review:
    choices: ["yes", "no"]   # see "YAML pitfall" below
    required: false
    default: "no"

formats: [tagged, json]

key_aliases:
  directional_bias: verdict
  rationale: summary

tag_aliases:
  VERDCT: VERDICT
  SUMARY: SUMMARY

wrapper_tags: [analysis, output]

critical_codes:
  - missing_required
  - invalid_choice
  - unfilled_template
  - no_content
  - too_short
```

### TOML schema

```toml
[fields.verdict]
choices = ["bullish", "bearish", "neutral"]

[fields.summary]
min_length = 50

[fields.priority]
type = "integer"
required = false
default = 0

formats = ["tagged", "json"]

[key_aliases]
directional_bias = "verdict"

[tag_aliases]
VERDCT = "VERDICT"
```

TOML doesn't have a clean way to express schemas with deeply nested
field arguments, so the format works best for simple field definitions.
For complex schemas, YAML or JSON is more readable.

## Loading schemas in Python

```python
from llm_salvage import ResponseParser, Schema

schema = Schema.from_file("schemas/support_ticket.yaml")
parser = ResponseParser(schema)
```

`Schema.from_file()` accepts a `Path` or a `str`. It raises
`FileNotFoundError` if the path doesn't exist, `ValueError` for
unsupported extensions or malformed schema content, and
`UnicodeDecodeError` if the file isn't valid UTF-8 (see "Encoding"
below).

You can also build a schema from an already-parsed dict:

```python
import yaml
from llm_salvage import Schema

with open("schema.yaml") as f:
    data = yaml.safe_load(f)

schema = Schema.from_dict(data)
```

This is useful when the schema dict comes from somewhere other than a
file — an HTTP response, a database row, a config service.

## YAML pitfall: bare `yes` and `no`

PyYAML follows the YAML 1.1 spec, which auto-converts certain bare
words to Python booleans:

- `yes`, `no`, `true`, `false`
- `on`, `off`
- `y`, `n`

If any of these appear unquoted in a `choices` list, they get parsed
as Python `True` / `False`, and `Field` rejects them when it tries to
uppercase them as strings.

This is wrong:

```yaml
fields:
  blocking:
    choices: [yes, no]   # parsed as [True, False] — will crash
```

This is right:

```yaml
fields:
  blocking:
    choices: ["yes", "no"]   # parsed as ["yes", "no"] — works
```

The same applies to default values:

```yaml
needs_review:
  choices: ["yes", "no"]
  default: "no"   # quoted — string
```

This is a YAML language quirk, not an `llm-salvage` issue. JSON and
TOML schemas don't have this problem because they don't have
auto-boolean conversion for bare words.

## Encoding

`Schema.from_file()` reads files as UTF-8. This is the right default
for new files but can trip up files saved with the system default
encoding on Windows (cp1252) or older Linux/macOS environments.

If you hit a `UnicodeDecodeError` loading a schema, re-save the file
as UTF-8. Most editors have a "Save with encoding" option; VS Code,
Sublime, and modern Notepad all default to UTF-8 now. The error
message will tell you which byte caused the issue.

## Choice values: case-insensitive matching

Choices are compared case-insensitively but normalized to uppercase
in `result.data`:

```yaml
fields:
  verdict:
    choices: [bullish, bearish, neutral]
```

A response containing `BULLISH`, `Bullish`, `bullish`, or `bull` (via
prefix matching) all produce `result.data["verdict"] == "BULLISH"`.

The same applies to default values. A schema with `default: "yes"`
and `choices: ["yes", "no"]` produces `result.data[field] == "YES"`
when the default is applied — consistent with what would happen if
the response contained `yes` and the parser normalized it.

## Key aliases vs tag aliases

These are different things:

**`key_aliases`** maps JSON keys to canonical schema field names.
Used during JSON extraction. If your model emits
`{"directional_bias": "bullish"}` but your schema field is named
`verdict`, declare `directional_bias: verdict` in `key_aliases`.

**`tag_aliases`** maps tag-name typos to canonical tag names. Used
during structural correction *before* extraction. If your model emits
`[VERDCT] bullish [/VERDCT]` but your schema field is named `verdict`,
declare `VERDCT: VERDICT` in `tag_aliases`. The corrector rewrites
the tag before the extractor runs, so the rest of the pipeline sees
the canonical form.

You generally only need one or the other — JSON-format users need
`key_aliases`, tagged-format users need `tag_aliases`. Schemas using
both formats might want both.

## Wrapper tags

Some prompts produce nested tag structures:

```
[ANALYSIS]
[VERDICT] bullish [/VERDICT]
[CONFIDENCE] high [/CONFIDENCE]
[SUMMARY] ... [/SUMMARY]
[/ANALYSIS]
```

The outer `[ANALYSIS]` tag wraps the inner field tags but isn't itself
a schema field. Declare it as a wrapper tag:

```yaml
wrapper_tags: [analysis]
```

The extractor recurses into wrapper tag contents rather than treating
them as field values. Multiple levels of nesting work; declare each
wrapper level.

## Critical codes

By default, these error codes prevent `ParseResult.ok` from being True:

- `missing_required`
- `invalid_choice`
- `unfilled_template`
- `no_content`

Other errors (e.g. `too_short`, `probability_sum`) are considered
non-critical — the parse is reported as ok with corrections, on the
theory that the data might still be usable for some consumers.

For high-stakes domains (medical triage, content moderation,
financial decisions) you may want to treat *any* validation error as
critical. Override `critical_codes`:

```yaml
critical_codes:
  - missing_required
  - invalid_choice
  - unfilled_template
  - no_content
  - too_short
  - probability_sum
  - invalid_integer
  - invalid_float
```

`ParseResult.ok` is now `False` whenever any of those codes appear in
errors, even with corrections applied. This is the recommended setting
for any pipeline where downstream consumers can't safely ignore
ambiguity.

## Reloading schemas

`Schema.from_file()` reads the file each time it's called. There's no
caching layer. If you change the schema file at runtime and want
existing parsers to use the new version, you need to construct a new
`ResponseParser`:

```python
schema = Schema.from_file("schemas/v2.yaml")
parser = ResponseParser(schema)  # picks up the new schema
```

This is intentional — the library doesn't try to be clever about
when to reload. Callers manage that.
