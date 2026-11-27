# Model plan: offline evaluation

Status: the planner fails the gate. Do not switch it on from this evidence alone.

The model plan shifts the room-temperature target by a small amount (set back at most
0.5 K, pre-heat at most 0.3 K) from the learned house model and the weather forecast.
This page shows what it does in simulation, including when the model or the forecast is
wrong. All numbers come from `python -m ovenbird_sim.evaluate model-plan` and can be
reproduced with the commands below.

## Summary

- 61 of 84 cells pass the gate and 23 fail (a cell is scenario x model variant x forecast
  variant). Failures: 23 times degree-hours below comfort rose too much, 9 times
  degree-hours below comfort minus 0.5 K rose, 3 times compressor starts rose too much.
- The benefit is real on sunny days with the correct model. Degree-hours above the band
  (room above 21.5 °C) fall from 21.4 to 15.3 Kh (`sunny_cold`) and from 36.8 to 30.5 Kh
  (`sunny_mild`) over 7 days, with a perfect forecast.
- The cost is in `sunny_mild`: with the correct model and a perfect forecast the room is
  below comfort 23.7 -> 26.3 Kh and below comfort minus 0.5 K 0.73 -> 1.23 Kh. The gate
  fails there.
- A forecast of sun that does not arrive (`missing_sun`, perfect forecast) costs +0.84 Kh
  below comfort, and cuts compressor starts from 1.57 to 0.86 per day. Sun that arrives
  unforecast (`unforecast_sun`, perfect forecast) costs +4.8 Kh below comfort and +0.86
  starts per day.
- Wrong models make some cells worse. The largest changes: `sunny_mild` with UA x0.7 and a noisy forecast, +5.8 Kh below comfort and
  +1.47 Kh below comfort minus 0.5 K; `missing_sun` with solar aperture x2, +4.1 Kh below
  comfort.
- Most of these differences are of the same size as the sensitivity of the loop itself.
  Shifting the true outside temperature by 0.1 K, with no planner, moves degree-hours
  below comfort by up to 15 Kh (`sunny_mild`: 16.9 to 32.2 Kh) and starts by up to 4 per
  day. The gate tolerances (0.5 Kh, 0.5 starts per day) are smaller than that. Single cell
  verdicts are therefore not reliable; the pattern over many cells is.
- No setting in the sweep passes every cell and keeps a benefit (see the sweep section).

## How it was run

Code: ovenbird commit `f1859f2` with uncommitted changes (the planner in
`packages/core/src/ovenbird_core/control/planner.py`, the closed-loop plan hook and the
evaluation modules in `packages/sim`). The run is not tied to a clean commit. Re-run it
after the planner is committed.

Commands (from the repository root):

```fish
uv run python -m ovenbird_sim.evaluate model-plan --out out/model-plan
uv run python -m ovenbird_sim.evaluate model-plan --quick --out out/model-plan-quick
uv run python -m ovenbird_sim.evaluate model-plan --no-sweep --out out/model-plan-grid
```

- The full run is 1782 simulations. It took 688 s wall time on a 12-core machine (about
  3.4 s CPU per simulation, in a process pool). The sweep and its re-runs are about 1570 of the
  1782 simulations; the grid and the sensitivity runs alone are about 210.
- `--quick` runs 2 scenarios x 2 models, perfect forecast, 3 days, in about 10 s.
- Options: `--days` (default 8), `--seeds` (default 3), `--workers`, `--no-sweep`.
- The command exits with status 1 when any cell fails the gate.
- It writes `model_plan.json` (every KPI, every verdict, the intervals, the sweep) and
  `model_plan_tables.md` (the tables below) to `--out`.
- The runs are deterministic. Three full runs gave identical grid tables.
- Seeds: the perfect forecast uses seed 0. The noisy forecast uses seeds 0, 1 and 2 (the
  forecast error draw). Sensor noise is zero in these runs, so the seed changes only the
  forecast error. The sweep uses the perfect forecast and noisy seed 0.
- There is no `make` target; the Makefile is shared. The command above is the entry point.

## What was simulated

Plant: the reference plant (`ovenbird_sim.heishamon.reference`): a semi-detached house
with a UA of 145 W/K, a 5 kW air-to-water heat pump, mixed floor and radiator emitters.
Controller: ovenbird with the `mixed` preset, room target 21.0 °C. Each simulation is 8
days of 60 s ticks. The first day is dropped, so every KPI covers 7 days. The room starts
at 21 °C.

Paired runs: every scenario is run without the planner and with it, on the same plant and
weather. The planner sees a forecast, not the truth.

Service guards, as emulated in `ovenbird_sim.evaluate.closedloop.simulate`:

- the planner is called every 900 s of simulated time, with the controller's filtered
  outside temperature;
- the previous offset is carried: it is the offset of the last slice if that slice is
  still valid, otherwise 0;
- a slice is valid for 900 s plus 300 s grace; the controller ignores it after that;
- the controller's own rules apply (bounds, room feedback needed, wood-stove blocks).

Not emulated: missed or late calls, service restarts, the service's own checks of model
quality and forecast age, forecast fetch delays.

### Scenarios

| scenario | outside temperature | sun (peak irradiance) | forecast says |
|---|---|---|---|
| `sunny_cold` | 1 °C mean, 3 K daily swing | 350 W/m² | the same |
| `sunny_mild` | 8 °C mean, 3 K swing | 600 W/m² | the same |
| `cloudy` | 1 °C mean, 3 K swing | 80 W/m² (diffuse) | the same |
| `cold_front` | 8 °C, falling to 0 °C between 11:00 and 14:00 on day 4 | none | the same |
| `missing_sun` | as `cloudy` | 80 W/m² | clear, 350 W/m² |
| `unforecast_sun` | as `sunny_cold` | 350 W/m² | overcast, 80 W/m² |

The sun is a half sine from 08:30 to 16:30 UTC on every day. The clock is UTC.

### Planner model variants

The planner's house model is the plant's true building parameters, with one set scaled:
`correct`; UA x0.7 and x1.4; solar aperture x0.5 and x2; thermal mass x0.5 and x2
(`c_mass` and `c_air` together).

### Forecast variants

- `perfect`: the forecast is the scenario's own forecast (the truth, except in
  `missing_sun` and `unforecast_sun`, where the sun differs on purpose).
