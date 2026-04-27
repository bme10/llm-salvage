# README patch — add limitations.md to the docs list

In `README.md`, find this section near the bottom:

```markdown
## Documentation

- [`docs/comparison.md`](./docs/comparison.md) — when to reach for which library
- [`docs/schema-files.md`](./docs/schema-files.md) — YAML/JSON/TOML schema syntax
- [`docs/telemetry.md`](./docs/telemetry.md) — interpreting JSONL telemetry
- [`docs/adapters.md`](./docs/adapters.md) — Pydantic and json-repair adapters
```

Add one line after the adapters line:

```markdown
## Documentation

- [`docs/comparison.md`](./docs/comparison.md) — when to reach for which library
- [`docs/schema-files.md`](./docs/schema-files.md) — YAML/JSON/TOML schema syntax
- [`docs/telemetry.md`](./docs/telemetry.md) — interpreting JSONL telemetry
- [`docs/adapters.md`](./docs/adapters.md) — Pydantic and json-repair adapters
- [`docs/limitations.md`](./docs/limitations.md) — known v0.1.0 limitations and workarounds
```

That's it.
