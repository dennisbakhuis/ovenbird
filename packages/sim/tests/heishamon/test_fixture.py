"""The committed synthetic capture slice is what its generator writes."""

from pathlib import Path

from ovenbird_sim.heishamon.fixture import write

COMMITTED = (
    Path(__file__).resolve().parents[3] / "core/tests/fixtures/synthetic/2026-01-06.jsonl.gz"
)


def test_committed_slice_is_reproducible(tmp_path: Path) -> None:
    """The committed fixture slice equals a freshly generated one."""
    fresh = tmp_path / COMMITTED.name
    write(fresh)
    assert fresh.read_bytes() == COMMITTED.read_bytes(), (
        "regenerate with: uv run python -m ovenbird_sim.heishamon.fixture"
    )