- `noisy`: the same, plus a seeded error (`ovenbird_sim.evaluate.forecast.ForecastError`):
  - irradiance of each UTC day times `exp(0.4 z - 0.08)` with `z` standard normal (mean
    factor 1; a typical day is wrong by about 40 %);
  - a temperature offset per UTC day with standard deviation 1.0 K;
  - temperature noise per hour with standard deviation 0.5 K;
  - the error grows with the lead time: weight `min(1, lead / 6 h)`. Hours in the past
    (stored with the shortest lead) are the truth. A draw depends only on the seed and
    the day or hour, never on call order.

The forecast table covers the 8 days. Hours before it repeat the first day, so the planner
has its 24 h of history from the first tick.

### KPIs and gate

Degree-hours are in K·h, summed over the 7 kept days. "Below" is the room below 21.0 °C,
"below 20.5 °C" is below comfort minus 0.5 K, "above" is above 21.5 °C. Starts, heat and
COP come from `ovenbird_sim.evaluate.kpi`. "Plan applied" is the share of ticks with a
non-zero applied offset. Cells with several seeds show the mean over seeds; the offset
maximum is the largest over seeds.

The gate (`ovenbird_sim.evaluate.plangate.judge`), applied to the seed means of every cell:

1. degree-hours below comfort minus 0.5 K rise by at most 0.1 Kh;
2. degree-hours below comfort rise by at most 5 % or 0.5 Kh, whichever is larger;
3. compressor starts per day rise by at most 5 % or 0.5 per day, whichever is larger;
4. benefit: on `sunny_cold` and `sunny_mild` with the correct model, degree-hours above
   the band fall (both forecast variants).

The tolerances were fixed before the run and were not tuned. A cell that fails in the
table text `(n/3 seeds fail)` has n seeds whose own pair fails; 14 cells pass on the seed
mean while at least one seed fails.

## Results

### Gate verdict

61 of 84 cells pass, 23 fail.

Failing cells:

- sunny_cold / aperture_x0.5 / noisy: below +0.90 Kh (allowed +0.50)
- sunny_cold / mass_x0.5 / perfect: below +0.90 Kh (allowed +0.50)
- sunny_cold / mass_x2 / perfect: below +2.32 Kh (allowed +0.50)
- sunny_cold / mass_x2 / noisy: below +1.63 Kh (allowed +0.50)
- sunny_mild / correct / perfect: below_band +0.50 Kh (allowed +0.10); below +2.56 Kh (allowed +1.18)
- sunny_mild / correct / noisy: below_band +0.13 Kh (allowed +0.10); below +2.31 Kh (allowed +1.18)
- sunny_mild / ua_x0.7 / perfect: below_band +0.45 Kh (allowed +0.10); below +3.08 Kh (allowed +1.18)
- sunny_mild / ua_x0.7 / noisy: below_band +1.47 Kh (allowed +0.10); below +5.79 Kh (allowed +1.18)
- sunny_mild / aperture_x0.5 / perfect: below_band +0.39 Kh (allowed +0.10); below +2.97 Kh (allowed +1.18)
- sunny_mild / aperture_x0.5 / noisy: below_band +0.32 Kh (allowed +0.10); below +1.54 Kh (allowed +1.18)
- sunny_mild / mass_x0.5 / noisy: below +1.34 Kh (allowed +1.18)
- sunny_mild / mass_x2 / perfect: below_band +0.78 Kh (allowed +0.10); below +4.54 Kh (allowed +1.18)
- sunny_mild / mass_x2 / noisy: below_band +0.87 Kh (allowed +0.10); below +3.94 Kh (allowed +1.18); starts +0.52/day (allowed +0.50)
- cloudy / ua_x1.4 / perfect: below +1.58 Kh (allowed +0.60)
- cloudy / aperture_x2 / perfect: below +3.47 Kh (allowed +0.60)
- missing_sun / correct / perfect: below +0.84 Kh (allowed +0.60)
- missing_sun / ua_x0.7 / noisy: below +0.61 Kh (allowed +0.60)
- missing_sun / ua_x1.4 / perfect: below +0.69 Kh (allowed +0.60)
- missing_sun / aperture_x2 / perfect: below +4.12 Kh (allowed +0.60)
- missing_sun / aperture_x2 / noisy: below +0.99 Kh (allowed +0.60)
- missing_sun / mass_x2 / perfect: below +0.68 Kh (allowed +0.60); starts +0.57/day (allowed +0.50)
- unforecast_sun / correct / perfect: below +4.80 Kh (allowed +0.50); starts +0.86/day (allowed +0.50)
- unforecast_sun / aperture_x2 / noisy: below_band +0.28 Kh (allowed +0.10); below +0.68 Kh (allowed +0.50)


### sunny_cold

Kh = K·h summed over the 7 kept days. Each cell: without / with / change.

