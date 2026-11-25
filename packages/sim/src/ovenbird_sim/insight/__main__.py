"""CLI: ``python -m ovenbird_sim.insight <captures> [options]``.

Prints the energy signature (apparent heat-loss coefficient, balance temperature,
time constant) with intervals and the design's credibility verdict, for the
whole-house indoor mean and, as a sensitivity, the living room. The RC model's
envelope conductance is read from ``<captures>/models/plant_params.json`` when
present (run ``python -m ovenbird_sim.identify`` first).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ovenbird_sim.data.dataset import build_dataset
from ovenbird_sim.insight.signature import daily, energy_signature


def _rc(path: Path) -> tuple[float | None, float | None]:
    if not path.exists():
        return None, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    building = payload.get("params", {}).get("building", {})
    derived = payload.get("derived", {})
    h = building.get("h_air_out")
    tau = derived.get("time_constant_h")
    return (float(h) if h is not None else None, float(tau) if tau is not None else None)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(prog="python -m ovenbird_sim.insight", description=__doc__)
    parser.add_argument("captures", type=Path)
    parser.add_argument("--capture-name", default="live")
    parser.add_argument(
        "--params", type=Path, help="params JSON (default <captures>/models/plant_params.json)"
    )
    parser.add_argument(
        "--design", type=float, default=-10.0, help="design outside temperature, degC"
    )
    parser.add_argument("--bootstrap", type=int, default=500)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    ds = build_dataset(args.captures, step=300.0, capture_name=args.capture_name)
    rc_h, rc_tau = _rc(args.params or args.captures / "models" / "plant_params.json")
    for indoor in ("house_mean", "room_living"):
        d = daily(ds, indoor)
        sig = energy_signature(
            d,
            indoor=indoor,
            rc_h_w_per_k=rc_h,
            design_c=args.design,
            replicates=args.bootstrap,
            seed=args.seed,
        )
        print(f"== energy signature ({indoor})")
        print("\n".join(sig.lines()))
    if rc_tau is not None:
        print(f"RC model slowest time constant {rc_tau:.0f} h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
