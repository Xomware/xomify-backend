"""
Pydantic <-> Xomify error bridging.

Handlers validate request payloads with Pydantic models but must surface a
consistent HTTP 400 (`ValidationError`) to the client instead of leaking a raw
Pydantic exception. `parse_model` performs the validation and maps the first
Pydantic error into a `ValidationError` carrying the offending field.
"""

from typing import Type, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from lambdas.common.errors import ValidationError

TModel = TypeVar("TModel", bound=BaseModel)


def parse_model(model_cls: Type[TModel], data: dict, handler: str = "unknown") -> TModel:
    """
    Validate `data` against `model_cls`, raising `ValidationError` (HTTP 400)
    on failure instead of a raw `pydantic.ValidationError`.
    """
    try:
        return model_cls.model_validate(data)
    except PydanticValidationError as err:
        first = err.errors()[0]
        loc = first.get("loc", ())
        field = ".".join(str(part) for part in loc) if loc else None
        message = f"{field}: {first.get('msg')}" if field else str(first.get("msg"))
        raise ValidationError(message=message, handler=handler, field=field)