| variant | below 21 °C (Kh) | below 20.5 °C (Kh) | above 21.5 °C (Kh) | starts/day | heat kWh/day | COP | plan applied | mean / max abs offset (K) | gate |
|---|---|---|---|---|---|---|---|---|---|
| correct, perfect | 8.82 / 8.44 / -0.38 | 0.00 / 0.00 / +0.00 | 21.38 / 15.30 / -6.08 | 2.57 / 2.43 / -0.14 | 56.8 / 56.5 / -0.3 | 4.24 / 4.26 / +0.02 | 31 % | 0.09 / 0.4 | pass |
| correct, noisy (1/3 seeds fail) | 8.82 / 8.30 / -0.52 | 0.00 / 0.00 / +0.00 | 21.38 / 16.10 / -5.28 | 2.57 / 2.19 / -0.38 | 56.8 / 56.7 / -0.2 | 4.24 / 4.25 / +0.01 | 44 % | 0.10 / 0.5 | pass |
| ua_x0.7, perfect | 8.82 / 5.86 / -2.96 | 0.00 / 0.00 / +0.00 | 21.38 / 12.34 / -9.04 | 2.57 / 1.71 / -0.86 | 56.8 / 56.8 / -0.0 | 4.24 / 4.28 / +0.04 | 29 % | 0.07 / 0.3 | pass |
| ua_x0.7, noisy (1/3 seeds fail) | 8.82 / 9.08 / +0.26 | 0.00 / 0.00 / +0.00 | 21.38 / 15.88 / -5.50 | 2.57 / 2.86 / +0.29 | 56.8 / 56.5 / -0.3 | 4.24 / 4.24 / -0.00 | 30 % | 0.08 / 0.5 | pass |
| ua_x1.4, perfect | 8.82 / 7.42 / -1.40 | 0.00 / 0.00 / +0.00 | 21.38 / 16.43 / -4.95 | 2.57 / 2.57 / +0.00 | 56.8 / 56.1 / -0.7 | 4.24 / 4.27 / +0.03 | 64 % | 0.14 / 0.5 | pass |
| ua_x1.4, noisy | 8.82 / 7.38 / -1.44 | 0.00 / 0.00 / +0.00 | 21.38 / 13.33 / -8.05 | 2.57 / 1.95 / -0.62 | 56.8 / 56.6 / -0.2 | 4.24 / 4.26 / +0.02 | 64 % | 0.15 / 0.5 | pass |
| aperture_x0.5, perfect | 8.82 / 8.59 / -0.23 | 0.00 / 0.00 / +0.00 | 21.38 / 19.95 / -1.43 | 2.57 / 2.43 / -0.14 | 56.8 / 56.6 / -0.2 | 4.24 / 4.25 / +0.01 | 25 % | 0.04 / 0.2 | pass |
| aperture_x0.5, noisy (2/3 seeds fail) | 8.82 / 9.72 / +0.90 | 0.00 / 0.00 / +0.00 | 21.38 / 14.94 / -6.44 | 2.57 / 2.86 / +0.29 | 56.8 / 56.3 / -0.5 | 4.24 / 4.23 / -0.01 | 30 % | 0.05 / 0.4 | FAIL (below) |
| aperture_x2, perfect | 8.82 / 5.51 / -3.31 | 0.00 / 0.00 / +0.00 | 21.38 / 15.66 / -5.72 | 2.57 / 1.71 / -0.86 | 56.8 / 56.6 / -0.2 | 4.24 / 4.28 / +0.04 | 62 % | 0.17 / 0.5 | pass |
| aperture_x2, noisy (1/3 seeds fail) | 8.82 / 8.32 / -0.50 | 0.00 / 0.00 / +0.00 | 21.38 / 12.93 / -8.45 | 2.57 / 2.14 / -0.43 | 56.8 / 56.4 / -0.4 | 4.24 / 4.27 / +0.03 | 62 % | 0.17 / 0.5 | pass |
| mass_x0.5, perfect (1/1 seeds fail) | 8.82 / 9.72 / +0.90 | 0.00 / 0.01 / +0.01 | 21.38 / 13.02 / -8.36 | 2.57 / 2.29 / -0.29 | 56.8 / 56.6 / -0.2 | 4.24 / 4.29 / +0.05 | 79 % | 0.25 / 0.5 | FAIL (below) |
| mass_x0.5, noisy (1/3 seeds fail) | 8.82 / 7.84 / -0.98 | 0.00 / 0.00 / +0.00 | 21.38 / 14.04 / -7.34 | 2.57 / 2.19 / -0.38 | 56.8 / 56.5 / -0.3 | 4.24 / 4.28 / +0.04 | 79 % | 0.25 / 0.5 | pass |
| mass_x2, perfect (1/1 seeds fail) | 8.82 / 11.14 / +2.32 | 0.00 / 0.00 / +0.00 | 21.38 / 18.49 / -2.89 | 2.57 / 3.00 / +0.43 | 56.8 / 56.7 / -0.2 | 4.24 / 4.24 / -0.00 | 18 % | 0.02 / 0.1 | FAIL (below) |
| mass_x2, noisy (2/3 seeds fail) | 8.82 / 10.45 / +1.63 | 0.00 / 0.00 / +0.00 | 21.38 / 17.45 / -3.93 | 2.57 / 2.71 / +0.14 | 56.8 / 56.5 / -0.3 | 4.24 / 4.24 / -0.00 | 17 % | 0.02 / 0.3 | FAIL (below) |

### sunny_mild

Kh = K·h summed over the 7 kept days. Each cell: without / with / change.

| variant | below 21 °C (Kh) | below 20.5 °C (Kh) | above 21.5 °C (Kh) | starts/day | heat kWh/day | COP | plan applied | mean / max abs offset (K) | gate |
|---|---|---|---|---|---|---|---|---|---|
| correct, perfect (1/1 seeds fail) | 23.70 / 26.26 / +2.56 | 0.73 / 1.23 / +0.50 | 36.78 / 30.48 / -6.30 | 3.86 / 4.00 / +0.14 | 27.6 / 27.6 / +0.0 | 6.04 / 6.09 / +0.05 | 57 % | 0.16 / 0.5 | FAIL (below_band, below) |
| correct, noisy (3/3 seeds fail) | 23.70 / 26.01 / +2.31 | 0.73 / 0.86 / +0.13 | 36.78 / 30.19 / -6.59 | 3.86 / 3.76 / -0.10 | 27.6 / 27.6 / +0.0 | 6.04 / 6.10 / +0.06 | 58 % | 0.16 / 0.5 | FAIL (below_band, below) |
| ua_x0.7, perfect (1/1 seeds fail) | 23.70 / 26.77 / +3.08 | 0.73 / 1.18 / +0.45 | 36.78 / 30.59 / -6.19 | 3.86 / 3.43 / -0.43 | 27.6 / 27.5 / -0.0 | 6.04 / 6.07 / +0.03 | 35 % | 0.13 / 0.5 | FAIL (below_band, below) |
| ua_x0.7, noisy (3/3 seeds fail) | 23.70 / 29.49 / +5.79 | 0.73 / 2.20 / +1.47 | 36.78 / 29.00 / -7.79 | 3.86 / 3.95 / +0.10 | 27.6 / 27.4 / -0.2 | 6.04 / 6.07 / +0.03 | 35 % | 0.13 / 0.5 | FAIL (below_band, below) |
| ua_x1.4, perfect | 23.70 / 23.37 / -0.33 | 0.73 / 0.62 / -0.11 | 36.78 / 30.53 / -6.25 | 3.86 / 3.57 / -0.29 | 27.6 / 27.4 / -0.2 | 6.04 / 6.12 / +0.08 | 72 % | 0.20 / 0.5 | pass |
| ua_x1.4, noisy | 23.70 / 22.40 / -1.30 | 0.73 / 0.33 / -0.40 | 36.78 / 30.69 / -6.10 | 3.86 / 3.62 / -0.24 | 27.6 / 27.7 / +0.1 | 6.04 / 6.14 / +0.10 | 71 % | 0.20 / 0.5 | pass |
| aperture_x0.5, perfect (1/1 seeds fail) | 23.70 / 26.67 / +2.97 | 0.73 / 1.13 / +0.39 | 36.78 / 33.99 / -2.80 | 3.86 / 3.71 / -0.14 | 27.6 / 27.7 / +0.1 | 6.04 / 6.07 / +0.03 | 31 % | 0.07 / 0.3 | FAIL (below_band, below) |
| aperture_x0.5, noisy (2/3 seeds fail) | 23.70 / 25.23 / +1.54 | 0.73 / 1.06 / +0.32 | 36.78 / 33.55 / -3.23 | 3.86 / 3.57 / -0.29 | 27.6 / 27.6 / +0.0 | 6.04 / 6.09 / +0.05 | 40 % | 0.08 / 0.5 | FAIL (below_band, below) |
| aperture_x2, perfect | 23.70 / 21.48 / -2.22 | 0.73 / 0.00 / -0.73 | 36.78 / 28.57 / -8.21 | 3.86 / 3.29 / -0.57 | 27.6 / 27.6 / -0.0 | 6.04 / 6.19 / +0.14 | 75 % | 0.23 / 0.5 | pass |
| aperture_x2, noisy (1/3 seeds fail) | 23.70 / 23.78 / +0.08 | 0.73 / 0.45 / -0.28 | 36.78 / 29.06 / -7.72 | 3.86 / 3.48 / -0.38 | 27.6 / 27.6 / -0.0 | 6.04 / 6.14 / +0.10 | 75 % | 0.22 / 0.5 | pass |
| mass_x0.5, perfect | 23.70 / 23.93 / +0.23 | 0.73 / 0.21 / -0.53 | 36.78 / 29.68 / -7.10 | 3.86 / 3.86 / +0.00 | 27.6 / 27.6 / -0.0 | 6.04 / 6.10 / +0.06 | 88 % | 0.30 / 0.5 | pass |
| mass_x0.5, noisy (2/3 seeds fail) | 23.70 / 25.04 / +1.34 | 0.73 / 0.73 / -0.01 | 36.78 / 29.10 / -7.69 | 3.86 / 4.33 / +0.48 | 27.6 / 27.6 / -0.0 | 6.04 / 6.11 / +0.07 | 87 % | 0.29 / 0.5 | FAIL (below) |
| mass_x2, perfect (1/1 seeds fail) | 23.70 / 28.24 / +4.54 | 0.73 / 1.52 / +0.78 | 36.78 / 28.49 / -8.30 | 3.86 / 4.00 / +0.14 | 27.6 / 27.3 / -0.2 | 6.04 / 5.97 / -0.07 | 27 % | 0.04 / 0.2 | FAIL (below_band, below) |
| mass_x2, noisy (3/3 seeds fail) | 23.70 / 27.64 / +3.94 | 0.73 / 1.60 / +0.87 | 36.78 / 32.57 / -4.22 | 3.86 / 4.38 / +0.52 | 27.6 / 27.5 / -0.1 | 6.04 / 6.04 / +0.00 | 27 % | 0.05 / 0.5 | FAIL (below_band, below, starts) |

