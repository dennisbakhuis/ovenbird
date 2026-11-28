"""The API contract stays single-sourced: models, ``docs/openapi.json`` and ``docs/api-v1.md``.

``docs/openapi.json`` is generated from the response models (``make api-schema``) and
the UI's TypeScript types from it (``npm --prefix ui run api-types``); these tests fail
when the committed schema is stale, when a route is missing from ``docs/api-v1.md`` (or
the document names a route that does not exist), and when a literal type of a model
drifts from the enum it mirrors.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args

import pytest

from ovenbird.api.models.app import SourceName
from ovenbird.api.models.config import (
    FieldTypeName,
    HaTestErrorCode,
    OriginName,
    TierName,
    ValueSourceName,
)
from ovenbird.api.models.control import (
    AlarmEventName,
    AwayPhaseName,
    DirectionName,
    FeatureName,
    FeatureStateName,
    ModeName,
    MonitorState,
    PlanGuardName,
    SeverityName,
    StoveSourceName,
    StoveTriggerName,
)
from ovenbird.api.models.insight import (
    BasicsStatusName,
    EmitterReasonName,
    HeatLossReasonName,
    HeatNowReasonName,
    OutsideSourceName,
    PointUseName,
    RoomSourceName,
)
from ovenbird.api.models.pump import OwnerName
from ovenbird.api.models.replay import ReplayKindName, ReplayStateName
from ovenbird.api.models.supervision import (
    CaptureRefusalName,
    CheckPhaseName,
    CheckStatusName,
    ReleaseItemStatusName,
    ReleaseOutcomeName,
)
from ovenbird.api.openapi import DEFAULT_PATH, contract, contract_app, render, routes
from ovenbird.api.replay_api import KINDS
from ovenbird.config import Settings
from ovenbird.configstore import schema_payload
from ovenbird.configstore.effective import Source
from ovenbird.configstore.fields import Feature, Tier
from ovenbird.configstore.store import Origin
from ovenbird.control.alarms import AlarmEventKind, Severity
from ovenbird.control.features import FeatureState
from ovenbird.control.forecastread import Guard
from ovenbird.control.monitors import Direction, MonitorStatus
from ovenbird.control.roomtarget import AwayPhase
from ovenbird.hacheck import ERROR_CODES
from ovenbird.insight.basics import (
    EmitterReason,
    HeatLossReason,
    HeatNowReason,
    OutsideSource,
    PointUse,
    RoomSource,
    Status,
)
from ovenbird.pump.settings import CONTROLLER, OPERATOR, PUMP
from ovenbird.replay.jobs import JobState
from ovenbird.trial.checklist import CHECK_STATUSES, PHASES
from ovenbird.trial.release import CAPTURE_REFUSALS, ITEM_STATUSES, OUTCOMES
from ovenbird_core import SourceKind
from ovenbird_core.control import Mode
from ovenbird_core.control.state import StoveSource, StoveTrigger

ROOT = Path(__file__).resolve().parents[3]
API_DOC = ROOT / "docs" / "api-v1.md"
DOWNLOADS = frozenset(
    {
        "GET /api/v1/diagnostics",
        "GET /api/v1/export/series",
        "GET /api/v1/export/journal/{kind}",
        "GET /api/v1/export/archive",
        "GET /api/v1/archive/months/{month}",
        "GET /api/v1/archive/years/{year}",
        "GET /api/v1/archive/seasons/{season}",
    }
)
REF = re.compile(r'"\$ref": "#/components/schemas/([^"]+)"')
HEADING_ROUTE = re.compile(r"`(GET|POST|PUT|DELETE|WS) (api/v1/[^`?\s]*)")
PARAM = re.compile(r"\{[^}]*\}")


def normalised(method: str, path: str) -> str:
    """Return a route key with path parameters collapsed to ``{}``."""
    return f"{method} {PARAM.sub('{}', path.lstrip('/'))}"


def documented() -> set[str]:
    """Return the routes that have a heading in ``docs/api-v1.md``."""
    found: set[str] = set()
    for line in API_DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            found.update(normalised(m, p) for m, p in HEADING_ROUTE.findall(line))
    return found


def registered(tmp_path: Path) -> set[str]:
    """Return the routes registered on the contract app."""
    return {normalised(method, path) for method, path, _ in routes(contract_app(tmp_path))}


def test_the_committed_openapi_document_is_current() -> None:
    """The committed ``docs/openapi.json`` equals the freshly rendered contract."""
    assert DEFAULT_PATH == ROOT / "docs" / "openapi.json"
    assert DEFAULT_PATH.read_text(encoding="utf-8") == render(contract()), (
        "docs/openapi.json is stale: run make api-schema (then npm --prefix ui run api-types)"
    )


def test_every_reference_resolves() -> None:
    """Every ``$ref`` in the rendered schema points at a defined component."""
    document = contract()
    names = set(REF.findall(render(document)))
    assert names <= set(document["components"]["schemas"])


def test_every_route_has_a_response_model(tmp_path: Path) -> None:
    """Every route except the download endpoints and websockets declares a response model."""
    found = {
        f"{method} {path}": model
        for method, path, model in routes(contract_app(tmp_path))
        if method != "WS"
    }
    missing = {route for route, model in found.items() if model is None} - DOWNLOADS
    assert not missing, f"routes without a response model: {sorted(missing)}"
    assert set(found) >= DOWNLOADS


def test_every_route_is_documented(tmp_path: Path) -> None:
    """Every registered route has a heading in ``docs/api-v1.md``."""
    missing = registered(tmp_path) - documented()
    assert not missing, f"routes without a heading in docs/api-v1.md: {sorted(missing)}"


def test_every_documented_route_exists(tmp_path: Path) -> None:
    """Every route named in ``docs/api-v1.md`` is actually registered."""
    unknown = documented() - registered(tmp_path)
    assert not unknown, f"docs/api-v1.md names routes that do not exist: {sorted(unknown)}"


@pytest.mark.parametrize(
    ("literal", "values"),
    [
        (ModeName, [mode.value for mode in Mode]),
        (SeverityName, [severity.value for severity in Severity]),
        (MonitorState, [status.value for status in MonitorStatus]),
        (AlarmEventName, [kind.value for kind in AlarmEventKind]),
        (StoveSourceName, [source.value for source in StoveSource]),
        (StoveTriggerName, [trigger.value for trigger in StoveTrigger]),
        (DirectionName, list(get_args(Direction.__value__))),
        (SourceName, [kind.value for kind in SourceKind]),
        (ValueSourceName, [source.value for source in Source]),
        (TierName, [tier.value for tier in Tier]),
        (FeatureName, [feature.value for feature in Feature]),
        (FeatureStateName, [state.value for state in FeatureState]),
        (PlanGuardName, [guard.value for guard in Guard]),
        (AwayPhaseName, [phase.value for phase in AwayPhase]),
        (OriginName, [origin.value for origin in Origin]),
        (OwnerName, [OPERATOR, CONTROLLER, PUMP]),
        (CheckStatusName, list(CHECK_STATUSES)),
        (CheckPhaseName, list(PHASES)),
        (CaptureRefusalName, list(CAPTURE_REFUSALS)),
        (ReleaseOutcomeName, list(OUTCOMES)),
        (ReleaseItemStatusName, ["pending", *ITEM_STATUSES]),
        (HaTestErrorCode, list(ERROR_CODES)),
        (ReplayKindName, list(KINDS)),
        (ReplayStateName, [state.value for state in JobState]),
        (BasicsStatusName, list(get_args(Status.__value__))),
        (HeatLossReasonName, list(get_args(HeatLossReason.__value__))),
        (EmitterReasonName, list(get_args(EmitterReason.__value__))),
        (PointUseName, list(get_args(PointUse.__value__))),
        (RoomSourceName, list(get_args(RoomSource.__value__))),
        (OutsideSourceName, list(get_args(OutsideSource.__value__))),
        (HeatNowReasonName, list(get_args(HeatNowReason.__value__))),
    ],
)
def test_literals_mirror_their_enums(literal: Any, values: list[str]) -> None:
    """Each API literal type lists exactly the values of the enum it mirrors, in order."""
    assert list(get_args(literal.__value__)) == values


def test_every_field_type_is_named() -> None:
    """Every config field type in the schema payload is a member of the field type literal."""
    used = {entry["type"] for entry in schema_payload(Settings())["fields"].values()}
    assert used <= set(get_args(FieldTypeName.__value__))
