"""Test a broker connection (``POST api/v1/config/mqtt/test``), subscribe-only.

The check opens its own subscribe-only session with the candidate settings (under a
client id of its own, so the running session is never displaced), subscribes to
``<base>/main/#`` and waits until a live (not retained) HeishaMon ``main/*`` value
arrives: HeishaMon publishes on change after every 5 s query, while a retained value
also comes from a board that is long gone. It never publishes, never logs or returns
the password, and ends within :data:`CHECK_LIMIT_S` seconds.
"""

from __future__ import annotations

import asyncio
import secrets
import ssl
import time
from collections.abc import Callable
from typing import Any, Final

import aiomqtt

from ovenbird.config import Settings
from ovenbird.mqtt import ReadOnlyMqttClient, SubscribeOnlyClient

CHECK_LIMIT_S: Final = 30.0
AUTH_CODES: Final = frozenset({4, 5, 134, 135})
ERROR_CODES: Final = (
    "invalid",
    "unreachable",
    "tls",
    "auth_failed",
    "refused",
    "timeout",
    "no_heishamon",
)
"""Every ``error_code`` of a failed test, in the order of the steps."""

type ClientFactory = Callable[[Settings], SubscribeOnlyClient]


def check_settings(settings: Settings) -> Settings:
    """Return ``settings`` with a client id of the check's own."""
    return settings.model_copy(update={"mqtt_client_id": f"ovenbird-check-{secrets.token_hex(4)}"})


async def mqtt_check(
    settings: Settings,
    *,
    connect: ClientFactory = ReadOnlyMqttClient,
    limit_s: float = CHECK_LIMIT_S,
) -> dict[str, Any]:
    """Connect with ``settings`` and wait for a live HeishaMon ``main/*`` value.

    Parameters
    ----------
    settings
        Candidate settings (broker, credentials, TLS, base topic).
    connect
        Builds the subscribe-only client (tests pass a fake).
    limit_s
        Overall time limit.

    Returns
    -------
    dict
        ``ok`` (connected and a live HeishaMon value seen), ``connected``,
        ``heishamon`` (a live value seen), ``topic`` (its topic), ``latency_ms``
        (connect time),
        ``error_code`` (one of :data:`ERROR_CODES`, ``None`` when ok) and ``error``.
    """
    base = settings.heishamon_base
    result: dict[str, Any] = {
        "ok": False,
        "host": settings.mqtt_host,
        "port": settings.mqtt_port,
        "base": base,
        "connected": False,
        "heishamon": False,
        "topic": None,
        "latency_ms": None,
        "error_code": None,
        "error": None,
    }
    started = time.monotonic()
    retained = False
    try:
        async with asyncio.timeout(limit_s):
            async with connect(check_settings(settings)) as client:
                result["connected"] = True
                result["latency_ms"] = round((time.monotonic() - started) * 1000)
                await client.subscribe(f"{base}/main/#")
                async for message in client.messages():
                    if message.topic.startswith(f"{base}/main/") and message.retained:
                        retained = True
                    elif message.topic.startswith(f"{base}/main/"):
                        result["heishamon"] = True
                        result["topic"] = message.topic
                        break
    except TimeoutError:
        code = "no_heishamon" if result["connected"] else "timeout"
        return _failed(result, code, _timeout_text(code, base, limit_s, retained=retained))
    except aiomqtt.MqttCodeError as exc:
        code = "auth_failed" if _rc(exc) in AUTH_CODES else "refused"
        return _failed(result, code, f"the broker refused the connection ({exc})")
    except ssl.SSLError as exc:
        return _failed(result, "tls", f"TLS failed ({exc.reason or type(exc).__name__})")
    except aiomqtt.MqttError as exc:
        return _failed(result, "unreachable", f"the broker is not reachable ({exc})")
    except OSError as exc:
        return _failed(result, "unreachable", f"the broker is not reachable ({type(exc).__name__})")
    if not result["heishamon"]:
        text = _timeout_text("no_heishamon", base, limit_s, retained=retained)
        return _failed(result, "no_heishamon", text)
    result["ok"] = True
    return result


def _rc(exc: aiomqtt.MqttCodeError) -> int | None:
    """Return the MQTT return code of an error as an integer, if it has one."""
    rc = exc.rc
    if isinstance(rc, int):
        return rc
    return None if rc is None else int(rc.value)


def _timeout_text(code: str, base: str, limit_s: float, *, retained: bool = False) -> str:
    """Return the message for a timed-out connection test.

    Parameters
    ----------
    code
        Error code of the timeout: ``no_heishamon`` or a connection timeout.
    base
        HeishaMon base topic.
    limit_s
        Time limit that elapsed, in seconds.
    retained
        Whether retained HeishaMon values arrived.
    """
    if code == "no_heishamon" and retained:
        return (
            f"connected, but only retained HeishaMon values on {base}/main/# and no live "
            f"one within {limit_s:.0f} s (is the board online?)"
        )
    if code == "no_heishamon":
        return f"connected, but no HeishaMon value on {base}/main/# within {limit_s:.0f} s"
    return f"no connection within {limit_s:.0f} s"


def _failed(result: dict[str, Any], code: str, text: str) -> dict[str, Any]:
    """Record a failure on the result and return it."""
    result["error_code"] = code
    result["error"] = text
    return result