### cloudy

Kh = K·h summed over the 7 kept days. Each cell: without / with / change.

| variant | below 21 °C (Kh) | below 20.5 °C (Kh) | above 21.5 °C (Kh) | starts/day | heat kWh/day | COP | plan applied | mean / max abs offset (K) | gate |
|---|---|---|---|---|---|---|---|---|---|
| correct, perfect | 11.91 / 11.88 / -0.04 | 0.00 / 0.00 / +0.00 | 0.88 / 1.12 / +0.25 | 1.57 / 1.29 / -0.29 | 60.4 / 60.6 / +0.1 | 4.24 / 4.26 / +0.02 | 18 % | 0.02 / 0.1 | pass |
| correct, noisy (2/3 seeds fail) | 11.91 / 11.84 / -0.08 | 0.00 / 0.00 / +0.00 | 0.88 / 0.89 / +0.01 | 1.57 / 1.86 / +0.29 | 60.4 / 60.3 / -0.1 | 4.24 / 4.25 / +0.00 | 19 % | 0.02 / 0.2 | pass |
| ua_x0.7, perfect | 11.91 / 11.91 / +0.00 | 0.00 / 0.00 / +0.00 | 0.88 / 0.88 / +0.00 | 1.57 / 1.57 / +0.00 | 60.4 / 60.4 / +0.0 | 4.24 / 4.24 / +0.00 | 0 % | 0.00 / 0.0 | pass |
| ua_x0.7, noisy | 11.91 / 10.35 / -1.57 | 0.00 / 0.00 / +0.00 | 0.88 / 0.95 / +0.07 | 1.57 / 1.29 / -0.29 | 60.4 / 60.5 / +0.1 | 4.24 / 4.25 / +0.01 | 4 % | 0.00 / 0.1 | pass |
| ua_x1.4, perfect (1/1 seeds fail) | 11.91 / 13.49 / +1.58 | 0.00 / 0.00 / +0.00 | 0.88 / 0.72 / -0.16 | 1.57 / 1.86 / +0.29 | 60.4 / 60.3 / -0.2 | 4.24 / 4.24 / +0.00 | 48 % | 0.06 / 0.2 | FAIL (below) |
| ua_x1.4, noisy | 11.91 / 10.47 / -1.45 | 0.00 / 0.00 / +0.00 | 0.88 / 0.46 / -0.42 | 1.57 / 1.10 / -0.48 | 60.4 / 60.5 / +0.1 | 4.24 / 4.27 / +0.03 | 48 % | 0.06 / 0.3 | pass |
| aperture_x0.5, perfect | 11.91 / 11.91 / +0.00 | 0.00 / 0.00 / +0.00 | 0.88 / 0.88 / +0.00 | 1.57 / 1.57 / +0.00 | 60.4 / 60.4 / +0.0 | 4.24 / 4.24 / +0.00 | 0 % | 0.00 / 0.0 | pass |
| aperture_x0.5, noisy (1/3 seeds fail) | 11.91 / 11.44 / -0.47 | 0.00 / 0.00 / +0.00 | 0.88 / 0.87 / -0.00 | 1.57 / 1.71 / +0.14 | 60.4 / 60.4 / -0.0 | 4.24 / 4.24 / +0.00 | 9 % | 0.01 / 0.1 | pass |
| aperture_x2, perfect (1/1 seeds fail) | 11.91 / 15.39 / +3.47 | 0.00 / 0.00 / +0.00 | 0.88 / 0.46 / -0.42 | 1.57 / 1.71 / +0.14 | 60.4 / 60.2 / -0.2 | 4.24 / 4.24 / -0.00 | 25 % | 0.04 / 0.2 | FAIL (below) |
| aperture_x2, noisy | 11.91 / 10.46 / -1.45 | 0.00 / 0.00 / +0.00 | 0.88 / 0.42 / -0.46 | 1.57 / 1.14 / -0.43 | 60.4 / 60.6 / +0.1 | 4.24 / 4.27 / +0.03 | 29 % | 0.04 / 0.4 | pass |
| mass_x0.5, perfect | 11.91 / 10.11 / -1.80 | 0.00 / 0.00 / +0.00 | 0.88 / 0.16 / -0.72 | 1.57 / 1.00 / -0.57 | 60.4 / 60.5 / +0.1 | 4.24 / 4.27 / +0.03 | 62 % | 0.12 / 0.3 | pass |
| mass_x0.5, noisy | 11.91 / 10.15 / -1.77 | 0.00 / 0.00 / +0.00 | 0.88 / 0.22 / -0.65 | 1.57 / 1.14 / -0.43 | 60.4 / 60.6 / +0.2 | 4.24 / 4.28 / +0.03 | 63 % | 0.13 / 0.5 | pass |
| mass_x2, perfect | 11.91 / 11.91 / +0.00 | 0.00 / 0.00 / +0.00 | 0.88 / 0.88 / +0.00 | 1.57 / 1.57 / +0.00 | 60.4 / 60.4 / +0.0 | 4.24 / 4.24 / +0.00 | 0 % | 0.00 / 0.0 | pass |
| mass_x2, noisy | 11.91 / 11.91 / +0.00 | 0.00 / 0.00 / +0.00 | 0.88 / 0.88 / +0.00 | 1.57 / 1.57 / +0.00 | 60.4 / 60.4 / +0.0 | 4.24 / 4.24 / +0.00 | 0 % | 0.00 / 0.0 | pass |

