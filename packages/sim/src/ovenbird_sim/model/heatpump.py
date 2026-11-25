"""Heat-pump layer: switching rule, modulation, capacity, COP and defrost.

All maps are smooth closed forms whose coefficients come from identification:

capacity
    heat per compressor hertz ``k = k0 + k_o T_o + k_s T_out + k_in T_in
    + k_w exp(-t / tau_k)`` (W/Hz). The identification keys it on the return (inlet)
    reading ``T_in`` and leaves ``k_s = 0``: the outlet carries the spread the heat
    itself makes, so an outlet term feeds back on the heat at a start. ``t`` is the
    time since the heating start (the
    start-up deficit: a cold loop gets clearly less than the steady map's heat in the
    first minutes); ``Q = k Hz + q0`` (the offset
    lets the heat per hertz rise towards the minimum frequency), with the frequency in
    ``[floor, hz_max]``. The floor is ``hz_min`` but rises to
    ``hz_min_cold`` while the pump's own (integer, running-biased) outdoor reading is
    at or below ``cold_floor_outside_c``; a raised cold floor makes a pump that is
    large for its house cycle hard in cold weather.
start phase
    after a heating start and after a defrost the compressor holds ``hz_start`` for
    ``start_phase_s``, then jumps to the resume level ``hz_resume0 + hz_resume_o
    T_sensor`` (clipped to the frequency range; higher in cold weather);
    without a start phase the compressor starts at ``hz_start``;
modulation
    after the start phase the compressor integrates the outlet error
    ``e = setpoint + outlet_bias_k - T_out`` outside a deadband:
    ``dHz/dt = hz_gain (e -/+ hz_deadband_k)`` per minute, rate-limited to
    ``hz_rate_down`` / ``hz_rate_up`` Hz/min and kept within ``[hz_min, hz_max]``. The
    slow ramp-down is what lets the outlet overshoot into the stop rule; recorded runs
    can hold a frequency for tens of minutes while the outlet drifts upward.
COP
    ``ln COP = c0 + c_o T_o + c_s T_out + c_h Hz + c_hh Hz^2 + w exp(-t / tau_w)``,
    clipped to ``[cop_min, cop_max]``, with ``t`` the time since the heating start
    (the warm-up term ``w = cop_warmup``, ``tau_w = cop_warmup_tau_s``; off when the
    time constant is 0). Electrical input is ``Q / COP`` while running (the pump's own
    estimate the map is fitted to includes its circulation pump) and
    ``circulation_w`` while the compressor is off.
return delay
    the return (inlet) sensor sees the loop's return temperature ``return_delay_s``
    late, the transport delay of the emitter circuit (after a start the inlet stays
    flat for several minutes); the outlet sensor reads that return plus the
    current heat over the loop flow.
switching
    stop when the outlet stays at or above ``setpoint + stop_margin_k`` for
    ``stop_delay_s``; start when the setpoint changes and the inlet is at or below
    ``setpoint - start_trigger_margin_k``, or when the inlet stays at or below
    ``setpoint - start_steady_margin_k`` for ``start_steady_delay_s`` with an unchanged
    setpoint; never within ``min_off_s`` of a stop.
defrost
    frost is water vapour deposited on the evaporator. The coil runs at
    ``T_c = coil0 + coil_o T_o + coil_h Hz`` (fitted on the pump's outdoor pipe
    sensor); below 0 degC, vapour deposits at a rate proportional to the difference
    between the air's vapour pressure ``RH e_w(T_o)`` and the saturation pressure over
    ice at the coil ``e_i(T_c)`` (Magnus forms). A defrost starts when the deposit
    reaches ``frost_capacity_hpa_h`` (hPa h of driving pressure while running), so
    ``frost += max(0, RH e_w(T_o) - e_i(T_c)) dt / frost_capacity_hpa_h``. Without a
    fitted capacity (0, older parameter files) the empirical rate
    ``exp(d0 + d_o T_o)`` per running hour below ``defrost_max_outside_c`` is used. At
    1 a defrost of ``defrost_duration_s`` draws ``defrost_heat_w`` (negative) from the
    loop, then frost resets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields

from ovenbird_core.derived import WATER_CP_J_PER_KG_K, WATER_DENSITY_KG_PER_L


@dataclass(frozen=True, slots=True)
class HeatPumpParams:
    """Parameters of the heat pump and its circulation.

    The defaults describe no particular unit: a generic inverter air-to-water pump with
    a 20-90 Hz compressor and about 200 W of heat per hertz near 0 °C outside (a minimum
    frequency raised below 3 °C), a log-COP
    rising 3 % per kelvin of outside temperature, the commonly quoted stop
    rule (outlet at least 2 K above the setpoint for 3 min) and physical COP bounds of
    1 and 9. Fitted plants (:mod:`ovenbird_sim.identify`) and the example house
    (:mod:`ovenbird_sim.heishamon.reference`) set their own values.

    Parameters
    ----------
    start_trigger_margin_k
        Start on a setpoint change when ``inlet <= setpoint - margin``.
    start_steady_margin_k, start_steady_delay_s
        Start with a steady setpoint when ``inlet <= setpoint - margin`` for the delay.
    min_off_s
        Minimum compressor off time.
    stop_margin_k, stop_delay_s
        Stop when ``outlet >= setpoint + margin`` for the delay.
    outlet_bias_k
        Outlet the modulation aims for, relative to the setpoint.
    hz_start
        Frequency right after a start (and after a defrost), held for the start phase.
    start_phase_s
        Length of the fixed-frequency start phase (0: none).
    hz_resume0, hz_resume_o
        Frequency at the end of the start phase: ``hz_resume0 + hz_resume_o T`` with
        ``T`` the pump's (running-biased) outdoor reading.
    hz_gain
        Integral gain in Hz per minute per K of outlet error beyond the deadband.
    hz_deadband_k
        Outlet error band without frequency change.
    hz_rate_down, hz_rate_up
        Frequency rate limits in Hz per minute.
    hz_min, hz_max
        Compressor frequency range while heating.
    hz_min_cold, cold_floor_outside_c
        Raised minimum frequency at or below this outdoor-sensor reading.
    k0, k_o, k_s
        Heat per hertz: ``k0 + k_o T_o + k_s T_out`` in W/Hz.
    k_in
        Heat per hertz per K of the return (inlet) temperature.
    k_warmup, k_warmup_tau_s
        Start-up term of the heat per hertz and its time constant (0: off).
    q0_w
        Heat offset of the capacity map in W.
    cop0, cop_o, cop_s, cop_h, cop_hh
        Log-COP map coefficients.
    cop_min, cop_max
        COP bounds.
    cop_warmup, cop_warmup_tau_s
        Warm-up term of the log-COP map and its time constant (0: off).
    flow_running_lpm, flow_idle_lpm
        Loop flow with the compressor running and idle.
    circulation_w
        Electrical input while the compressor is off (the pump's estimate).
    defrost0, defrost_o
        Log frost rate per running hour: ``defrost0 + defrost_o T_o``.
    defrost_max_outside_c
        No frost build-up above this outside temperature.
    coil0, coil_o, coil_h
        Evaporator coil temperature ``coil0 + coil_o T_o + coil_h Hz`` while running.
    frost_capacity_hpa_h
        Driving vapour pressure integrated over running time (hPa h) that fills the
        coil with frost (0: use the empirical rate).
    frost_rh_pct
        Relative humidity used when none is supplied.
    defrost_duration_s
        Duration of one defrost.
    defrost_heat_w
        Heat flow into the loop during a defrost (negative).
    defrost_elec_w
        Electrical input during a defrost.
    spread_offset_k
        Calibrated outlet-minus-inlet sensor offset at zero heat.
    outside_bias_running_k
        Outdoor-unit sensor reading minus true outside temperature while running.
    return_delay_s
        Transport delay of the return temperature at the inlet sensor (0: none).
    """

    start_trigger_margin_k: float = 3.75
    start_steady_margin_k: float = 5.5
    start_steady_delay_s: float = 600.0
    min_off_s: float = 180.0
    stop_margin_k: float = 2.0
    stop_delay_s: float = 180.0
    outlet_bias_k: float = 0.2
    hz_start: float = 39.0
    start_phase_s: float = 0.0
    hz_resume0: float = 0.0
    hz_resume_o: float = 0.0
    hz_gain: float = 1.1
    hz_deadband_k: float = 0.45
    hz_rate_down: float = 0.8
    hz_rate_up: float = 6.0
    hz_min: float = 20.0
    hz_max: float = 90.0
    hz_min_cold: float = 30.0
    cold_floor_outside_c: float = 3.0
    k0: float = 200.0
    k_o: float = 5.0
    k_s: float = 0.0
    k_in: float = 0.0
    k_warmup: float = 0.0
    k_warmup_tau_s: float = 0.0
    q0_w: float = 0.0
    cop0: float = 1.5
    cop_o: float = 0.03
    cop_s: float = -0.03
    cop_h: float = 0.0
    cop_hh: float = 0.0
    cop_min: float = 1.0
    cop_max: float = 9.0
    cop_warmup: float = 0.0
    cop_warmup_tau_s: float = 0.0
    flow_running_lpm: float = 20.0
    flow_idle_lpm: float = 12.0
    circulation_w: float = 40.0
    defrost0: float = 0.0
    defrost_o: float = -0.6
    defrost_max_outside_c: float = 7.5
    coil0: float = -2.0
    coil_o: float = 0.75
    coil_h: float = -0.05
    frost_capacity_hpa_h: float = 0.0
    frost_rh_pct: float = 85.0
    defrost_duration_s: float = 360.0
    defrost_heat_w: float = -4000.0
    defrost_elec_w: float = 1200.0
    spread_offset_k: float = 0.0
    outside_bias_running_k: float = 0.0
    return_delay_s: float = 0.0

    def __post_init__(self) -> None:
        """Validate ranges."""
        if not 0 < self.hz_min <= self.hz_max or not self.hz_min <= self.hz_min_cold <= self.hz_max:
            raise ValueError("need 0 < hz_min <= hz_min_cold <= hz_max")
        if self.flow_running_lpm <= 0 or self.flow_idle_lpm <= 0:
            raise ValueError("flows must be positive")
        if self.defrost_heat_w > 0:
            raise ValueError("defrost_heat_w must be zero or negative")
        if self.stop_delay_s < 0 or self.start_steady_delay_s < 0 or self.min_off_s < 0:
            raise ValueError("delays must be non-negative")
        if self.hz_rate_down < 0 or self.hz_rate_up < 0 or self.hz_deadband_k < 0:
            raise ValueError("rate limits and deadband must be non-negative")
        if not 0 < self.cop_min <= self.cop_max:
            raise ValueError("need 0 < cop_min <= cop_max")
        if min(self.start_phase_s, self.return_delay_s, self.cop_warmup_tau_s) < 0:
            raise ValueError("start phase, return delay and warm-up time must be non-negative")
        if self.k_warmup_tau_s < 0:
            raise ValueError("capacity warm-up time must be non-negative")
        if self.frost_capacity_hpa_h < 0:
            raise ValueError("frost capacity must be non-negative")

    def replace(self, **changes: float) -> HeatPumpParams:
        """Return a copy with some fields changed."""
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        values.update(changes)
        return HeatPumpParams(**values)


def mass_flow_cp(flow_lpm: float) -> float:
    """Capacity flow ``m c_p`` in W/K of a volume flow in l/min."""
    return flow_lpm / 60.0 * WATER_DENSITY_KG_PER_L * WATER_CP_J_PER_KG_K


def heat_per_hz(
    p: HeatPumpParams,
    outside_c: float,
    outlet_c: float,
    run_s: float = math.inf,
    inlet_c: float | None = None,
) -> float:
    """Heat output per compressor hertz in W/Hz (at least 1) ``run_s`` after the start."""
    k = p.k0 + p.k_o * outside_c + p.k_s * outlet_c
    if inlet_c is not None:
        k += p.k_in * inlet_c
    if p.k_warmup_tau_s > 0 and math.isfinite(run_s):
        k += p.k_warmup * math.exp(-max(run_s, 0.0) / p.k_warmup_tau_s)
    return max(k, 1.0)


def heat_output(
    p: HeatPumpParams,
    outside_c: float,
    outlet_c: float,
    hz: float,
    run_s: float = math.inf,
    inlet_c: float | None = None,
) -> float:
    """Heat delivered to the loop at ``hz`` (at least 0)."""
    return max(heat_per_hz(p, outside_c, outlet_c, run_s, inlet_c) * hz + p.q0_w, 0.0)


def sensor_outside(p: HeatPumpParams, outside_c: float, running: bool) -> int:
    """Return the pump's own outdoor reading: integer, biased low while running."""
    return round(outside_c + (p.outside_bias_running_k if running else 0.0))


def min_frequency(p: HeatPumpParams, sensor_c: float) -> float:
    """Minimum compressor frequency for the pump's outdoor reading."""
    return p.hz_min_cold if sensor_c <= p.cold_floor_outside_c else p.hz_min


def capacity_range(
    p: HeatPumpParams,
    outside_c: float,
    outlet_c: float,
    running: bool = True,
    inlet_c: float | None = None,
) -> tuple[float, float]:
    """Minimum and maximum steady heat output in W while running."""
    floor = min_frequency(p, sensor_outside(p, outside_c, running))
    low = heat_output(p, outside_c, outlet_c, floor, inlet_c=inlet_c)
    return low, heat_output(p, outside_c, outlet_c, p.hz_max, inlet_c=inlet_c)


def warmup(p: HeatPumpParams, run_s: float) -> float:
    """Warm-up term of ``ln COP`` at ``run_s`` seconds after the heating start."""
    if p.cop_warmup_tau_s <= 0 or not math.isfinite(run_s):
        return 0.0
    return p.cop_warmup * math.exp(-max(run_s, 0.0) / p.cop_warmup_tau_s)


def cop(
    p: HeatPumpParams, outside_c: float, outlet_c: float, hz: float, run_s: float = math.inf
) -> float:
    """Coefficient of performance from the fitted log-linear map.

    Parameters
    ----------
    p
        Parameters.
    outside_c, outlet_c, hz
        Operating point.
    run_s
        Time since the heating start (the warm-up term; ``inf``: warmed up).

    Returns
    -------
    float
        COP within ``[cop_min, cop_max]``.
    """
    log_cop = p.cop0 + p.cop_o * outside_c + p.cop_s * outlet_c + p.cop_h * hz + p.cop_hh * hz * hz
    log_cop += warmup(p, run_s)
    return min(max(math.exp(log_cop), p.cop_min), p.cop_max)


def resume_frequency(p: HeatPumpParams, sensor_c: float, floor_hz: float) -> float:
    """Frequency at the end of the start phase for the pump's outdoor reading."""
    return min(max(p.hz_resume0 + p.hz_resume_o * sensor_c, floor_hz), p.hz_max)


def vapour_pressure_water_hpa(t_c: float) -> float:
    """Saturation vapour pressure over water (Magnus, hPa)."""
    return 6.112 * math.exp(17.62 * t_c / (243.12 + t_c))


def vapour_pressure_ice_hpa(t_c: float) -> float:
    """Saturation vapour pressure over ice (Magnus, hPa)."""
    return 6.112 * math.exp(22.46 * t_c / (272.62 + t_c))


def coil_temperature(p: HeatPumpParams, outside_c: float, hz: float) -> float:
    """Evaporator coil temperature while running."""
    return p.coil0 + p.coil_o * outside_c + p.coil_h * hz


def frost_driver_hpa(p: HeatPumpParams, outside_c: float, hz: float, rh_pct: float) -> float:
    """Vapour pressure driving deposition on the coil (hPa; 0 above freezing or when dry)."""
    coil = coil_temperature(p, outside_c, hz)
    if coil >= 0.0:
        return 0.0
    rh = p.frost_rh_pct if not math.isfinite(rh_pct) else min(max(rh_pct, 0.0), 100.0)
    air = rh / 100.0 * vapour_pressure_water_hpa(outside_c)
    return max(air - vapour_pressure_ice_hpa(coil), 0.0)


def frost_rate_per_s(
    p: HeatPumpParams, outside_c: float, hz: float = 35.0, rh_pct: float = math.nan
) -> float:
    """Frost build-up per running second (a defrost starts at 1).

    Parameters
    ----------
    p
        Parameters.
    outside_c
        Outside air temperature.
    hz
        Compressor frequency (the coil runs colder at higher load).
    rh_pct
        Relative humidity of the outside air (``NaN``: ``frost_rh_pct``).

    Returns
    -------
    float
        Fraction of a full coil per second.
    """
    if p.frost_capacity_hpa_h > 0:
        return frost_driver_hpa(p, outside_c, hz, rh_pct) / (3600.0 * p.frost_capacity_hpa_h)
    if outside_c > p.defrost_max_outside_c:
        return 0.0
    return math.exp(p.defrost0 + p.defrost_o * outside_c) / 3600.0


def next_frequency(
    p: HeatPumpParams,
    hz: float,
    setpoint_c: float,
    outlet_c: float,
    dt: float,
    floor_hz: float | None = None,
) -> float:
    """Advance the compressor frequency over ``dt`` seconds of running.

    Parameters
    ----------
    p
        Parameters.
    hz
        Current frequency.
    setpoint_c, outlet_c
        Applied setpoint and current outlet temperature.
    dt
        Step in seconds.
    floor_hz
        Minimum frequency (defaults to ``hz_min``).

    Returns
    -------
    float
        Frequency after the step, within ``[floor_hz, hz_max]``.
    """
    error = setpoint_c + p.outlet_bias_k - outlet_c
    minutes = dt / 60.0
    if abs(error) <= p.hz_deadband_k:
        change = 0.0
    else:
        change = p.hz_gain * (error - math.copysign(p.hz_deadband_k, error)) * minutes
    change = min(max(change, -p.hz_rate_down * minutes), p.hz_rate_up * minutes)
    floor = p.hz_min if floor_hz is None else floor_hz
    return min(max(hz + change, floor), p.hz_max)
