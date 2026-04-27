# llm-salvage

Salvage structured data from LLM responses that didn't follow instructions.

```bash
pip install llm-salvage
```

## What this is for

You ask a local model for structured output. It mostly does what you said, but:

- It wrapped the JSON in ` ```json ` fences when you said not to.
- It used `"sentiment"` instead of `"verdict"`, or `Bullish` instead of `BULLISH`.
- It misspelled a tag name - `[VERDCIT]` instead of `[VERDICT]`.
- It returned trailing commas, smart quotes, or nested objects where you wanted strings.
- It wrote a thoughtful paragraph before the structured output you asked for.

You can prompt around these problems, retry with stricter instructions, or
switch to a model with better tool-calling support. Or you can accept that
local models do this sometimes and parse what you got.

`llm-salvage` is the third option. It applies deterministic corrections,
extracts data in tagged or JSON or assignment formats, validates against a
schema, and returns a result you can inspect - with a record of every fix
that was applied along the way.

## What this is not

It does not call any LLM. It does not retry. It does not depend on Pydantic,
PyYAML, or any other library by default. It does not know what model produced
the text it's parsing. It is not a replacement for
[Instructor](https://github.com/567-labs/instructor) or
[PydanticAI](https://ai.pydantic.dev/) - if you have a frontier model with
reliable tool-calling, those libraries are simpler and more powerful. This
library is for when tool-calling isn't available or isn't reliable, and you
need to make sense of raw text output.

## Quick start

````python
from llm_salvage import ResponseParser, Schema, Field

schema = Schema(fields={
    "sentiment":  Field(choices=["positive", "negative", "neutral"]),
    "confidence": Field(choices=["high", "medium", "low"]),
    "summary":    Field(min_length=20),
})

response = '''
```json
{
  "sentiment": "Positive",
  "confidence": "HIGH",
  "summary": "The product launch exceeded expectations across all key metrics.",
}
```
'''

result = ResponseParser(schema).parse(response)

if result.ok:
    print(result.data["sentiment"])    # "POSITIVE"
    print(result.corrections)          # ['stripped_code_fences', 'removed_trailing_commas', ...]
else:
    for error in result.errors:
        print(error)
````

The parser stripped the code fences, repaired the trailing comma, normalized
`"Positive"` to match the schema's choices, and recorded each fix as a
correction code. The response text never raised an exception - the parser
returns a `ParseResult` you inspect.

## How it works

Four passes, in order:

**1. Structural corrections.** Code fence removal, BOM stripping, line ending
normalization, tag-name typo correction (when a typo map is configured),
auto-closing of unclosed tags whose names match schema fields.

**2. Extraction.** The parser detects whether the response uses tagged,
JSON, or assignment format and tries them in order. JSON keys are matched
against schema field names directly, with optional aliases for legacy or
domain-specific naming.

**3. Validation.** Field types are checked, choices are normalized
case-insensitively, probability dicts are summed, week-range strings are
parsed into structured form. Validation never modifies data destructively
- if a value can't be normalized, it's reported as an error.

**4. Telemetry (optional).** Each parse can write a JSONL event recording
which corrections were applied, what errors remained, and which model the
response came from. Over time this builds a corpus you can query to see
which models need which corrections.

## Schema definition

Schemas can be defined in code:

```python
from llm_salvage import Schema, Field, FieldType, Formats

schema = Schema(
    fields={
        "topic":     Field(choices=["billing", "technical", "general"]),
        "priority":  Field(choices=["urgent", "normal", "low"]),
        "summary":   Field(min_length=10, max_length=500),
        "needs_human_review": Field(type=FieldType.STRING, required=False, default="no"),
    },
    formats=[Formats.TAGGED, Formats.JSON],
)
```

Or loaded from a file:

```python
from llm_salvage import Schema

schema = Schema.from_file("schemas/support_ticket.yaml")
```

Where `support_ticket.yaml` looks like:

```yaml
fields:
  topic:
    choices: [billing, technical, general]
  priority:
    choices: [urgent, normal, low]
  summary:
    min_length: 10
    max_length: 500
  needs_human_review:
    type: string
    required: false
    default: "no"

