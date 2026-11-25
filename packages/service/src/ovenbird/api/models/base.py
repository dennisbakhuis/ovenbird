"""Building blocks of the API v1 response models.

The models describe the dictionaries the service already builds; they never change
a body. Routes attach them with :func:`returns`, which keeps keys that a handler
leaves out absent (``exclude_unset``) and serialises in the field order declared
here, which is the order the handlers build. Numbers keep their JSON type: an
``int`` stays ``5`` and a ``float`` stays ``5.0`` (:data:`Number`). Unknown keys are
kept at runtime (``extra="allow"``) and refused by the contract tests.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema

REF_PREFIX = "#/components/schemas/"
NUMBER_SCHEMA: dict[str, Any] = {"type": "number"}
SCALAR_SCHEMA: dict[str, Any] = {
    "anyOf": [{"type": "number"}, {"type": "string"}, {"type": "boolean"}, {"type": "null"}]
}

Number = Annotated[int | float, WithJsonSchema(NUMBER_SCHEMA)]
Scalar = Annotated[bool | int | float | str | None, WithJsonSchema(SCALAR_SCHEMA)]
JsonObject = dict[str, Any]


def _closed(schema: dict[str, Any]) -> None:
    schema.pop("additionalProperties", None)


def _no_default(schema: dict[str, Any]) -> None:
    schema.pop("default", None)


def absent(alias: str | None = None) -> Any:
    """Return the default of a key that a handler sometimes leaves out (never ``null``).

    The schema lists the key as optional with its own type; the body only carries it
    when the handler set it (:func:`returns` excludes unset keys).

    Parameters
    ----------
    alias
        The key's name in the body when it is not a valid field name.
    """
    return Field(default=None, alias=alias, json_schema_extra=_no_default)


class ApiModel(BaseModel):
    """Base of every response model: keeps unknown keys, documents only the declared ones."""

    model_config = ConfigDict(extra="allow", json_schema_extra=_closed)


def returns(model: Any, *, encoder: bool = False) -> dict[str, Any]:
    """Return the route keyword arguments that attach ``model`` without changing a byte.

    Parameters
    ----------
    model
        Response model (or a union of models).
    encoder
        The route answered through ``JSONResponse`` before (``response_model=None``),
        so it keeps Python's JSON encoder instead of pydantic's.

    Returns
    -------
    dict
        ``response_model``, ``response_model_exclude_unset`` and, with ``encoder``,
        ``response_class``.
    """
    kwargs: dict[str, Any] = {"response_model": model, "response_model_exclude_unset": True}
    if encoder:
        kwargs["response_class"] = JSONResponse
    return kwargs
