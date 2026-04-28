"""
llm-salvage — salvage structured data from LLM responses that didn't follow instructions.

Handles tagged (``[TAG]...[/TAG]``), JSON, hybrid, and assignment formats.
Applies deterministic corrections before validation. Logs correction
telemetry to JSONL on request.

Basic usage::

    from llm_salvage import ResponseParser, Schema, Field

    schema = Schema(fields={
        "sentiment":  Field(choices=["positive", "negative", "neutral"]),
        "confidence": Field(choices=["high", "medium", "low"]),
        "summary":    Field(min_length=20),
    })

    result = ResponseParser(schema).parse(response)

    if result.ok:
        print(result.data["sentiment"])
    else:
        print(result.errors)
"""

from .parser import ParseResult, ResponseParser
from .schema import Field, FieldType, Formats, Schema
from .telemetry import correction_summary, model_profile, read_events
from .validator import ValidationError

__version__ = "0.1.2"

__all__ = [
    "ResponseParser",
    "ParseResult",
    "Schema",
    "Field",
    "FieldType",
    "Formats",
    "ValidationError",
    "correction_summary",
    "model_profile",
    "read_events",
    "__version__",
]