### cold_front

Kh = K·h summed over the 7 kept days. Each cell: without / with / change.

| variant | below 21 °C (Kh) | below 20.5 °C (Kh) | above 21.5 °C (Kh) | starts/day | heat kWh/day | COP | plan applied | mean / max abs offset (K) | gate |
|---|---|---|---|---|---|---|---|---|---|
| correct, perfect | 12.44 / 12.09 / -0.35 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.86 / +0.00 | 51.1 / 51.4 / +0.3 | 4.84 / 4.82 / -0.01 | 4 % | 0.01 / 0.2 | pass |
| correct, noisy | 12.44 / 12.00 / -0.44 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.57 / -0.29 | 51.1 / 51.1 / -0.1 | 4.84 / 4.85 / +0.01 | 4 % | 0.01 / 0.3 | pass |
| ua_x0.7, perfect | 12.44 / 12.95 / +0.51 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.57 / -0.29 | 51.1 / 51.0 / -0.1 | 4.84 / 4.85 / +0.01 | 2 % | 0.00 / 0.1 | pass |
| ua_x0.7, noisy | 12.44 / 12.47 / +0.03 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.76 / -0.10 | 51.1 / 51.1 / -0.0 | 4.84 / 4.84 / +0.00 | 1 % | 0.00 / 0.1 | pass |
| ua_x1.4, perfect | 12.44 / 11.33 / -1.11 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.57 / -0.29 | 51.1 / 51.1 / +0.0 | 4.84 / 4.84 / +0.01 | 5 % | 0.01 / 0.3 | pass |
| ua_x1.4, noisy | 12.44 / 11.27 / -1.17 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.67 / -0.19 | 51.1 / 51.2 / +0.1 | 4.84 / 4.83 / -0.00 | 5 % | 0.01 / 0.3 | pass |
| aperture_x0.5, perfect | 12.44 / 12.09 / -0.35 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.86 / +0.00 | 51.1 / 51.4 / +0.3 | 4.84 / 4.82 / -0.01 | 4 % | 0.01 / 0.2 | pass |
| aperture_x0.5, noisy | 12.44 / 12.00 / -0.44 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.57 / -0.29 | 51.1 / 51.1 / -0.1 | 4.84 / 4.85 / +0.01 | 4 % | 0.01 / 0.3 | pass |
| aperture_x2, perfect | 12.44 / 12.09 / -0.35 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.86 / +0.00 | 51.1 / 51.4 / +0.3 | 4.84 / 4.82 / -0.01 | 4 % | 0.01 / 0.2 | pass |
| aperture_x2, noisy | 12.44 / 12.00 / -0.44 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.57 / -0.29 | 51.1 / 51.1 / -0.1 | 4.84 / 4.85 / +0.01 | 4 % | 0.01 / 0.3 | pass |
| mass_x0.5, perfect | 12.44 / 11.13 / -1.30 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.86 / +0.00 | 51.1 / 51.5 / +0.3 | 4.84 / 4.82 / -0.02 | 5 % | 0.01 / 0.3 | pass |
| mass_x0.5, noisy | 12.44 / 11.07 / -1.37 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.57 / -0.29 | 51.1 / 51.2 / +0.0 | 4.84 / 4.84 / +0.01 | 5 % | 0.01 / 0.3 | pass |
| mass_x2, perfect | 12.44 / 12.44 / +0.00 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.86 / +0.00 | 51.1 / 51.1 / +0.0 | 4.84 / 4.84 / +0.00 | 0 % | 0.00 / 0.0 | pass |
| mass_x2, noisy | 12.44 / 12.56 / +0.12 | 0.00 / 0.00 / +0.00 | 2.14 / 2.14 / +0.00 | 0.86 / 0.76 / -0.10 | 51.1 / 51.1 / -0.0 | 4.84 / 4.84 / +0.00 | 1 % | 0.00 / 0.1 | pass |

### missing_sun

Kh = K·h summed over the 7 kept days. Each cell: without / with / change.

