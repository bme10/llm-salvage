# Comparison with other libraries

Several libraries solve adjacent problems. This document covers when to
reach for each, including `llm-salvage`. The summary at the end is the
quick-reference; the sections above explain how each library thinks
about the problem.

## Instructor

[Instructor](https://github.com/567-labs/instructor) is the dominant
library for getting structured output from LLMs. It wraps the OpenAI,
Anthropic, and other major-provider clients and uses their native
tool-calling APIs to constrain output to a Pydantic model. When the
model returns malformed output, Instructor automatically retries with
the validation error included in the prompt.

Use Instructor when:

- You're calling a model with reliable tool-calling support — GPT-4,
  Claude, Gemini, recent Mistral models.
- You're already using Pydantic for your data models.
- You want automatic retry on validation failure.
- You want a single import that handles client setup, schema
  enforcement, and validation together.

`llm-salvage` doesn't compete with Instructor. The two libraries solve
different parts of the problem. Instructor sits *in front of* the model
call — it shapes the prompt and constrains the response via the API.
`llm-salvage` sits *behind* the model call — it parses whatever text the
model produced, regardless of how it was produced.

You can use both. A common pattern: Instructor for your frontier-model
path, `llm-salvage` for your local-model fallback.

## PydanticAI

[PydanticAI](https://ai.pydantic.dev/) is a full agent framework from
the Pydantic team. It includes structured output handling, tool calling,
multi-step workflows, dependency injection, and observability hooks.

Use PydanticAI when:

- You're building agents, not one-shot extractions.
- You want a framework, not a library.
- You're committed to the Pydantic ecosystem end-to-end.

`llm-salvage` is intentionally smaller. It does one thing — parse text
into structured data — and doesn't try to manage agents, tools, or
workflows.

## json-repair

[json-repair](https://github.com/mangiucugna/json_repair) is a small
focused library that fixes malformed JSON. Trailing commas, missing
quotes, single quotes instead of double, truncated objects — it handles
hundreds of common malformations and returns valid JSON.

Use json-repair when:

- Your input is JSON, possibly malformed.
- You don't need a schema, just valid JSON to parse.
- You don't need format detection, validation, or telemetry.

`llm-salvage` integrates `json-repair` automatically when it's installed
(via `pip install 'llm-salvage[repair]'`). For users who only need JSON
repair, `json-repair` alone is simpler and lighter.

## LangChain output parsers

LangChain has a family of output parser classes — `PydanticOutputParser`,
`StructuredOutputParser`, `OutputFixingParser`, and others. They're
deeply integrated with the rest of LangChain.

Use LangChain output parsers when:

- You're already using LangChain for the rest of your pipeline.
- You want the parser to integrate with LangChain's chains, agents,
  and callbacks.

`llm-salvage` is framework-independent. It has no awareness of
LangChain, doesn't import it, doesn't compose with it natively. If
you're building outside LangChain (which most non-tutorial production
systems are), this is an advantage. If you're inside LangChain, the
native parsers are a more natural fit.

## llm-salvage

The library this document ships with. It's designed for a specific
situation: you're calling a model that doesn't reliably follow
tool-calling APIs, the response is text, and you need to parse it
into structured data — handling whatever quirks the model introduces.

Use `llm-salvage` when:

- You're calling local models (Ollama, llama.cpp, MLX) where
  tool-calling is inconsistent or unavailable.
- Your model output uses tagged formats (`[VERDICT] BULLISH [/VERDICT]`),
  not just JSON.
- You want post-hoc parsing — the library never makes network calls,
  never retries, never knows what model produced the text.
- You want to track which corrections each model in your fleet
  consistently needs (the telemetry feature).
- You want zero required dependencies in the core, with optional
  adapters for Pydantic and `json-repair` when you need them.

## Quick reference

| Situation                                                       | Reach for         |
|-----------------------------------------------------------------|-------------------|
| Frontier model with tool-calling, Pydantic models               | Instructor        |
| Building agents, full framework                                 | PydanticAI        |
| Pure JSON repair, no schema needed                              | json-repair       |
| Inside a LangChain pipeline                                     | LangChain parsers |
| Local models, mixed formats, post-hoc parsing                   | llm-salvage       |
| Local models with structured output (this is the canonical fit) | llm-salvage       |

## Composing libraries

These libraries are not mutually exclusive. Common compositions:

**Instructor for cloud, llm-salvage for local.** Your code paths for
GPT-4 and Claude use Instructor; your fallback path for a local Llama
model uses `llm-salvage`. Both produce the same Pydantic objects via
the `llm-salvage` Pydantic adapter.

**llm-salvage with json-repair installed.** Out of the box,
`llm-salvage` has a small built-in JSON repair routine. With
`pip install 'llm-salvage[repair]'`, it uses the more robust
`json-repair` package internally for JSON-format extraction. No code
changes needed.

**llm-salvage telemetry feeding prompt iteration.** As `llm-salvage`
parses real responses, it logs which corrections each model needed.
After a few thousand parses, the telemetry shows which prompt
adjustments would have the biggest impact across your fleet. This
isn't something the other libraries try to do.
