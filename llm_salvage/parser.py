"""
ResponseParser — main entry point.

Orchestrates: structural correction → tag-closing → extraction →
validation → telemetry. Returns a ParseResult the caller inspects;
never raises on bad model output.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .corrector import apply_structural_corrections, close_unclosed_tags
from .extractor import extract
from .schema import Schema
from .telemetry import log_parse_event
from .validator import ValidationError, validate

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """
    Result of a single parse attempt.

    Attributes:
        ok:          True if data is valid and usable. False when critical
                     errors remain that the schema can't tolerate.
        valid:       True if validation passed with zero errors.
        corrected:   True if any corrections were applied during parsing.
        data:        Extracted and normalized field values. Keyed by
                     schema field name.
        corrections: Codes for every correction applied during parsing.
        errors:      Validation errors. Empty when ``valid`` is True.
        raw:         The original response text, unmodified.
    """

    ok:          bool
    valid:       bool
    corrected:   bool
    data:        dict[str, Any]
    corrections: list[str]
    errors:      list[ValidationError]
    raw:         str

    def get(self, key: str, default: Any = None) -> Any:
        """Convenience accessor for data fields."""
        return self.data.get(key, default)

    def __repr__(self) -> str:
        if self.valid:
            status = "valid"
        elif self.corrected:
            status = "corrected"
        else:
            status = "failed"
        return (
            f"ParseResult({status}, "
            f"fields={list(self.data.keys())}, "
            f"corrections={self.corrections}, "
            f"errors={[str(e) for e in self.errors]})"
        )


class ResponseParser:
    """
    Parse structured data from LLM responses.

    Example::

        from llm_salvage import ResponseParser, Schema, Field

        schema = Schema(fields={
            "sentiment":  Field(choices=["positive", "negative", "neutral"]),
            "confidence": Field(choices=["high", "medium", "low"]),
            "summary":    Field(min_length=20),
        })

        parser = ResponseParser(schema)
        result = parser.parse(response_text)

        if result.ok:
            sentiment = result.data["sentiment"]
        else:
            for err in result.errors:
                print(err)

    Args:
        schema:               Schema defining expected fields and formats.
        log_path:             Path to a JSONL telemetry file. ``None``
                              disables file logging.
        model:                Model name recorded in telemetry events
                              (informational only — the parser does not
                              call any model).
        log_corrections_only: When True, telemetry events are only written
                              for parses that applied at least one
                              correction. Useful for high-volume usage
                              where clean parses don't need to be recorded.
    """

    def __init__(
        self,
        schema:               Schema,
        log_path:             Path | str | None = None,
        model:                str = "",
        log_corrections_only: bool = False,
    ):
        self.schema               = schema
        self.log_path             = Path(log_path) if log_path else None
        self.model                = model
        self.log_corrections_only = log_corrections_only

    def parse(
        self,
        response:  str,
        task_id:   str = "",
        ticker:    str = "",
        task_type: str = "",
    ) -> ParseResult:
        """
        Parse a model response against the schema.

        Pipeline:
            1. Structural corrections (fences, BOM, line endings, tag aliases)
            2. Auto-close unclosed tags whose names match schema fields
            3. Extract data using formats in schema-defined order
            4. Validate and normalize extracted values
            5. Log telemetry (if configured)

        Args:
            response:  Raw model output text.
            task_id:   Optional identifier recorded in telemetry.
            ticker:    Optional symbol recorded in telemetry. Retained for
                       backward compatibility; use ``task_id`` for general
                       categorization.
            task_type: Optional category recorded in telemetry.

        Returns:
            A ParseResult. Never raises on malformed input.
        """
        all_corrections: list[str] = []
        original = response

        # ── Step 1: Structural corrections ────────────────────────────────
        try:
            text, corrections = apply_structural_corrections(
                response,
                tag_aliases=self.schema.tag_aliases,
            )
            all_corrections.extend(corrections)
        except Exception as exc:
            logger.warning("Structural correction error: %s", exc)
            text = response

        # ── Step 2: Close unclosed tags (using schema field names) ────────
        known_tags = [k.upper() for k in self.schema.fields]
        try:
            text, corrections = close_unclosed_tags(text, known_tags)
            all_corrections.extend(corrections)
        except Exception as exc:
            logger.warning("Tag closing error: %s", exc)

        # ── Step 3: Extract ───────────────────────────────────────────────
        try:
            extracted, corrections = extract(text, self.schema)
            all_corrections.extend(corrections)
        except Exception as exc:
            logger.error("Extraction error: %s", exc)
            extracted = {}

        if not extracted:
            result = ParseResult(
                ok=False, valid=False, corrected=False,
                data={}, corrections=all_corrections,
                errors=[ValidationError(
                    field="*",
                    code="no_content",
                    message="No structured content could be extracted from the response",
                )],
                raw=original,
            )
            self._log(result, task_id, ticker, task_type)
            return result

        # ── Step 4: Validate ──────────────────────────────────────────────
        try:
            normalized, val_corrections, errors = validate(extracted, self.schema)
            all_corrections.extend(val_corrections)
        except Exception as exc:
            logger.error("Validation error: %s", exc)
            errors = [ValidationError(
                field="*",
                code="validation_exception",
                message=str(exc),
            )]
            normalized = extracted

        # ── Step 5: Build result ──────────────────────────────────────────
        valid     = len(errors) == 0
        corrected = len(all_corrections) > 0
        ok        = valid or self._only_non_critical_errors(errors)

        result = ParseResult(
            ok=ok, valid=valid, corrected=corrected,
            data=normalized, corrections=all_corrections,
            errors=errors, raw=original,
        )

        self._log(result, task_id, ticker, task_type)
        return result

    # ── Internal helpers ──────────────────────────────────────────────────

    def _only_non_critical_errors(self, errors: list[ValidationError]) -> bool:
        """
        True when all remaining errors are non-critical per the schema.

        Critical codes are configurable via ``Schema.critical_codes``.
        """
        critical = self.schema.critical_codes
        return all(e.code not in critical for e in errors)

    def _log(
        self,
        result:    ParseResult,
        task_id:   str,
        ticker:    str,
        task_type: str,
    ) -> None:
        """Log telemetry for this parse attempt."""
        # Skip clean parses when log_corrections_only is set.
        if self.log_corrections_only and not result.corrections and result.valid:
            return

        try:
            log_parse_event(
                log_path=self.log_path,
                model=self.model,
                corrections=result.corrections,
                errors=result.errors,
                valid=result.valid,
                task_id=task_id,
                ticker=ticker,
                task_type=task_type,
                response_len=len(result.raw),
            )
        except Exception as exc:
            logger.warning("Telemetry logging error: %s", exc)