formats: [tagged, json]
```

YAML, JSON, and TOML are all supported. YAML requires `pip install
'llm-salvage[yaml]'`.

## Field types

| Type          | Use for                                              |
|---------------|------------------------------------------------------|
| `STRING`      | Free-form text with optional `min_length`/`max_length` |
| `CHOICE`      | Enum of allowed values, case-insensitive             |
| `INTEGER`     | Whole numbers                                        |
| `FLOAT`       | Decimal numbers                                      |
| `PROBABILITY` | Dict of label→int that should sum to ~100            |
| `WEEK_RANGE`  | Strings like `"2-4 weeks"` parsed to `{min, max}`    |

A field's type is inferred from its arguments - `Field(choices=[...])` is a
`CHOICE` field, `Field(min_length=20)` is a `STRING` field. Specify
`type=FieldType.X` explicitly when the inference would be wrong.

## Adapters

Optional integrations that activate when their dependency is installed.

**Pydantic** - convert between `Schema` and Pydantic models:

```python
# pip install 'llm-salvage[pydantic]'
from llm_salvage.adapters.pydantic import schema_from_pydantic, to_pydantic
from pydantic import BaseModel

class Ticket(BaseModel):
    topic: str
    priority: str
    summary: str

schema = schema_from_pydantic(Ticket)
result = ResponseParser(schema).parse(response)
ticket = to_pydantic(result, Ticket)
```

**json-repair** - use the `json-repair` library for more robust JSON repair:

```python
# pip install 'llm-salvage[repair]'
# No code change needed - the parser uses json-repair automatically when installed.
```

## Telemetry

When you pass a `log_path`, the parser writes one JSONL event per parse
attempt, recording corrections applied, errors encountered, and the model
name. This is opt-in:

```python
parser = ResponseParser(
    schema,
    log_path="parses.jsonl",
    model="llama3.2:3b",
)

for response in responses:
    parser.parse(response, task_id=response.task_id)
```

After a few hundred parses, you can ask the corpus what each model needs:

```python
from llm_salvage import model_profile

profile = model_profile("parses.jsonl", "llama3.2:3b")
# {
#   "model": "llama3.2:3b",
#   "events": 847,
#   "valid_pct": 89.4,
#   "corrections": {
#     "stripped_code_fences": 612,
#     "case_normalized_BULLISH": 243,
#     ...
#   },
#   "top_correction": "stripped_code_fences"
# }
```

This is the most useful piece of the library for ongoing operations. It
turns the parser into a feedback loop: you see which corrections each model
consistently needs, which suggests which prompt changes would have the
biggest effect.

Set `log_corrections_only=True` if you only want to record events where
corrections were actually applied - useful when you're parsing high volume
and don't need a record of every clean parse.

## Comparison with other libraries

| Library                                           | Use when                                          |
|---------------------------------------------------|---------------------------------------------------|
| [Instructor](https://github.com/567-labs/instructor) | You're using a model with reliable tool-calling. |
| [PydanticAI](https://ai.pydantic.dev/)            | You're building agents and want a full framework. |
| [json-repair](https://github.com/mangiucugna/json_repair) | You only need JSON repair, no schema or tagged formats. |
| `llm-salvage` (this)                              | Local models, mixed formats, post-hoc parsing.    |

These compose. You can use Instructor for your frontier-model path and
`llm-salvage` for your local-model fallback in the same codebase.

## Examples

The [`examples/`](./examples/) directory has end-to-end examples covering
several common domains:

- [`examples/sentiment_analysis.py`](./examples/sentiment_analysis.py) - review classification
- [`examples/support_triage.py`](./examples/support_triage.py) - customer ticket routing
- [`examples/content_moderation.py`](./examples/content_moderation.py) - flag and category extraction
- [`examples/product_extraction.py`](./examples/product_extraction.py) - pulling structured product data from descriptions
- [`examples/code_review.py`](./examples/code_review.py) - extracting findings from LLM code review
- [`examples/medical_triage.py`](./examples/medical_triage.py) - symptom severity classification

## Documentation

- [`docs/comparison.md`](./docs/comparison.md) - when to reach for which library
- [`docs/schema-files.md`](./docs/schema-files.md) - YAML/JSON/TOML schema syntax
- [`docs/telemetry.md`](./docs/telemetry.md) - interpreting JSONL telemetry
- [`docs/adapters.md`](./docs/adapters.md) - Pydantic and json-repair adapters

## Status

`v0.1.0` is alpha. The API may change before `1.0`. If you find a parsing
case that should work but doesn't, opening an issue with the response text
is the most useful contribution - telemetry corpora from real workloads
beat invented test cases.

## License

MIT - see [LICENSE](./LICENSE).
