"""House insight: what the learner wrote in ``<data_dir>/models``, read as plain JSON.

The house model is fitted offline by the optional learner (``python -m
ovenbird_sim.learn``, with the scientific stack), which the service starts as a child
process (:mod:`ovenbird.insight.learnrun`) or which runs in its own container; the
service only reads its files, so it never imports numpy or scipy. Two directories form the
hand-off, so the learner needs nothing else of ``<data_dir>``:

* ``<data_dir>/learner`` is written *by the service* and only read by the learner:
  ``learner-config.json`` (the control and house fields of the effective
  configuration, refreshed whenever a configuration applies) and
  ``history.snapshot.db`` (a hard link to, or else a copy of, the atomically replaced
  history snapshot, refreshed every ``EXPORT_INTERVAL_S``);
* ``<data_dir>/models`` is written by the learner: ``current.json`` names the champion
  and its ``insight-<date>.json``, ``index.json`` lists every run, ``status.json``
  describes the last run (outcome, what is missing, the learner's interval).

The service treats ``models`` as untrusted: it opens each file without following a
link (``O_NOFOLLOW``), only regular files up to ``MAX_FILE_BYTES``, parses strict
JSON (no ``NaN``), keeps an allow-list of keys with bounded sizes, finite numbers and
the types it computes with, and falls back to the ``learning`` state on any error.
A model whose learner has not run for more than twice its interval is marked stale
(``learner.stale``).

The insulation score is recomputed here from the champion's UA and the current
``house_floor_area_m2`` (so a floor area set after the run counts at once); the
constants repeat :mod:`ovenbird_sim.learn.score` and a test keeps them equal. The
curve proposal becomes a configuration *draft* only on request
(:func:`proposal_changes`); it goes through validate, preview and apply like any
other change and is never applied by the service.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from ovenbird.config import SECRET_FIELDS, Settings
from ovenbird.configstore.fields import effective_value

LOGGER = logging.getLogger("ovenbird.insight")
MODELS_DIR: Final = "models"
LEARNER_DIR: Final = "learner"
HISTORY_EXPORT: Final = "history.snapshot.db"
LEARNER_DIR_MODE: Final = 0o750
MODELS_DIR_MODE: Final = 0o2770
LEARNER_FILE_MODE: Final = 0o640
EXPORT_INTERVAL_S: Final = 600.0
MAX_FILE_BYTES: Final = 4 * 1024 * 1024
MAX_DEPTH: Final = 8
MAX_ITEMS: Final = 5000
MAX_KEYS: Final = 200
MAX_TEXT: Final = 4000
MAX_KEY: Final = 100
MAX_CURVE_POINTS: Final = 12
DEFAULT_INTERVAL_H: Final = 168.0
STALE_FACTOR: Final = 2.0
INSIGHT_KEYS: Final = frozenset(
    {
        "schema",
        "model",
        "data",
        "ua",
        "time_constant_h",
        "solar_aperture_m2",
        "internal_gains_w",
        "balance_temperature_c",
        "signature",
        "credibility",
        "validation",
        "error_trend",
        "daily_error",
        "proposal",
        "events",
        "limits",
        "provenance",
    }
)
STATUS_KEYS: Final = (
    "at",
    "outcome",
    "model",
    "champion",
    "missing",
    "message",
    "error",
    "runtime_s",
    "interval_h",
)
UNREADABLE: Final = "the learner's files could not be read ({why}); waiting for its next run"
CURRENT: Final = "current.json"
INDEX: Final = "index.json"
STATUS: Final = "status.json"
LEARNER_CONFIG: Final = "learner-config.json"
LEARNER_CONFIG_FORMAT: Final = 1
LEARNER_PREFIXES: Final = ("control_", "house_")
SUGGESTION_LABEL: Final = "Suggested by the house model"
DESIGN_INDOOR_C: Final = 20.0
DESIGN_OUTSIDE_C: Final = -10.0
BANDS: Final[tuple[tuple[str, float], ...]] = (
    ("A", 30.0),
    ("B", 45.0),
    ("C", 60.0),
    ("D", 80.0),
    ("E", 100.0),
    ("F", 125.0),
    ("G", math.inf),
)
NOTE: Final = (
    "Indicative: heat loss per m2 at 20 degC inside and -10 degC outside from the "
    "apparent heat-loss coefficient (ventilation included). Not the official energielabel."
)
NOT_RUN: Final = (
    "the house model learner has not run yet; it refits weekly by default, in the service "
    "or in a separate learner container (docs/design.md, House insight)"
)

type Json = dict[str, Any]


def models_dir(settings: Settings) -> Path:
    """Return the models directory of an installation."""
    return settings.data_dir / MODELS_DIR


class LearnerFileError(ValueError):
    """A file in the models directory that the service does not serve (the message says why)."""


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


def read_untrusted(path: Path, limit: int = MAX_FILE_BYTES) -> Any:
    """Read a JSON file the learner wrote, without trusting it.

    The file is opened without following a link and must be a regular file of at
    most ``limit`` bytes holding strict JSON (no ``NaN`` or ``Infinity``).

    Parameters
    ----------
    path
        File in the models directory.
    limit
        Size cap in bytes.

    Returns
    -------
    Any
        The parsed JSON; ``None`` when the file does not exist.

    Raises
    ------
    LearnerFileError
        For a link, a non-regular file, an oversized file or invalid JSON.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LearnerFileError(f"{path.name}: cannot open ({exc.strerror or exc})") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise LearnerFileError(f"{path.name}: not a regular file")
        if info.st_size > limit:
            raise LearnerFileError(f"{path.name}: larger than {limit} bytes")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(limit + 1)
    finally:
        os.close(fd)
    if len(raw) > limit:
        raise LearnerFileError(f"{path.name}: larger than {limit} bytes")
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise LearnerFileError(f"{path.name}: invalid JSON ({exc})") from None


