"""The API v1 contract as OpenAPI, written to ``docs/openapi.json`` at build time.

The running service serves no schema (``openapi_url=None``); ``make api-schema``
runs this module to regenerate the file from the response models, and a test fails
when the committed file differs. The UI's ``npm run api-types`` turns it into
TypeScript. The schema is stable: keys are sorted, ``info.version`` is the API
version (not the release), the generated ``title`` of every schema is dropped (the
docstrings stay as descriptions) and the WebSocket messages of
:mod:`ovenbird.api.models.ws` are added as components.

Usage::

    python -m ovenbird.api.openapi [--check] [PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Final, cast

from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute, iter_route_contexts
from pydantic import TypeAdapter

from ovenbird.api.app import API_PREFIX, create_app
from ovenbird.api.models.base import REF_PREFIX
from ovenbird.api.models.supervision import KEPT_MODELS
from ovenbird.api.models.ws import ServerMessage
from ovenbird.config import load_settings
from ovenbird.configstore import ConfigManager
from ovenbird.payloads import API_VERSION
from ovenbird.pump.settings import PumpSettings
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.testing import FakeClock
from ovenbird.weather import OpenMeteoProvider, WeatherService

DEFAULT_PATH: Final = Path(__file__).resolve().parents[5] / "docs" / "openapi.json"
REF_TEMPLATE: Final = REF_PREFIX + "{model}"
NUMPY_SECTION: Final = re.compile(
    r"\n*^(?:Parameters|Other Parameters|Returns|Yields|Raises|Warns|See Also|Notes|Examples)"
    r"\n-{3,}\n",
    re.MULTILINE,
)
EMPTY_SIGNALS: Final[dict[str, Any]] = {
    "ha": {"enabled": False, "link_up": False},
    "room": [],
    "liveness": [],
    "crosscheck": [],
}


async def _no_sleep(_: float) -> None:
    """Skip a wait, so the contract app never delays."""


def _no_network(_: str) -> bytes:
    """Refuse any forecast fetch."""
    raise OSError("the contract app never fetches a forecast")


def contract_app(data_dir: Path) -> FastAPI:
    """Return the application with every optional router, on a scratch data directory."""
    settings = load_settings(data_dir=data_dir, ui_dir=data_dir / "ui", http_port=0)
    clock = FakeClock()
    manager = ConfigManager.open(settings, clock, locked={})
    runtime = Runtime(clock=clock)
    loop, _ = build_control(manager.settings, runtime, None, sleep=_no_sleep, hold=manager.hold)
    pumps = PumpSettings(runtime, loop.guard, loop.adapter, manager, manager.settings.history_path)
    weather = WeatherService(
        manager.settings,
        clock,
        OpenMeteoProvider(_no_network),
        history_path=manager.settings.history_path,
    )
    return create_app(
        runtime,
        manager.settings,
        control=loop,
        config=manager,
        pumps=pumps,
        weather=weather,
        signals=lambda: EMPTY_SIGNALS,
    )


def routes(app: FastAPI) -> list[tuple[str, str, Any]]:
    """Return ``(method, path, response model)`` of every API route; ``WS`` for the WebSocket."""
    found: list[tuple[str, str, Any]] = []
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        path = context.path or ""
        if not path.startswith(API_PREFIX):
            continue
        if isinstance(route, APIRoute):
            found += [
                (method, path, route.response_model) for method in sorted(route.methods or ())
            ]
        elif isinstance(route, APIWebSocketRoute):
            found.append(("WS", path, None))
    return found


def untitled(node: Any, *, names: bool = False) -> None:
    """Drop pydantic's generated ``title`` of every schema below ``node`` (in place).

    ``names`` marks a ``properties`` object, whose keys are field names, not keywords.
    """
    if isinstance(node, dict):
        if not names and isinstance(node.get("title"), str):
            del node["title"]
        for key, value in node.items():
            untitled(value, names=not names and key == "properties")
    elif isinstance(node, list):
        for item in node:
            untitled(item)


def trim_descriptions(paths: dict[str, Any]) -> None:
    """Cut every operation description at its first numpy section (in place).

    FastAPI copies the whole route docstring into the description; the ``Parameters``
    and ``Returns`` sections are for readers of the code, not of the contract.
    """
    for operations in paths.values():
        for operation in operations.values():
            description = operation.get("description") if isinstance(operation, dict) else None
            if not isinstance(description, str):
                continue
            trimmed = NUMPY_SECTION.split(description, maxsplit=1)[0].rstrip()
            if trimmed:
                operation["description"] = trimmed
            else:
                del operation["description"]


def component(schemas: dict[str, Any], name: str, kind: Any) -> None:
    """Add ``kind`` (and the models it uses) to ``schemas`` as the component ``name``.

    The WebSocket messages and the objects passed through from the facts store
    (:data:`~ovenbird.api.models.supervision.KEPT_MODELS`) are not, or not always,
    reached from a route's response model.

    Raises
    ------
    ValueError
        When a component of that name exists with another schema.
    """
    schema = TypeAdapter[Any](cast(Any, kind)).json_schema(
        mode="serialization", ref_template=REF_TEMPLATE
    )
    for sub, body in [*schema.pop("$defs", {}).items(), (name, schema)]:
        if schemas.setdefault(sub, body) != body:
            raise ValueError(f"the schema of {sub} differs from the one the routes use")


def contract() -> dict[str, Any]:
    """Return the OpenAPI document of API v1, WebSocket messages included."""
    with tempfile.TemporaryDirectory(prefix="ovenbird-openapi-") as scratch:
        document = contract_app(Path(scratch)).openapi()
    document["info"]["version"] = str(API_VERSION)
    schemas = document.setdefault("components", {}).setdefault("schemas", {})
    component(schemas, "ServerMessage", ServerMessage)
    for model in KEPT_MODELS:
        component(schemas, model.__name__, model)
    trim_descriptions(document["paths"])
    untitled(document["paths"])
    untitled(schemas)
    return document


def render(document: dict[str, Any]) -> str:
    """Return the stable text form: sorted keys, two-space indent, final newline."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the schema, or with ``--check`` report whether the file is current."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--check", action="store_true", help="fail when the file differs")
    args = parser.parse_args(argv)
    text = render(contract())
    path: Path = args.path
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != text:
            print(f"{path} is stale; run make api-schema", file=sys.stderr)
            return 1
        return 0
    path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
