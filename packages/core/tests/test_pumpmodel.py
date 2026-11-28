from __future__ import annotations

import pytest

from ovenbird_core.pumpmodel import PROFILES, DeiceSpec, profile_for


def test_the_verified_id_bytes_select_their_profile() -> None:
    """The verified model ID bytes select their profile, ignoring surrounding whitespace."""
    profile = profile_for("32 D4 0B 88 84 73 90 0C 85 84")
    assert profile is not None
    assert profile.name == "WH-MXC12J9E8"
    assert "14.2.2" in profile.source
    assert profile.deice == DeiceSpec()
    assert profile.to_json() == {"name": "WH-MXC12J9E8", "source": profile.source}
    assert profile_for(" 32 D4 0B 88 84 73 90 0C 85 84\n") is profile


@pytest.mark.parametrize("model", ["C2 D3 0B 33 65 B2 D3 0B 94 65", "", None, 42])
def test_unknown_or_missing_bytes_are_generic(model: object) -> None:
    """Unknown, empty or non-string model values give no profile."""
    assert profile_for(model) is None


def test_only_verified_units_have_a_profile() -> None:
    """Only the verified unit is registered."""
    assert list(PROFILES) == ["32 D4 0B 88 84 73 90 0C 85 84"]


@pytest.mark.parametrize(
    ("inlet", "outside", "mode"),
    [
        (25.5, 3.0, 2),
        (27.0, 3.0, 1),
        (45.0, -12.0, 2),
        (45.0, -9.0, 1),
        (60.0, -15.0, 1),
        (61.0, -15.0, 1),
        (45.0, None, 1),
        (None, -15.0, 1),
    ],
)
def test_the_deice_mode_follows_the_service_manual(
    inlet: float | None, outside: float | None, mode: int
) -> None:
    """The de-ice mode follows the service manual thresholds, and unknown inputs give mode 1."""
    assert DeiceSpec().mode(inlet, outside) == mode