def read_json(path: Path) -> Any:
    """Read a learner file; ``None`` when it is missing or refused (refusals are logged)."""
    try:
        return read_untrusted(path)
    except LearnerFileError as exc:
        LOGGER.warning("ignoring a learner file: %s", exc)
        return None


def bounded(value: Any, depth: int = 0) -> Any:
    """Return ``value`` when it is plain, bounded JSON; raise ``ValueError`` otherwise.

    Objects with at most ``MAX_KEYS`` string keys of at most ``MAX_KEY`` characters,
    lists of at most ``MAX_ITEMS`` items, strings of at most ``MAX_TEXT`` characters,
    finite numbers, booleans and ``null``, nested at most ``MAX_DEPTH`` deep.
    """
    if depth > MAX_DEPTH:
        raise ValueError("nested too deep")
    if value is None or isinstance(value, bool | str | int):
        if isinstance(value, str) and len(value) > MAX_TEXT:
            raise ValueError("text too long")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("number not finite")
        return value
    if isinstance(value, list):
        if len(value) > MAX_ITEMS:
            raise ValueError("list too long")
        return [bounded(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > MAX_KEYS:
            raise ValueError("too many keys")
        if any(not isinstance(key, str) or len(key) > MAX_KEY for key in value):
            raise ValueError("bad key")
        return {key: bounded(item, depth + 1) for key, item in value.items()}
    raise ValueError(f"unexpected {type(value).__name__}")


def _number_or_none(value: Any, what: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{what} is not a number")
    return float(value)


def _pair(value: Any, what: str) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{what} is not a pair of numbers")
    return [float(_number_or_none(item, what) or 0.0) for item in value]


def _curve_points(value: Any, what: str) -> list[list[float]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not 0 < len(value) <= MAX_CURVE_POINTS:
        raise ValueError(f"{what} is not a list of curve points")
    out: list[list[float]] = []
    for point in value:
        pair = _pair(point, what)
        if pair is None:
            raise ValueError(f"{what} has an empty point")
        out.append(pair)
    return out


def _object(value: Any, what: str) -> Json:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{what} is not an object")
    return value


def checked_insight(raw: Any) -> Json:
    """Return the allow-listed, type-checked insight a learner wrote.

    Raises
    ------
    ValueError
        When the insight is not an object, exceeds the bounds or a field the
        service computes with has the wrong type.
    """
    if not isinstance(raw, dict):
        raise ValueError("insight is not an object")
    body: Json = bounded({key: raw[key] for key in INSIGHT_KEYS if key in raw})
    ua = _object(body.get("ua"), "ua")
    _number_or_none(ua.get("w_per_k"), "ua.w_per_k")
    _pair(ua.get("interval_90"), "ua.interval_90")
    cred = _object(body.get("credibility"), "credibility")
    if not isinstance(cred.get("credible", False), bool):
        raise ValueError("credibility.credible is not a boolean")
    if not isinstance(cred.get("message") or "", str):
        raise ValueError("credibility.message is not text")
    proposal = body.get("proposal")
    if proposal is not None:
        proposal = _object(proposal, "proposal")
        _curve_points(proposal.get("curve"), "proposal.curve")
        _curve_points(proposal.get("based_on_curve"), "proposal.based_on_curve")
    return body


def checked_status(raw: Any) -> Json | None:
    """Return the allow-listed essentials of ``status.json``; ``None`` when unusable."""
    if not isinstance(raw, dict):
        return None
    try:
        out: Json = bounded({key: raw[key] for key in STATUS_KEYS if key in raw})
        for key in ("at", "outcome", "model", "champion", "message", "error"):
            if out.get(key) is not None and not isinstance(out[key], str):
                raise ValueError(f"{key} is not text")
        missing = out.get("missing")
        if missing is not None and (
            not isinstance(missing, list) or not all(isinstance(m, str) for m in missing)
        ):
            raise ValueError("missing is not a list of text")
        _number_or_none(out.get("runtime_s"), "runtime_s")
        _number_or_none(out.get("interval_h"), "interval_h")
    except ValueError as exc:
        LOGGER.warning("ignoring the learner's status.json: %s", exc)
        return None
    return out


def band(w_per_m2: float) -> str:
    """Return the indicative band letter of a heat loss per m2."""
    for letter, limit in BANDS:
        if w_per_m2 < limit:
            return letter
    return BANDS[-1][0]


def score(
    ua_w_per_k: float | None,
    ua_interval: list[float] | None,
    floor_area_m2: float | None,
    *,
    credible: bool,
    message: str | None = None,
) -> Json:
    """Return the insulation score object (see ``docs/api-v1.md``, ``insight/house``).

    Parameters
    ----------
    ua_w_per_k
        The model's envelope conductance.
    ua_interval
        Its 90 % interval.
    floor_area_m2
        Heated floor area (``house_floor_area_m2``).
    credible
        Whether the learner's credibility rules pass.
    message
        What is still missing when they do not.

    Returns
    -------
    dict
        ``state`` ``ready``, ``learning`` or ``no_floor_area`` with the design
        conditions and bands, and when ready ``heat_loss_w``, ``w_per_m2``,
        ``band`` and their intervals.
    """
    delta = DESIGN_INDOOR_C - DESIGN_OUTSIDE_C
    out: Json = {
        "design_indoor_c": DESIGN_INDOOR_C,
        "design_outside_c": DESIGN_OUTSIDE_C,
        "floor_area_m2": floor_area_m2,
        "bands": [
            {"band": letter, "below_w_per_m2": None if math.isinf(limit) else limit}
            for letter, limit in BANDS
        ],
        "indicative": True,
        "note": NOTE,
    }
    if not credible or ua_w_per_k is None:
        return out | {"state": "learning", "message": message or "insufficient data"}
    if floor_area_m2 is None or not floor_area_m2 > 0:
        return out | {
            "state": "no_floor_area",
            "heat_loss_w": round(ua_w_per_k * delta),
            "message": "set the heated floor area (house_floor_area_m2) to get W/m2 and a band",
        }
    w_per_m2 = ua_w_per_k * delta / floor_area_m2
    result = out | {
        "state": "ready",
        "heat_loss_w": round(ua_w_per_k * delta),
        "w_per_m2": round(w_per_m2, 1),
        "band": band(w_per_m2),
    }
    if ua_interval is not None and len(ua_interval) == 2:
        lo, hi = (float(v) * delta / floor_area_m2 for v in ua_interval)
        result["interval_90"] = [round(lo, 1), round(hi, 1)]
        result["band_interval"] = [band(lo), band(hi)]
    return result


def _models_ok(models: Path) -> bool:
    """Whether ``models`` is a real directory (not a link)."""
    try:
        return stat.S_ISDIR(os.lstat(models).st_mode)
    except OSError:
        return False


def last_run(models: Path) -> Json | None:
    """Return the essentials of ``status.json`` (the learner's last run)."""
    if not _models_ok(models):
        return None
    return checked_status(read_json(models / STATUS))


def champion(models: Path) -> tuple[Json, Json] | None:
    """Return ``current.json`` and the champion's insight, or ``None`` without a champion.

    Raises
    ------
    LearnerFileError
        When the champion's files exist but are refused.
    """
    if not _models_ok(models):
        return None
    current = read_untrusted(models / CURRENT)
    if current is None:
        return None
    if not isinstance(current, dict):
        raise LearnerFileError("current.json is not an object")
    name = current.get("insight")
    if not isinstance(name, str) or not name or Path(name).name != name or name.startswith("."):
        raise LearnerFileError("current.json names no insight file")
    raw = read_untrusted(models / name)
    if raw is None:
        raise LearnerFileError(f"{name} is missing")
    try:
        insight = checked_insight(raw)
        meta = bounded({key: current[key] for key in ("model", "promoted_at") if key in current})
    except ValueError as exc:
        raise LearnerFileError(f"{name}: {exc}") from None
    return meta, insight


def learner_health(
    run: Json | None, now: datetime | None = None, default_interval_h: float = DEFAULT_INTERVAL_H
) -> Json:
    """Return when the learner last ran and whether that is too long ago.

    Parameters
    ----------
    run
        :func:`last_run`.
    now
        Wall time (the learner runs on the real clock); now when omitted.
    default_interval_h
        The interval when ``status.json`` names none: the configured
        ``house_learn_interval_h`` when the service runs the learner itself, else
        the weekly default. An interval an external learner wrote wins.

    Returns
    -------
    dict
        ``last_run_at``, ``age_h``, ``interval_h`` (the learner's, or the default),
        ``stale_after_h`` (twice the interval) and ``stale``.
    """
    interval = run.get("interval_h") if run is not None else None
    interval_h = (
        float(interval)
        if isinstance(interval, int | float) and not isinstance(interval, bool) and interval > 0
        else default_interval_h
    )
    at = run.get("at") if run is not None else None
    age_h: float | None = None
    if isinstance(at, str):
        try:
            when = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            when = None
        if when is not None:
            when = when if when.tzinfo is not None else when.replace(tzinfo=UTC)
            age_h = round(((now or datetime.now(UTC)) - when).total_seconds() / 3600.0, 1)
    limit = STALE_FACTOR * interval_h
    return {
        "last_run_at": at if isinstance(at, str) else None,
        "age_h": age_h,
        "interval_h": interval_h,
        "stale_after_h": limit,
        "stale": age_h is not None and age_h > limit,
    }


def _curve(settings: Settings) -> list[list[float]] | None:
    value = effective_value(settings, "control_curve")
    if not isinstance(value, list):
        return None
    return [[float(p[0]), float(p[1])] for p in value]


def _dict(value: Any) -> Json:
    """Return ``value`` when it is a JSON object, else an empty one."""
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def house_payload(
    models: Path, settings: Settings, now: datetime | None = None, *, embedded: bool = False
) -> tuple[int, Json]:
    """Return the status and body of ``GET api/v1/insight/house``.

    Parameters
    ----------
    models
        Models directory.
    settings
        Effective settings (floor area, current curve).
    now
        Wall time for the learner's age; now when omitted.
    embedded
        The service runs the learner itself, so its health uses the configured
        ``house_learn_interval_h`` unless ``status.json`` names an interval.

    Returns
    -------
    tuple
        Always ``200``: the champion's insight (``state`` ``ready``, the score
        recomputed for the current floor area, the proposal marked ``stale`` when the
        curve changed since the run), or ``state`` ``learning`` / ``not_run`` with what
        is missing (also when the learner's files are refused); every body has
        ``learner`` (:func:`learner_health`).
    """
    run = last_run(models)
    health = learner_health(
        run, now, settings.house_learn_interval_h if embedded else DEFAULT_INTERVAL_H
    )
    try:
        found = champion(models)
    except LearnerFileError as exc:
        LOGGER.warning("not serving the house model: %s", exc)
        why = [UNREADABLE.format(why=exc)]
        return 200, {"state": "learning", "missing": why, "last_run": run, "learner": health}
    if found is None:
        if run is None:
            return 200, {
                "state": "not_run",
                "missing": [NOT_RUN],
                "last_run": None,
                "learner": health,
            }
        missing = run.get("missing") or []
        if not missing and run.get("error"):
            missing = [f"the last learner run failed: {run['error']}"]
        if not missing:
            missing = [run.get("message") or "no model has been promoted yet"]
        return 200, {"state": "learning", "missing": missing, "last_run": run, "learner": health}
    current, insight = found
    body = dict(insight)
    ua = _dict(insight.get("ua"))
    cred = _dict(insight.get("credibility"))
    interval = ua.get("interval_90")
    body["score"] = score(
        _float(ua.get("w_per_k")),
        interval if isinstance(interval, list) else None,
        settings.house_floor_area_m2,
        credible=bool(cred.get("credible")),
        message=cred.get("message"),
    )
    proposal = insight.get("proposal")
    if isinstance(proposal, dict):
        curve = _curve(settings)
        body["proposal"] = proposal | {
            "current_curve": curve,
            "stale": curve is not None and proposal.get("based_on_curve") != curve,
        }
    body["state"] = "ready"
    body["champion"] = {
        "model": current.get("model"),
        "promoted_at": current.get("promoted_at"),
    }
    body["last_run"] = run
    body["learner"] = health
    return 200, body


def history_payload(models: Path, settings: Settings) -> Json:
    """Return the body of ``GET api/v1/insight/house/history``: one entry per promoted model.

    Runs that are not plain bounded JSON with the expected types are left out.
    """
    index = read_json(models / INDEX) if _models_ok(models) else None
    runs = index.get("runs", []) if isinstance(index, dict) else []
    runs = runs if isinstance(runs, list) else []
    current = read_json(models / CURRENT) if _models_ok(models) else None
    champion_name = current.get("model") if isinstance(current, dict) else None
    out = []
    for raw in runs[:MAX_ITEMS]:
        if not isinstance(raw, dict) or raw.get("promoted") is not True:
            continue
        try:
            run = bounded(raw)
            _number_or_none(run.get("ua_w_per_k"), "ua_w_per_k")
            _pair(run.get("ua_interval_90"), "ua_interval_90")
            _number_or_none(run.get("time_constant_h"), "time_constant_h")
            _number_or_none(run.get("challenger_room_rmse_k"), "challenger_room_rmse_k")
        except ValueError as exc:
            LOGGER.warning("ignoring a run in the learner's index.json: %s", exc)
            continue
        interval = run.get("ua_interval_90")
        out.append(
            {
                "model": run.get("model"),
                "data_to": run.get("data_to"),
                "generated": run.get("generated"),
                "champion": run.get("model") == champion_name,
                "ua_w_per_k": run.get("ua_w_per_k"),
                "ua_interval_90": interval,
                "time_constant_h": run.get("time_constant_h"),
                "credible": run.get("credible"),
                "room_rmse_24h_k": run.get("challenger_room_rmse_k"),
                "score": score(
                    _float(run.get("ua_w_per_k")),
                    interval if isinstance(interval, list) else None,
                    settings.house_floor_area_m2,
                    credible=bool(run.get("credible")),
                ),
            }
        )
    return {"floor_area_m2": settings.house_floor_area_m2, "models": out}


def proposal_changes(models: Path, settings: Settings) -> tuple[int, Json]:
    """Return the draft of the champion's curve proposal (``insight/house/proposal/draft``).

    Returns
    -------
    tuple
        ``200`` with ``changes`` (``control_curve``), the label, the model and an
        apply comment, or ``404`` when there is no champion or it has no proposal.
    """
    try:
        found = champion(models)
    except LearnerFileError as exc:
        return 404, {"detail": f"the house model cannot be read: {exc}"}
    if found is None:
        return 404, {"detail": "no house model has been promoted yet"}
    current, insight = found
    proposal = _dict(insight.get("proposal"))
    curve = proposal.get("curve")
    if not isinstance(curve, list) or not curve:
        return 404, {"detail": f"house model {current.get('model')} has no curve proposal"}
    model = str(current.get("model"))
    now = _curve(settings)
    return 200, {
        "label": SUGGESTION_LABEL,
        "model": model,
        "comment": f"{SUGGESTION_LABEL} ({model})",
        "changes": {"control_curve": curve},
        "current": {"control_curve": now},
        "stale": now is not None and proposal.get("based_on_curve") != now,
        "credible": bool(proposal.get("credible")),
        "points": proposal.get("points"),
    }


def learner_config(settings: Settings, version: int | None) -> Json:
    """Return the configuration the learner reads (control and house fields, no secrets)."""
    return {
        "ovenbird_learner_config": LEARNER_CONFIG_FORMAT,
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "version": version,
        "effective": {
            name: effective_value(settings, name)
            for name in Settings.model_fields
            if name.startswith(LEARNER_PREFIXES) and name not in SECRET_FIELDS
        },
    }


def learner_dir(settings: Settings) -> Path:
    """Return the directory the service writes for the learner (read-only to it)."""
    return settings.data_dir / LEARNER_DIR


def prepare_dirs(settings: Settings) -> None:
    """Create the hand-off directories with their modes; a link in their place is refused.

    ``learner`` is 0750 (the learner reads it through the service's group);
    ``models`` is 2770 (a learner in the service's group writes it, its files keep
    that group).

    Raises
    ------
    OSError
        When a directory cannot be created or is a link.
    """
    for path, mode in (
        (learner_dir(settings), LEARNER_DIR_MODE),
        (models_dir(settings), MODELS_DIR_MODE),
    ):
        path.mkdir(mode=mode & 0o777, parents=True, exist_ok=True)
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode):
            raise OSError(f"{path} is not a directory")
        if stat.S_IMODE(info.st_mode) != mode:
            os.chmod(path, mode)


def _sync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic(target: Path, data: bytes) -> None:
    """Write ``data`` to ``target`` durably: unique temporary file, fsync, rename, dir fsync."""
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, LEARNER_FILE_MODE)
        os.replace(name, target)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    _sync_dir(target.parent)


def write_learner_config(settings: Settings, version: int | None) -> Path | None:
    """Write ``learner/learner-config.json`` atomically; ``None`` (logged) when it fails.

    The file lives outside the directory the learner can write; a copy the service
    wrote into ``models`` before is removed (the link itself, never its target).
    """
    target = learner_dir(settings) / LEARNER_CONFIG
    text = json.dumps(learner_config(settings, version), indent=2)
    try:
        prepare_dirs(settings)
        write_atomic(target, text.encode("utf-8"))
    except OSError:
        LOGGER.exception("cannot write %s", target)
        return None
    for legacy in (LEARNER_CONFIG, LEARNER_CONFIG + ".tmp"):
        try:
            (models_dir(settings) / legacy).unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            LOGGER.warning("cannot remove the old models/%s: %s", legacy, exc)
    return target


def export_history(settings: Settings) -> Path | None:
    """Give the learner the current history snapshot in ``learner/history.snapshot.db``.

    A hard link to ``history.snapshot.db`` (no extra space; the snapshot is replaced
    atomically, so the link keeps a consistent copy until the next export), or a
    copy where links are not possible. Nothing happens while the export is current.

    Returns
    -------
    Path or None
        The export, or ``None`` without a snapshot or when it fails (logged).
    """
    source = settings.snapshot_path
    target = learner_dir(settings) / HISTORY_EXPORT
    try:
        src = os.lstat(source)
    except FileNotFoundError:
        return None
    except OSError:
        LOGGER.exception("cannot read %s", source)
        return None
    if not stat.S_ISREG(src.st_mode):
        LOGGER.warning("not exporting %s: not a regular file", source)
        return None
    try:
        prepare_dirs(settings)
        try:
            dst = os.lstat(target)
        except FileNotFoundError:
            dst = None
        if dst is not None and (dst.st_ino == src.st_ino and dst.st_dev == src.st_dev):
            return target
        if dst is not None and (dst.st_mtime_ns, dst.st_size) == (src.st_mtime_ns, src.st_size):
            return target
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        tmp.unlink(missing_ok=True)
        try:
            os.link(source, tmp, follow_symlinks=False)
        except OSError:
            shutil.copy2(source, tmp, follow_symlinks=False)
            os.chmod(tmp, LEARNER_FILE_MODE)
            with open(tmp, "rb") as handle:
                os.fsync(handle.fileno())
        os.replace(tmp, target)
        _sync_dir(target.parent)
    except OSError:
        LOGGER.exception("cannot export the history snapshot for the learner")
        return None
    LOGGER.info("history snapshot exported for the learner to %s", target)
    return target


async def run_handoff(
    settings: Callable[[], Settings], interval_s: float = EXPORT_INTERVAL_S
) -> None:
    """Keep the learner's history export current (a supervised service component)."""
    while True:
        await asyncio.to_thread(export_history, settings())
        await asyncio.sleep(interval_s)
