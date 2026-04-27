# Adapters

Adapters are optional integrations with other libraries. They activate
when the corresponding package is installed and stay invisible when
it isn't. The core `llm-salvage` package has zero required
dependencies; adapters extend it.

Two adapters ship in v0.1.0:

- **Pydantic** — bridge between `Schema` and Pydantic models.
- **json-repair** — improved JSON repair via the `json-repair` package.

## Pydantic adapter

The Pydantic adapter lets you use Pydantic models alongside
`llm-salvage`. Two directions are supported: building an `llm-salvage`
`Schema` from a Pydantic model, and converting a `ParseResult` into a
Pydantic instance.

### Installation

```bash
pip install 'llm-salvage[pydantic]'
```

### Building a schema from a Pydantic model

```python
from typing import Literal
from pydantic import BaseModel, Field as PydanticField

from llm_salvage import ResponseParser
from llm_salvage.adapters.pydantic import schema_from_pydantic, to_pydantic


class SupportTicket(BaseModel):
    topic:    Literal["billing", "technical", "general"]
    priority: Literal["urgent", "normal", "low"]
    summary:  str = PydanticField(min_length=10, max_length=500)
    needs_callback: Literal["yes", "no"] = "no"


schema = schema_from_pydantic(SupportTicket)
parser = ResponseParser(schema)

result = parser.parse(response_text)
if result.ok:
    ticket = to_pydantic(result, SupportTicket)
    # ticket is a SupportTicket instance, validated by Pydantic.
    print(ticket.topic)
```

### What gets translated

The adapter handles common Pydantic features:

- `str` fields → `FieldType.STRING`. `min_length` and `max_length`
  constraints are preserved.
- `Literal["a", "b", "c"]` → `FieldType.CHOICE` with the literal values
  as choices.
- `int` → `FieldType.INTEGER`.
- `float` → `FieldType.FLOAT`.
- `Optional[X]` or `X | None` → marks the field as `required=False`.
- Default values are preserved on optional fields.

What doesn't translate:

- Custom validators (`@field_validator`) — these run inside Pydantic
  but `llm-salvage` doesn't see them. The Pydantic validation
  happens in `to_pydantic()`, after `llm-salvage` parsing.
- Computed fields, model validators, generic types, discriminated
  unions, and other advanced Pydantic features fall back to
  `FieldType.STRING`.

For models that use unsupported features, you can build the schema
manually rather than via the adapter, then still use `to_pydantic()`
for the round-trip:

```python
from llm_salvage import Schema, Field, FieldType

schema = Schema(fields={
    "topic":    Field(choices=["billing", "technical", "general"]),
    "priority": Field(choices=["urgent", "normal", "low"]),
    "summary":  Field(min_length=10, max_length=500),
    "needs_callback": Field(
        choices=["yes", "no"], required=False, default="no",
    ),
})

result = parser.parse(response)
ticket = to_pydantic(result, SupportTicket)
```

### Pydantic v2 only

The adapter uses Pydantic v2 internals (`model_fields`, `FieldInfo`,
`PydanticUndefined`). Pydantic v1 is not supported. The
`pyproject.toml` pins `pydantic>=2.0` for the `[pydantic]` extra.

Pydantic v1 is end-of-life as of late 2024 and most active projects
have migrated. If you have a v1 codebase that can't migrate, use
`Schema` directly without the adapter.

## json-repair adapter

The `json-repair` package handles many more JSON malformations than
`llm-salvage`'s built-in repair logic. When installed, it's used
automatically — no API change, no configuration.

### Installation

```bash
pip install 'llm-salvage[repair]'
```

That's it. After installation, the parser uses `json-repair`
internally for JSON-format extraction. You don't import anything.

### What changes

Without `json-repair` installed, the built-in repair handles:

- Trailing commas before `}` or `]`.
- Single quotes instead of double quotes.
- Truncation at the last complete object/array.

That covers maybe 70% of real-world malformed JSON.

With `json-repair` installed, the parser handles:

- All of the above, plus
- Missing commas between elements.
- Missing closing braces or brackets.
- Invalid escape sequences.
- Unquoted keys.
- Mixed quoting styles within the same object.
- Markdown formatting bleeding into the JSON.
- And many other malformations the package authors have curated.

Coverage jumps to maybe 95%+ of real-world cases.

### Correction codes

When the package handles a repair, the correction code is
`repaired_via_json_repair`. When the built-in handles it, the
specific code (`removed_trailing_commas`, `replaced_single_quotes`,
`truncated_to_last_complete`) is used.

For telemetry analysis, both indicate "the JSON needed repair." The
specific code with the built-in is more diagnostic; the package code
is more reliable. There's a tradeoff between observability and
robustness — most users prefer the package once they know it's
available.

### Disabling the package

If for some reason you want to force use of the built-in repair logic
even with `json-repair` installed, the supported way is to uninstall
the package. There's no runtime flag; the integration check is purely
"can I import this?"

The unsupported way is to monkey-patch the `_try_json_repair_package`
function in `llm_salvage.corrector` to return `None`. This works but
is fragile — internal function names may change between versions.

### Defensive guards

`llm-salvage` doesn't blindly trust `json-repair`'s output. The
adapter:

1. Skips text that doesn't start with `{` or `[`. The package is
   permissive enough to turn arbitrary prose into valid-looking JSON;
   running it on tagged or assignment-format input produces
   misleading results.

2. Skips text that matches the `[TAG_NAME]` pattern. Tagged content
   starts with `[` but is not JSON.

3. Verifies the repaired output actually parses with `json.loads`
   and is non-empty.

These guards mean the adapter is safe to enable on responses of
unknown format. The parser routes mixed/uncertain content through
multiple format extractors, and the JSON path is now well-behaved
for non-JSON input.

## Future adapters

The `adapters/` namespace is intended to grow over time. Candidates
for v0.x:

- **msgspec** — high-performance schema validation with `Struct`
  classes. Translation analogous to the Pydantic adapter.
- **attrs/cattrs** — for users in the `attrs` ecosystem.
- **dataclasses-json** — bridge for stdlib dataclasses with JSON
  marshaling.

These aren't planned for any specific release. They'll show up if
there's user demand or a clear use case. Contributions welcome.