| variant | below 21 °C (Kh) | below 20.5 °C (Kh) | above 21.5 °C (Kh) | starts/day | heat kWh/day | COP | plan applied | mean / max abs offset (K) | gate |
|---|---|---|---|---|---|---|---|---|---|
| correct, perfect (1/1 seeds fail) | 11.91 / 12.75 / +0.84 | 0.00 / 0.00 / +0.00 | 0.88 / 0.08 / -0.80 | 1.57 / 0.86 / -0.71 | 60.4 / 60.5 / +0.1 | 4.24 / 4.26 / +0.02 | 31 % | 0.09 / 0.4 | FAIL (below) |
| correct, noisy (1/3 seeds fail) | 11.91 / 12.23 / +0.31 | 0.00 / 0.00 / +0.00 | 0.88 / 0.02 / -0.86 | 1.57 / 0.90 / -0.67 | 60.4 / 60.5 / +0.1 | 4.24 / 4.28 / +0.04 | 44 % | 0.10 / 0.5 | pass |
| ua_x0.7, perfect | 11.91 / 11.69 / -0.23 | 0.00 / 0.00 / +0.00 | 0.88 / 0.00 / -0.88 | 1.57 / 1.14 / -0.43 | 60.4 / 60.5 / +0.1 | 4.24 / 4.27 / +0.03 | 29 % | 0.07 / 0.3 | pass |
| ua_x0.7, noisy (1/3 seeds fail) | 11.91 / 12.52 / +0.61 | 0.00 / 0.00 / +0.00 | 0.88 / 0.00 / -0.88 | 1.57 / 1.24 / -0.33 | 60.4 / 60.4 / -0.0 | 4.24 / 4.26 / +0.02 | 30 % | 0.08 / 0.5 | FAIL (below) |
| ua_x1.4, perfect (1/1 seeds fail) | 11.91 / 12.61 / +0.69 | 0.00 / 0.00 / +0.00 | 0.88 / 0.00 / -0.88 | 1.57 / 0.86 / -0.71 | 60.4 / 60.5 / +0.0 | 4.24 / 4.29 / +0.05 | 64 % | 0.14 / 0.5 | FAIL (below) |
| ua_x1.4, noisy (2/3 seeds fail) | 11.91 / 12.03 / +0.12 | 0.00 / 0.00 / +0.00 | 0.88 / 0.00 / -0.88 | 1.57 / 0.86 / -0.71 | 60.4 / 60.4 / +0.0 | 4.24 / 4.29 / +0.05 | 64 % | 0.15 / 0.5 | pass |
| aperture_x0.5, perfect | 11.91 / 10.38 / -1.54 | 0.00 / 0.00 / +0.00 | 0.88 / 0.45 / -0.43 | 1.57 / 0.86 / -0.71 | 60.4 / 60.6 / +0.2 | 4.24 / 4.27 / +0.03 | 25 % | 0.04 / 0.2 | pass |
| aperture_x0.5, noisy (1/3 seeds fail) | 11.91 / 11.68 / -0.24 | 0.00 / 0.00 / +0.00 | 0.88 / 0.35 / -0.53 | 1.57 / 1.38 / -0.19 | 60.4 / 60.7 / +0.3 | 4.24 / 4.26 / +0.02 | 30 % | 0.05 / 0.4 | pass |
| aperture_x2, perfect (1/1 seeds fail) | 11.91 / 16.03 / +4.12 | 0.00 / 0.00 / +0.00 | 0.88 / 0.00 / -0.88 | 1.57 / 1.29 / -0.29 | 60.4 / 60.3 / -0.2 | 4.24 / 4.28 / +0.04 | 62 % | 0.17 / 0.5 | FAIL (below) |
| aperture_x2, noisy (2/3 seeds fail) | 11.91 / 12.90 / +0.99 | 0.00 / 0.00 / +0.00 | 0.88 / 0.00 / -0.88 | 1.57 / 0.48 / -1.10 | 60.4 / 60.2 / -0.2 | 4.24 / 4.30 / +0.06 | 62 % | 0.17 / 0.5 | FAIL (below) |
| mass_x0.5, perfect | 11.91 / 12.32 / +0.40 | 0.00 / 0.00 / +0.00 | 0.88 / 0.00 / -0.88 | 1.57 / 0.71 / -0.86 | 60.4 / 60.6 / +0.1 | 4.24 / 4.30 / +0.06 | 79 % | 0.25 / 0.5 | pass |
| mass_x0.5, noisy (1/3 seeds fail) | 11.91 / 11.36 / -0.56 | 0.00 / 0.00 / +0.00 | 0.88 / 0.00 / -0.88 | 1.57 / 0.67 / -0.90 | 60.4 / 60.6 / +0.1 | 4.24 / 4.30 / +0.06 | 79 % | 0.25 / 0.5 | pass |
| mass_x2, perfect (1/1 seeds fail) | 11.91 / 12.59 / +0.68 | 0.00 / 0.00 / +0.00 | 0.88 / 0.87 / -0.01 | 1.57 / 2.14 / +0.57 | 60.4 / 60.1 / -0.4 | 4.24 / 4.25 / +0.01 | 18 % | 0.02 / 0.1 | FAIL (below, starts) |
| mass_x2, noisy | 11.91 / 9.85 / -2.07 | 0.00 / 0.00 / +0.00 | 0.88 / 0.99 / +0.11 | 1.57 / 1.19 / -0.38 | 60.4 / 60.4 / -0.0 | 4.24 / 4.27 / +0.03 | 17 % | 0.02 / 0.3 | pass |

### unforecast_sun

Kh = K·h summed over the 7 kept days. Each cell: without / with / change.

