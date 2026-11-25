"""Reference plant: a generic example house with a 5 kW air-to-water heat pump.

Every synthetic run (the harness scenarios, the fault sweep, the drills, the golden
streams, the committed capture slice) uses these values. They describe no real house:
they are textbook values for a typical mid-size Dutch house, chosen so that anyone can
run the simulator without local data. A fitted model of an actual install is loaded
instead with ``--params`` or, for the command lines, :data:`PLANT_ENV`
(see :func:`plant_from_environment`).

Building (three-node network of :mod:`ovenbird_sim.model.building`)
    A semi-detached house of about 130 m² usable floor area on two storeys, insulated
    to the Dutch building code of the 2000s (Rc about 3.5 m²K/W for floor, walls and
    roof, so U about 0.27 W/m²K; HR++ glazing with frames, U about 1.6 W/m²K).

    =========================================  ==========
    Envelope part                              W/K
    =========================================  ==========
    ground floor 65 m², U 0.29, ground factor 0.6     11
    roof 75 m², U 0.27                                20
    walls 100 m² net, U 0.27                          27
    windows and doors 30 m², U 1.6                    48
    thermal bridges (about 5 %)                        6
    ventilation, 100 m³/h exhaust at 0.34 Wh/m³K      33
    total ``h_air_out``                              145
    =========================================  ==========

    That is a design heat loss of about 4.4 kW at -10 °C outside and 20 °C inside,
    within the 5 kW pump's rating. Heat capacity follows the "medium" class of EN ISO
    13790 (about 165 kJ/m²K of floor area, brick and concrete), about 26 MJ/K, so the
    time constant ``C / H`` is about 50 h. Mixed heating: underfloor heating in a
    45 m² living room and kitchen (50 mm screed, about 4.5 MJ/K; pipe to screed about
    12 W/m²K, floor surface to room about 10 W/m²K after EN 1264) and radiators
    upstairs (about 40 W/K near the low supply temperatures used here); about 120 l of
    loop water. Internal gains 2.5 W/m² (EN ISO 13790 residential), peaking in the
    evening; a winter solar aperture of 3.5 m² on global horizontal irradiance.
Heat pump (:mod:`ovenbird_sim.model.heatpump`)
    A 5 kW monobloc after the public Panasonic Aquarea J-generation data
    (WH-MDC05J3E5): 5.0 kW at A7/W35 with COP 5.08 and 5.0 kW at A-7/W35 with COP
    2.78. The capacity map gives 100 W/Hz at 7 °C and 74 W/Hz at -7 °C, so about
    5 kW near 50 Hz at 7 °C and at the 68 Hz maximum at -7 °C, and about 1.8 kW at
    the 18 Hz minimum (a minimum modulation of roughly a third of the rating, typical
    of this class). The log-COP map hits both rated points with a textbook 2.5 % per
    kelvin of supply temperature. Flow is the nominal 5 K spread at 5 kW (about
    14 l/min); defrosts last 5 min, about once per running hour near -4 °C. Switching
    and modulation are generic inverter behaviour: start a few kelvin below the
    setpoint, stop 1.5 K above it for 2 min, at least 5 min off.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from ovenbird_sim.model import BuildingParams, HeatPumpParams, PlantParams

PLANT_ENV: Final = "OVENBIRD_REFERENCE_PLANT"

REFERENCE_HEAT_PUMP: Final = HeatPumpParams(
    start_trigger_margin_k=3.0,
    start_steady_margin_k=5.0,
    start_steady_delay_s=600.0,
    min_off_s=300.0,
    stop_margin_k=1.5,
    stop_delay_s=120.0,
    outlet_bias_k=0.0,
    hz_start=30.0,
    start_phase_s=180.0,
    hz_resume0=40.0,
    hz_resume_o=-0.6,
    hz_gain=1.5,
    hz_deadband_k=0.4,
    hz_rate_down=2.0,
    hz_rate_up=8.0,
    hz_min=18.0,
    hz_max=68.0,
    hz_min_cold=24.0,
    cold_floor_outside_c=2.0,
    k0=87.0,
    k_o=1.9,
    k_s=0.0,
    cop0=2.55,
    cop_o=0.035,
    cop_s=-0.025,
    cop_h=-0.006,
    flow_running_lpm=14.5,
    flow_idle_lpm=10.0,
    circulation_w=25.0,
    defrost0=-0.5,
    defrost_o=-0.12,
    defrost_max_outside_c=5.0,
    defrost_duration_s=300.0,
    defrost_heat_w=-3000.0,
    defrost_elec_w=800.0,
    spread_offset_k=0.0,
    outside_bias_running_k=-1.0,
    return_delay_s=180.0,
)

REFERENCE_BUILDING: Final = BuildingParams(
    c_water=5.0e5,
    c_mass=4.5e6,
    c_air=2.1e7,
    h_water_mass=540.0,
    h_water_air=40.0,
    h_mass_air=450.0,
    h_air_out=145.0,
    solar_aperture_m2=3.5,
    solar_mass_fraction=0.3,
    q_int_w=325.0,
    q_int_modulation=0.4,
    q_int_peak_hour=19.0,
)

REFERENCE_PARAMS: Final = PlantParams(REFERENCE_HEAT_PUMP, REFERENCE_BUILDING)


def plant_from_environment() -> Path | None:
    """Return the parameter file named by :data:`PLANT_ENV`, or ``None`` when unset or empty."""
    configured = os.environ.get(PLANT_ENV, "").strip()
    return Path(configured) if configured else None
