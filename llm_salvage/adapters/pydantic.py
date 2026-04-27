"""
Pydantic adapter — bridge llm-salvage Schema and Pydantic models.

This module is optional. To use it::

    pip install 'llm-salvage[pydantic]'

It provides two directions:

  - ``schema_from_pydantic(MyModel)`` builds a Schema from a Pydantic model
    by inspecting field types, constraints, and ``Literal`` annotations.

  - ``to_pydantic(result, MyModel)`` converts a successful ParseResult
    into an instance of the target Pydantic model.

The adapter handles the common cases — strings with min/max length,
``Literal[...]`` choices, integers, floats. More complex Pydantic
features (custom validators, computed fields, generics) aren't translated;
for those, use the Schema directly and validate post-extraction.
"""
from __future__ import annotations

from typing import Any, get_args, get_origin

try:
    from pydantic import BaseModel
    from pydantic.fields import FieldInfo
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The Pydantic adapter requires Pydantic. "
        "Install with: pip install 'llm-salvage[pydantic]'"
    ) from exc

from ..parser import ParseResult
from ..schema import Field, FieldType, Schema


def schema_from_pydantic(model: type[BaseModel]) -> Schema:
    """
    Build a Schema from a Pydantic model.

    Supported translations:
      - ``str`` → ``FieldType.STRING``
      - ``Literal[...]`` of strings → ``FieldType.CHOICE``
      - ``int`` → ``FieldType.INTEGER``
      - ``float`` → ``FieldType.FLOAT``
      - ``Optional[...]`` or fields with defaults → ``required=False``
      - ``Field(min_length=N, max_length=N)`` constraints are preserved

    Unsupported types fall back to ``FieldType.STRING``.
    """
    fields: dict[str, Field] = {}

    for name, info in model.model_fields.items():
        fields[name] = _field_from_pydantic_info(info)

    return Schema(fields=fields)


def to_pydantic(
    result: ParseResult,
    model:  type[BaseModel],
) -> BaseModel:
    """
    Convert a ParseResult into an instance of a Pydantic model.

    Raises Pydantic's ``ValidationError`` if the result data doesn't satisfy
    the Pydantic model's constraints. For graceful failure handling, check
    ``result.ok`` before calling this.
    """
    return model(**result.data)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _field_from_pydantic_info(info: FieldInfo) -> Field:
    """Translate a Pydantic FieldInfo into an llm-salvage Field."""
    annotation = info.annotation
    required = info.is_required()

    # Unwrap Optional[X] → X, marking the field as not required.
    annotation, optional_unwrap = _unwrap_optional(annotation)
    if optional_unwrap:
        required = False

    # Literal[...] of strings → CHOICE field.
    if get_origin(annotation) is type(get_origin(_LiteralProbe)):
        # get_origin returns a special internal class for Literal in some
        # Python versions; we use a probe to detect it portably below.
        pass

    if _is_literal(annotation):
        choices = [str(arg) for arg in get_args(annotation)]
        kwargs: dict[str, Any] = {"choices": choices, "required": required}
        if not required and not info.is_required():
            default = _extract_default(info)
            if default is not _NO_DEFAULT:
                kwargs["default"] = default
        return Field(**kwargs)

    # Plain type mapping.
    field_type = _python_type_to_field_type(annotation)

    # Build kwargs based on type.
    kwargs = {"type": field_type, "required": required}

    if field_type == FieldType.STRING:
        # Pydantic stores constraints in metadata.
        for meta in info.metadata or []:
            if hasattr(meta, "min_length") and meta.min_length is not None:
                kwargs["min_length"] = meta.min_length
            if hasattr(meta, "max_length") and meta.max_length is not None:
                kwargs["max_length"] = meta.max_length

    if not required:
        default = _extract_default(info)
        if default is not _NO_DEFAULT:
            kwargs["default"] = default

    return Field(**kwargs)


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Return (inner_type, was_optional) for ``Optional[X]`` or ``X | None``."""
    args = get_args(annotation)
    if not args:
        return annotation, False
    if type(None) not in args:
        return annotation, False
    non_none = [a for a in args if a is not type(None)]
    if len(non_none) == 1:
        return non_none[0], True
    return annotation, False


def _is_literal(annotation: Any) -> bool:
    """Check if an annotation is a typing.Literal[...]."""
    from typing import Literal
    return get_origin(annotation) is Literal


# Probe used for portable Literal detection (kept for future-proofing).
_LiteralProbe = None


def _python_type_to_field_type(annotation: Any) -> FieldType:
    """Map a Python type to a FieldType. Falls back to STRING."""
    # Strip Annotated[X, ...] wrappers.
    origin = get_origin(annotation)
    if origin is not None and hasattr(origin, "__name__") and origin.__name__ == "Annotated":
        annotation = get_args(annotation)[0]

    if annotation is str:
        return FieldType.STRING
    if annotation is int:
        return FieldType.INTEGER
    if annotation is float:
        return FieldType.FLOAT
    if annotation is dict:
        return FieldType.PROBABILITY  # closest match for dict-shaped fields
    return FieldType.STRING


# Sentinel for "no default supplied" — distinct from None, which is itself
# a valid default value.
_NO_DEFAULT = object()


def _extract_default(info: FieldInfo) -> Any:
    """Get the default value from a Pydantic FieldInfo, or _NO_DEFAULT."""
    # Pydantic uses PydanticUndefined to mean "no default."
    from pydantic_core import PydanticUndefined

    if info.default is not PydanticUndefined:
        return info.default
    if info.default_factory is not None:
        try:
            return info.default_factory()
        except Exception:  # noqa: BLE001
            return _NO_DEFAULT
    return _NO_DEFAULT