| variant | below 21 °C (Kh) | below 20.5 °C (Kh) | above 21.5 °C (Kh) | starts/day | heat kWh/day | COP | plan applied | mean / max abs offset (K) | gate |
|---|---|---|---|---|---|---|---|---|---|
| correct, perfect (1/1 seeds fail) | 8.82 / 13.62 / +4.80 | 0.00 / 0.00 / +0.00 | 21.38 / 11.29 / -10.09 | 2.57 / 3.43 / +0.86 | 56.8 / 56.4 / -0.5 | 4.24 / 4.20 / -0.04 | 18 % | 0.02 / 0.1 | FAIL (below, starts) |
| correct, noisy (1/3 seeds fail) | 8.82 / 9.28 / +0.46 | 0.00 / 0.00 / +0.00 | 21.38 / 15.38 / -6.00 | 2.57 / 2.71 / +0.14 | 56.8 / 56.3 / -0.5 | 4.24 / 4.23 / -0.01 | 19 % | 0.02 / 0.2 | pass |
| ua_x0.7, perfect | 8.82 / 8.82 / +0.00 | 0.00 / 0.00 / +0.00 | 21.38 / 21.38 / +0.00 | 2.57 / 2.57 / +0.00 | 56.8 / 56.8 / +0.0 | 4.24 / 4.24 / +0.00 | 0 % | 0.00 / 0.0 | pass |
| ua_x0.7, noisy (1/3 seeds fail) | 8.82 / 9.05 / +0.23 | 0.00 / 0.00 / +0.00 | 21.38 / 19.58 / -1.80 | 2.57 / 2.57 / +0.00 | 56.8 / 56.8 / -0.0 | 4.24 / 4.24 / -0.00 | 4 % | 0.00 / 0.1 | pass |
| ua_x1.4, perfect | 8.82 / 7.61 / -1.21 | 0.00 / 0.00 / +0.00 | 21.38 / 20.10 / -1.28 | 2.57 / 2.00 / -0.57 | 56.8 / 57.0 / +0.2 | 4.24 / 4.25 / +0.01 | 48 % | 0.06 / 0.2 | pass |
| ua_x1.4, noisy | 8.82 / 6.57 / -2.25 | 0.00 / 0.00 / +0.00 | 21.38 / 17.91 / -3.47 | 2.57 / 2.14 / -0.43 | 56.8 / 56.6 / -0.2 | 4.24 / 4.26 / +0.02 | 48 % | 0.06 / 0.3 | pass |
| aperture_x0.5, perfect | 8.82 / 8.82 / +0.00 | 0.00 / 0.00 / +0.00 | 21.38 / 21.38 / +0.00 | 2.57 / 2.57 / +0.00 | 56.8 / 56.8 / +0.0 | 4.24 / 4.24 / +0.00 | 0 % | 0.00 / 0.0 | pass |
| aperture_x0.5, noisy (2/3 seeds fail) | 8.82 / 9.21 / +0.39 | 0.00 / 0.00 / +0.00 | 21.38 / 18.22 / -3.16 | 2.57 / 2.71 / +0.14 | 56.8 / 56.7 / -0.1 | 4.24 / 4.23 / -0.01 | 9 % | 0.01 / 0.1 | pass |
| aperture_x2, perfect | 8.82 / 8.56 / -0.26 | 0.00 / 0.00 / +0.00 | 21.38 / 19.90 / -1.48 | 2.57 / 2.43 / -0.14 | 56.8 / 56.6 / -0.2 | 4.24 / 4.25 / +0.01 | 25 % | 0.04 / 0.2 | pass |
| aperture_x2, noisy (1/3 seeds fail) | 8.82 / 9.50 / +0.68 | 0.00 / 0.28 / +0.28 | 21.38 / 18.95 / -2.43 | 2.57 / 2.71 / +0.14 | 56.8 / 56.6 / -0.2 | 4.24 / 4.24 / -0.00 | 29 % | 0.04 / 0.4 | FAIL (below_band, below) |
| mass_x0.5, perfect | 8.82 / 7.15 / -1.67 | 0.00 / 0.00 / +0.00 | 21.38 / 15.09 / -6.29 | 2.57 / 2.43 / -0.14 | 56.8 / 56.6 / -0.2 | 4.24 / 4.24 / -0.00 | 62 % | 0.12 / 0.3 | pass |
| mass_x0.5, noisy | 8.82 / 6.11 / -2.71 | 0.00 / 0.00 / +0.00 | 21.38 / 14.46 / -6.92 | 2.57 / 1.95 / -0.62 | 56.8 / 56.7 / -0.2 | 4.24 / 4.27 / +0.03 | 63 % | 0.13 / 0.5 | pass |
| mass_x2, perfect | 8.82 / 8.82 / +0.00 | 0.00 / 0.00 / +0.00 | 21.38 / 21.38 / +0.00 | 2.57 / 2.57 / +0.00 | 56.8 / 56.8 / +0.0 | 4.24 / 4.24 / +0.00 | 0 % | 0.00 / 0.0 | pass |
| mass_x2, noisy | 8.82 / 8.82 / +0.00 | 0.00 / 0.00 / +0.00 | 21.38 / 21.38 / +0.00 | 2.57 / 2.57 / +0.00 | 56.8 / 56.8 / +0.0 | 4.24 / 4.24 / +0.00 | 0 % | 0.00 / 0.0 | pass |


### Benefit with the correct model (95 % day-block bootstrap of the change, Kh)

| scenario | forecast | above 21.5 °C | below 21 °C | below 20.5 °C |
|---|---|---|---|---|
| sunny_cold | perfect | -6.08 [-14.53, +2.89] | -0.38 [-7.48, +6.69] | +0.00 [+0.00, +0.00] |
| sunny_cold | noisy | -5.28 [-10.50, -0.35] | -0.52 [-3.83, +2.83] | +0.00 [+0.00, +0.00] |
| sunny_mild | perfect | -6.30 [-8.55, -4.33] | +2.56 [-2.14, +7.65] | +0.50 [-0.54, +1.58] |
| sunny_mild | noisy | -6.59 [-7.75, -5.39] | +2.31 [-0.06, +4.99] | +0.13 [-0.29, +0.63] |


### Sensitivity floor: runs without the planner, outside temperature shifted by -0.1, -0.05, +0.05, +0.1 K

Range (minimum to maximum) of the baseline KPIs over those runs and the unshifted run. The loop rounds its setpoint to whole kelvin, so a change of the same size with the planner is not distinguishable from this.

| scenario | below 21 °C (Kh) | below 20.5 °C (Kh) | above 21.5 °C (Kh) | starts/day |
|---|---|---|---|---|
| sunny_cold | 5.95 to 9.89 | 0.00 to 0.00 | 10.97 to 21.38 | 2.43 to 3.43 |
| sunny_mild | 16.92 to 32.24 | 0.12 to 4.56 | 35.45 to 36.78 | 2.43 to 6.86 |
| cloudy | 8.77 to 15.10 | 0.00 to 0.00 | 0.07 to 0.88 | 1.43 to 2.43 |
| cold_front | 12.05 to 14.47 | 0.00 to 0.00 | 1.99 to 2.28 | 0.57 to 0.86 |
| missing_sun | 8.77 to 15.10 | 0.00 to 0.00 | 0.07 to 0.88 | 1.43 to 2.43 |
| unforecast_sun | 5.95 to 9.89 | 0.00 to 0.00 | 10.97 to 21.38 | 2.43 to 3.43 |


### Planner setting sweep

Every setting over the same grid (6 scenarios x 7 models, perfect and 1 noisy seed). Benefit: reduction of Kh above the band, sunny scenarios, correct model, perfect forecast. Below: change of Kh below comfort over the same cells.

