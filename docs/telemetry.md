# Telemetry

`llm-salvage` can log every parse attempt to a JSONL file. Over time
this builds a corpus you can query to see which models in your fleet
need which corrections, which prompts produce the most parse failures,
and where prompt engineering effort would have the biggest impact.

This is the most distinctive feature of the library. Other parsers
tell you whether a single response succeeded; `llm-salvage` builds an
operational record of *what your models actually do*.

## Enabling telemetry

Telemetry is opt-in via the `log_path` argument:

```python
from llm_salvage import ResponseParser, Schema, Field

parser = ResponseParser(
    schema,
    log_path="logs/parses.jsonl",
    model="llama3.2:3b",
)
```

`log_path` accepts a `Path` or `str`. Parent directories are created
automatically if missing. The file is opened in append mode, so
multiple processes can safely log to the same file (with the usual
small risk of interleaved writes — for high-volume usage, give each
process its own file).

The `model` argument is a label recorded with each event. It's
purely informational — `llm-salvage` doesn't validate it, doesn't
call any model, and doesn't assume any particular naming convention.
Pick whatever scheme makes sense for your fleet (`llama3.2:3b`,
`prod-extraction-v2`, `experimental-finetune-2025-04`).

## Event format

Each parse writes one JSON object per line:

```json
{
  "ts": "2026-04-27T03:14:15.926+00:00",
  "model": "llama3.2:3b",
  "task_id": "ticket-1234",
  "ticker": "",
  "task_type": "support_triage",
  "response_len": 412,
  "valid": true,
  "corrections": ["stripped_code_fences", "case_normalized_URGENT"],
  "error_codes": [],
  "error_fields": []
}
```

Fields:

- `ts` — UTC timestamp in ISO 8601 format.
- `model` — the model label you provided.
- `task_id`, `ticker`, `task_type` — pass-through metadata you provide
  on each `parse()` call. All optional, default empty string.
- `response_len` — character count of the original response.
- `valid` — whether validation passed with zero errors.
- `corrections` — list of correction codes applied.
- `error_codes`, `error_fields` — codes and field names of any errors.

Note that `task_id`, `ticker`, and `task_type` are pass-through —
nothing in the library requires or interprets them. Use whatever
identifiers make sense for your data.

## Logging only corrected parses

For high-volume usage where you don't want to record every clean
parse, set `log_corrections_only=True`:

```python
parser = ResponseParser(
    schema,
    log_path="logs/parses.jsonl",
    model="llama3.2:3b",
    log_corrections_only=True,
)
```

Now only parses that applied at least one correction (or had errors)
are logged. Clean parses are silently dropped. This keeps the log
file focused on the cases that need attention.

The Python logger still receives WARNING-level messages for
corrected parses regardless of this flag. If you want full silence,
configure the `llm_salvage` logger via standard `logging`
configuration.

## Reading and analyzing telemetry

The `read_events()`, `correction_summary()`, and `model_profile()`
functions are exported from the top-level package.

### `read_events(log_path)`

Reads all events from a JSONL file. Returns a list of dicts.

```python
from llm_salvage import read_events

events = read_events("logs/parses.jsonl")
print(f"Parsed {len(events)} events")
print(f"First event: {events[0]}")
```

Malformed lines are skipped without raising. This means a
half-written final line from a crashed process won't break analysis.

### `correction_summary(log_path)`

Returns a dict of `correction_code -> count`, sorted by frequency
descending. Across all models, all parses, all time:

```python
from llm_salvage import correction_summary

summary = correction_summary("logs/parses.jsonl")
for code, count in summary.items():
    print(f"{code}: {count}")
```

Output might look like:

```
stripped_code_fences: 1247
case_normalized_BULLISH: 891
case_normalized_HIGH: 663
removed_trailing_commas: 412
fixed_tag_verdct: 89
applied_default_in_stock: 34
```

Reading this top-down: more than 1200 of your parses had code fences
that needed stripping. That's a candidate for a prompt change ("do
not wrap your output in code fences"). The 89 typos of `[VERDCT]`
suggest the model is misspelling the tag often enough to add it to
your `tag_aliases` if you haven't already.

### `model_profile(log_path, model)`

Filters telemetry to a single model and produces a richer summary:

```python
from llm_salvage import model_profile

profile = model_profile("logs/parses.jsonl", "llama3.2:3b")
```

Returns:

```python
{
    "model": "llama3.2:3b",
    "events": 5247,
    "valid_pct": 89.4,
    "corrections": {
        "stripped_code_fences": 612,
        "case_normalized_BULLISH": 401,
        ...
    },
    "top_correction": "stripped_code_fences",
}
```

`valid_pct` is the percentage of parses that succeeded with zero
errors. Anything below ~95% probably warrants prompt iteration on
that model.

`top_correction` is the most frequent correction. If it's something
trivial (case normalization), you're probably fine. If it's something
serious (`unfilled_template` would mean the model is emitting prompt
placeholders verbatim), it's a signal to investigate.

## Common workflows

### Comparing models

```python
from llm_salvage import model_profile

models = ["llama3.2:3b", "qwen2.5:7b", "gemma3:4b"]
for m in models:
    p = model_profile("logs/parses.jsonl", m)
    print(f"{m}: {p['valid_pct']}% valid ({p['events']} events)")
```

Useful for picking which model to deploy. The model with the highest
`valid_pct` on your specific schema and prompt is the most reliable
for your use case — which may not be the largest or newest model.

### Identifying prompt issues

If a particular correction code has a high count *across all models*,
that's a prompt issue, not a model issue. The fix is in the prompt
text, not the model selection.

If a correction code is high *only on one model*, that's a
model-specific quirk. Either add a schema-level workaround
(`tag_aliases`, `key_aliases`) or switch models for that path.

### Spot-checking failures

```python
import json
from pathlib import Path

failures = [
    json.loads(line)
    for line in Path("logs/parses.jsonl").read_text().splitlines()
    if line and not json.loads(line)["valid"]
]

print(f"Found {len(failures)} failed parses")
for f in failures[:10]:
    print(f"  {f['model']} / {f['task_type']}: {f['error_codes']}")
```

`read_events()` strips out the malformed-line handling for you, but
direct iteration like this gives you control over what to filter on.

## Operational considerations

### File size

Each event is roughly 200–400 bytes depending on how many corrections
were applied. A million parses produces a 200–400 MB log file. For
most workloads this is fine; for heavy production use, rotate the
log periodically and run analysis against the rotated archives.

`llm-salvage` itself doesn't do log rotation — that's the caller's
responsibility. Standard tools (`logrotate` on Linux, custom cron
jobs, or a wrapper that switches log paths daily) all work because
`llm-salvage` just opens the configured path in append mode.

### Concurrent writers

The library uses a simple `f.write()` per event. On most filesystems,
writes under the OS atomic-write threshold (typically 4 KB) are
atomic — meaning two processes writing at the same time won't
interleave their bytes within a single line. Since each event is
well under 4 KB, this works in practice.

For pathological cases (very-high-concurrency or non-POSIX filesystems),
give each process its own log file and merge later. Don't rely on
exclusive locking; the library doesn't do that.

### Privacy

The log records the *length* of each response, not the response itself.
Field names appear in `error_fields`, but field values do not. If your
responses contain sensitive data, the log is safe to retain — it
captures behavior, not content.

If you want to record content too (for debugging), wrap `parser.parse`
yourself:

```python
def parse_with_content(text, **kwargs):
    result = parser.parse(text, **kwargs)
    if not result.ok:
        log_full_response(text, result.errors)
    return result
```

Don't add content logging to the library itself; it would conflict
with the privacy default.
