import type { GlossaryEntry } from '$lib/help/types';

export const glossary: GlossaryEntry[] = [
  {
    id: 'heating-curve',
    term: 'Heating curve',
    short:
      'The rule that gives a water temperature for every outside temperature: the colder it is, the warmer the water.',
    body: 'Also called a weather-compensated curve, or WAR. It is the starting point of every setpoint; ovenbird adds corrections on top. You edit it under [Settings → Heating curve](#/settings/curve), with 2 to 6 points. Weather-dependent control can be switched off there; ovenbird then uses one fixed water temperature instead. Room correction is a separate switch.',
    related: ['setpoint', 'filtered-outside', 'room-feedback'],
    aliases: ['WAR', 'weather-compensated', 'stooklijn'],
  },
  {
    id: 'setpoint',
    term: 'Setpoint',
    short: 'The water temperature ovenbird asks the pump for, in whole degrees.',
    body: 'Also called the water target. ovenbird works it out every minute from the heating curve plus corrections, and sends it only when the change is worth it. The pump then decides by itself when to start and stop to reach it.',
    related: ['heating-curve', 'dead-band', 'dwell', 'decision'],
  },
  {
    id: 'outlet',
    term: 'Outlet',
    short: 'The temperature of the water leaving the heat pump towards your floor or radiators.',
    body: 'Also called the supply or flow temperature. The pump aims to bring the outlet to the setpoint.',
    related: ['inlet', 'delta-t', 'setpoint'],
  },
  {
    id: 'inlet',
    term: 'Inlet',
    short:
      'The temperature of the water coming back to the heat pump, after it has given off its heat.',
    body: 'Also called the return temperature.',
    related: ['outlet', 'delta-t'],
  },
  {
    id: 'delta-t',
    term: 'Delta-T (ΔT)',
    short:
      'The difference between outlet and inlet: how much the water cools on its way through the house.',
    body: 'In Delta-T flow mode the pump adjusts the flow to keep this difference near the **Heating delta-T** setting (3–10 K). A smaller delta-T means more flow. While the compressor is off, ΔT is close to zero.',
    related: ['outlet', 'inlet', 'flow', 'flow-mode'],
  },
  {
    id: 'flow',
    term: 'Flow',
    short: 'How much water circulates through the heating, in litres per minute.',
    body: 'Too little flow is a risk for the heat pump, so ovenbird raises an alarm when it drops too low while the compressor runs. Keep at least one heating loop always open.',
    related: ['delta-t', 'pump-duty'],
  },
  {
    id: 'cop',
    term: 'COP',
    short:
      'Heat delivered divided by electricity used. A COP of 4 means 4 kWh of heat for 1 kWh of electricity.',
    body: 'The COP is higher when it is milder outside and when the water does not need to be very warm. Defrosts and short runs pull it down. ovenbird calculates it from the pump’s own estimates of power and heat, so take it as a good indication rather than a meter reading.',
    related: ['defrost', 'short-cycling'],
  },
  {
    id: 'compressor',
    term: 'Compressor',
    short: 'The heart of the heat pump: it pumps heat from the outside air into the water.',
    body: 'Its speed is shown in Hz: higher means more heat and more electricity. When it stands still (0 Hz), the pump is idle.',
    related: ['short-cycling', 'cop'],
  },
  {
    id: 'defrost',
    term: 'Defrost',
    short:
      'A few minutes in which the pump melts ice off its outdoor unit, using heat from the water.',
    body: 'Ice forms in cold, damp weather. During a defrost the water cools for a moment and the pump drives its own circulation pump. ovenbird then freezes room feedback and does not lower the setpoint, so it does not over-react to the dip.\n\nFor a heat pump model it recognises (System → About this installation), ovenbird also names the **deice mode** the pump picks. **Mode 1** is a reverse cycle: the pump runs its refrigerant backwards and the water pump keeps running. **Mode 2** is a hot-gas defrost: the water pump stops by design, so the flow drops to zero and the defrost can last up to 30 minutes. The service manual has the pump pick mode 2 when the return water is cold: below 27 °C, or below 60 °C in frost below −10 °C.',
    related: ['pump-duty', 'cop', 'dhw'],
  },
  {
    id: 'dhw',
    term: 'Hot water',
    feature: 'hotWater',
    short: 'The pump heating the domestic hot-water tank instead of the house (DHW).',
    body: 'A valve then sends the warm water to the tank. ovenbird never controls hot water. While a run lasts it treats it like a defrost: room feedback is frozen and the setpoint is not lowered.',
    related: ['defrost'],
  },
  {
    id: 'pump-duty',
    term: 'Pump duty',
    short:
      'The speed of the circulation pump that moves water through the heating, as a number from the pump.',
    body: 'The **Maximum pump duty** setting caps it. ovenbird can keep one maximum while the compressor runs and a lower one while it is idle, to save electricity and noise (see [Settings → Pump](#/settings/pump-duty)). During a defrost the pump ignores the maximum, so ovenbird sends nothing then.',
    related: ['flow', 'defrost'],
  },
  {
    id: 'quiet-mode',
    term: 'Quiet mode',
    short: 'A pump mode that limits compressor and fan speed so the outdoor unit makes less noise.',
    body: 'It comes in levels 1 to 3; a higher level is quieter but also gives less heat. ovenbird can switch it on at set times, for example at night (see [Settings → Quiet mode](#/settings/quiet)). It is about noise, not a night setback such as Node-RED’s NightReduction: ovenbird has none yet.',
    related: ['compressor'],
    aliases: ['NightReduction', 'night reduction', 'night setback', 'whisper mode'],
  },
  {
    id: 'heating-off-temperature',
    term: 'Heating off above outdoor temperature',
    short:
      'Above this outdoor temperature the pump stops heating by itself, whatever ovenbird asks.',
    body: 'A summer switch inside the pump, settable from 10 to 35 °C on the [Pump](#/pump) page. ovenbird shows an info alarm while it is that warm outside. Set it too low and the house may stay cold on mild days.',
    related: ['setpoint'],
  },
  {
    id: 'flow-mode',
    term: 'Pump flow-rate mode',
    short:
      'How the pump chooses its flow: Delta-T keeps the set ΔT, Maximum flow always pumps as hard as it may.',
    body: 'Delta-T is the usual choice. Some older pump models ignore this setting.',
    related: ['delta-t', 'flow'],
  },
  {
    id: 'start-ramp',
    term: 'Start ramp',
    short:
      'After a compressor start, ovenbird holds the setpoint a little below the curve and lets it rise slowly.',
    body: 'Also called soft start. A pump that starts against a high setpoint runs hard, overshoots and may stop again soon. A gentle start gives longer, calmer runs. You can switch it off under [Settings → Behaviour](#/settings/behaviour).',
    related: ['short-cycling', 'setpoint'],
    aliases: ['SoftStart', 'soft start'],
  },
  {
    id: 'short-cycling',
    term: 'Short cycling',
    short: 'The compressor starting and stopping often, with short runs in between.',
    body: 'Every start costs efficiency and wear. ovenbird’s **Cycling protection** keeps the setpoint high enough early in a run, so the pump does not reach its own stop point too soon. Fewer, longer runs are better.',
    related: ['compressor', 'start-ramp'],
  },
  {
    id: 'dead-band',
    term: 'Dead band',
    short:
      'The smallest change worth sending: the setpoint only moves when the calculated value is at least this far away (1 K or more).',
    body: 'It stops the setpoint from jumping back and forth by a degree on small changes.',
    related: ['dwell', 'setpoint'],
  },
  {
    id: 'dwell',
    term: 'Wait time',
    short: 'The minimum time between two setpoint changes.',
    body: 'It keeps the pump calm and protects its daily number of writes. You set it under [Settings → Behaviour](#/settings/behaviour); a change that is due waits until the time has passed.',
    related: ['dead-band', 'setpoint'],
  },
  {
    id: 'filtered-outside',
    term: 'Filtered outside temperature',
    short:
      'The outside temperature smoothed over several hours. This is what the heating curve uses.',
    body: 'The pump reports the outside temperature in whole degrees and it can swing quickly. The house reacts slowly, so ovenbird smooths it first.',
    related: ['heating-curve'],
  },
  {
    id: 'forecast',
    term: 'Weather forecast',
    short:
      'The expected outside temperature, sun, cloud and wind for the coming days, from an online provider.',
    body: 'Opt-in: only your location, rounded to about 1 km, is sent. It is shown for your information; only the [[model-plan|model plan]] works with it, and until that is On it changes nothing in the control.',
    related: ['lead-time', 'forecast-bias', 'mae'],
  },
  {
    id: 'lead-time',
    term: 'Lead time',
    short:
      'How far ahead a forecast was made. A forecast for 18:00 issued at 12:00 has a lead time of 6 hours.',
    body: 'Forecasts get less accurate the further ahead they look, so their errors are judged per lead time.',
    related: ['forecast', 'mae'],
  },
  {
    id: 'forecast-bias',
    term: 'Bias',
    short:
      'The average forecast error. Positive means the forecast was on average too warm, negative too cold.',
    related: ['mae', 'lead-time'],
  },
  {
    id: 'mae',
    term: 'MAE',
    short:
      'Mean absolute error: how far off the forecast typically was, whether too warm or too cold.',
    body: 'An MAE of 1.4 K means the forecast was typically 1.4 degrees off.',
    related: ['forecast-bias', 'lead-time'],
  },
  {
    id: 'degree-hours',
    term: 'Degree-hours (K·h)',
    short:
      'How far and how long the room was below the comfort band: 1 K too cold for 2 hours is 2 K·h.',
    body: 'Zero means the room stayed comfortable all day.',
    related: ['comfort-band'],
  },
  {
    id: 'ua',
    term: 'Heat loss (UA)',
    short:
      'How many watts the house loses for every degree it is warmer inside than outside, in W/K.',
    body: 'A house with a UA of 300 W/K at 20 °C inside and 0 °C outside loses about 6 kW. ovenbird learns it from your own history; with one room sensor it is an **apparent** figure: ventilation and the other rooms are in it too. Shown with a range that combines resampling of the days and separate training periods, so it is the wide, honest one. Divided by the floor area it gives the [indicative insulation score](#/house).',
    related: ['balance-temperature', 'time-constant', 'energy-signature'],
    aliases: ['UA', 'heat loss coefficient', 'HLC', 'warmteverlies', 'insulation'],
  },
  {
    id: 'balance-temperature',
    term: 'Balance temperature',
    short:
      'The outside temperature above which the house needs no heating: sun, people and appliances keep it warm.',
    body: 'Below it the heat the pump must deliver grows with every degree it gets colder. ovenbird reads it from the [[energy-signature]]: where the line through the daily points reaches zero heat.',
    related: ['energy-signature', 'ua'],
    aliases: ['heating limit', 'stookgrens', 'base temperature'],
  },
  {
    id: 'time-constant',
    term: 'Time constant',
    short:
      'How slowly the house cools down: the hours it takes to lose about two thirds of a temperature difference without heating.',
    body: 'A heavy, well-insulated house has a long time constant (often 100 hours or more) for the house as a whole, while the floor alone reacts in an hour or so: a night without heating costs little. A light house cools fast. It is why ovenbird can lower the water temperature for a while without the room noticing at once.',
    related: ['ua'],
    aliases: ['tau', 'thermal mass', 'tijdconstante'],
  },
  {
    id: 'heat-capacity',
    term: 'Heat capacity',
    short:
      'How much heat the floor and the house store for every degree, and how fast each part reacts.',
    body: 'The house model is a chain of three parts: the **loop** (the water in the heating loop), the **emitter** (the floor and screed, fast) and the **building** (the whole house, slow). The heat pump warms the water, the water warms the floor, and the floor warms the house. The emitter reacts within hours, the building within days: that is why a house cools slowly and its [[time-constant]] is long. The [House page](#/house) shows the **total heat capacity** in kWh per K and both response times, for example "the floor responds in about 0.6 hours, the house in about 130 hours". In its picture the floor and the house together either store heat or give it back.',
    related: ['time-constant', 'ua'],
    aliases: ['thermal mass', 'storage', 'building mass', 'emitter', 'warmtecapaciteit'],
  },
  {
    id: 'energy-signature',
    term: 'Energy signature',
    short: "A chart of the heat the house needed per day against that day's outside temperature.",
    body: 'The colder the day, the more heat. The slope of the line through the points is the [[ua|heat loss]]; where it reaches zero is the [[balance-temperature]]. Sunny days sit below the line. Wood-stove days are left out.',
    related: ['ua', 'balance-temperature'],
    aliases: ['heat signature', 'energiesignatuur'],
  },
];