| setting | failing cells | above reduced (Kh) | below change (Kh) |
|---|---|---|---|
| g0.3 sb0.2 ph0.3 dz0.2 | 21 of 84 | +6.41 | +9.35 |
| g0.3 sb0.2 ph0.3 dz0.3 | 13 of 84 | +3.36 | +0.12 |
| g0.3 sb0.3 ph0.3 dz0.2 | 18 of 84 | +6.41 | +9.35 |
| g0.3 sb0.3 ph0.3 dz0.3 | 11 of 84 | +3.36 | +0.12 |
| g0.3 sb0.5 ph0.3 dz0.2 | 20 of 84 | +6.41 | +9.35 |
| g0.3 sb0.5 ph0.3 dz0.3 | 10 of 84 | +3.36 | +0.12 |
| g0.45 sb0.2 ph0.3 dz0.2 | 27 of 84 | +10.75 | +6.95 |
| g0.45 sb0.2 ph0.3 dz0.3 | 20 of 84 | +6.54 | +9.44 |
| g0.45 sb0.3 ph0.3 dz0.2 | 25 of 84 | +9.35 | +5.67 |
| g0.45 sb0.3 ph0.3 dz0.3 | 20 of 84 | +0.25 | +6.38 |
| g0.45 sb0.5 ph0.3 dz0.2 | 30 of 84 | +10.00 | +4.79 |
| g0.45 sb0.5 ph0.3 dz0.3 | 17 of 84 | +0.25 | +6.38 |
| g0.6 sb0.2 ph0.3 dz0.2 | 23 of 84 | +0.11 | +0.58 |
| g0.6 sb0.2 ph0.3 dz0.3 | 27 of 84 | +10.84 | +5.06 |
| g0.6 sb0.3 ph0.3 dz0.2 | 23 of 84 | +11.85 | +1.31 |
| g0.6 sb0.3 ph0.3 dz0.3 | 22 of 84 | +10.08 | -0.24 |
| g0.6 sb0.5 ph0.3 dz0.2 | 27 of 84 | +12.38 | +2.18 |
| g0.6 sb0.5 ph0.3 dz0.3 | 28 of 84 | +13.66 | +0.31 |
| g0.6 sb0 ph0.3 dz0.2 | 13 of 84 | +0.01 | -4.63 |
| g0.6 sb0.5 ph0 dz0.2 | 38 of 84 | +12.39 | +2.79 |

No tested setting passes every cell with a benefit left.

## Finding from the sweep

Planner settings varied: gain 0.3, 0.45, 0.6; set-back bound 0.2, 0.3, 0.5 K; dead zone
0.2, 0.3 K; plus pre-heat only (set-back bound 0, pre-heat 0.3 K) and set-back only (set-back 0.5 K, pre-heat
bound 0) at the other defaults. The pre-heat bound is 0.3 K (except set-back only) and the horizon 6 h throughout. Each
setting runs the same 84 cells (perfect forecast and one noisy seed).

- No setting passes every cell. The fewest failures: gain 0.3, dead zone 0.3 K (10 to 13
  of 84, any set-back bound). It keeps a benefit of 3.4 Kh less above the band over the
  sunny, correct-model, perfect-forecast cells (the default setting: 12.4 Kh less) and
  changes the degree-hours below comfort by +0.1 Kh over the same cells. It still fails
  on the `sunny_cold` benefit criterion and on cells with solar aperture x2 or thermal
  mass x0.5 (the lists of failing cells per setting are in `model_plan.json`).
- Set-back only (no pre-heat) has the most failures (38 of 84) and a benefit of 12.4 Kh.
  Pre-heat only has 13 failing cells and no benefit left (0.01 Kh).
- The sweep is not smooth. Gain 0.6 with a 0.2 K set-back bound and 0.2 K dead zone
  gives 0.1 Kh benefit, with a 0.3 K bound 11.9 Kh. A small change of setting moves the
  loop into a different pattern of whole-kelvin setpoint steps. This is the sensitivity
  floor above, seen from another side. A setting that passes by chance in this sweep
  would not be trusted either.

The result for the owner: lowering the gain and widening the dead zone reduces the number
of failing cells by more than half and keeps part of the benefit, but nothing in this grid
passes the gate.

## Recommendation

1. Do not switch the planner on in control from these results. The gate fails in 23 of 84
   cells, including the correct model with a perfect forecast on `sunny_mild`.
2. If the owner wants to continue, the conservative candidate is gain 0.3 with a 0.3 K dead
   zone. It needs a better evaluation first: several weather replicas per scenario
   (small shifts of the outside temperature), so that a cell verdict is larger than the
   sensitivity floor, and the same grid on the plant fitted to the owner's house.
3. Running the planner in shadow (compute and log the offset, do not apply it) costs
   nothing in comfort and shows how often the real forecast would have been wrong.

## Limits

- The plant is the reference house, not the owner's. The planner's "correct" model has
  the same structure as the plant, so `correct` is a best case that a fitted model will
  not reach. The wrong-model variants scale single parameters; a real model error is
  mixed.
- Weather is synthetic: a sine day, half-sine sun, one front. There is no wind, rain,
  snow, no multi-day weather change except the front, no seasonal sun height.
- The forecast errors are simulated with the model above. Real forecast errors are
  correlated in time and across variables in ways this model does not capture.
- Sensor noise is zero (the default sensor model); the room sensor has its default
  send-on-delta behaviour. The sensitivity floor therefore comes from the quantised
  control itself, and real noise would add to it.
- The plant has no domestic hot water cycle and no wood stove. Defrost is modelled
  (5 min cycles near -4 °C). Hot water cycles would add compressor starts to both runs
  and interfere with the plan's timing; this is not tested.
- Seven kept days per run. Days are not independent (the house carries heat over), so
  the day-block bootstrap intervals are rough. They are only given for the correct-model
  cells and are wide.
- The comparison to the author's scratch study is loose. The scratch study used 0 W/m²
  as overcast and left day 0 without sun; here overcast is 80 W/m² and the sun is on every
  day. The scratch values (for example `sunny_cold` above the band 24.0 -> 14.1 Kh) are
  of the same kind as here (21.4 -> 15.3 Kh) but not equal.
- The "largest setpoint step" KPI is in `model_plan.json`; it is a mean over seeds in
  cells with several seeds. In 15 cells the largest step with the plan exceeds the
  largest step without (up to 5 K against 3 K, `sunny_mild` with mass x2).

## Ablation

The planner is not added as a term to `ovenbird_sim.evaluate.ablation`. That factorial is
fixed at four terms (`TERMS`, `combos()` returns 16 settings) and is used by the
counterfactual replay on recorded weather. A fifth term would change every `combos()`
consumer to 32 settings, and the replay has neither a forecast nor a house model to feed
the planner. The paired runs on this page are the model plan's attribution: the same
controller with the planner on and off.

`ovenbird_sim.evaluate.openloop` also passes `plan=None`. It replays recorded captures
without a stored forecast, so a plan provider would have nothing to plan from; it is
unchanged.

## Closed-loop plan hook

`LoopOptions(plan_provider=..., plan_forecast=..., plan_every_s=900.0)`. The provider is
called as `provider(PlanRequest(now, outside_filtered_c, previous_offset_k, forecast))` and
returns a `PlanSlice` or `None`; `forecast.rows(now)` returns the hourly rows the planner
reads. With `plan_provider=None` (the default) the run is identical to before.
`Trace.plan_offset_k` holds the offset the controller applied per tick, and the ladder
level `model_plan` counts as room feedback in `FEEDBACK_LEVELS`.
