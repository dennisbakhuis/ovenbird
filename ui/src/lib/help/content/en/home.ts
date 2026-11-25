import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'home',
  title: 'Home',
  lead: 'How warm the house is, what the heat pump is doing right now, and why ovenbird asks for the water temperature it does.',
  art: 'home',
  sections: [
    {
      id: 'verdict',
      kind: 'see',
      title: 'At a glance',
      body: 'One line sums up the house: **The house is at temperature**, **Warming up**, **Warmer than the target**, **Needs attention: …**, **Wood stove burning, heating backed off** or **No room temperature**. It follows the [[alarm|alarms]] (warning or critical), a [[hold]], whether ovenbird sends, the trust in the room value and [[wood-stove|wood-stove mode]]. [Activity](#/activity) lists the alarms and holds.\n\nBelow it, from the [[forecast|weather forecast]]: "Tonight: down to −1 °C outside. Heating continues." Without the forecast that line is left out.',
      target: 'home.verdict',
    },
    {
      id: 'room',
      kind: 'see',
      title: 'Room temperature',
      body: 'The big number is the room as your [[room-sensor|room sensor]] measures it, with a trend arrow; the bar shows the [[comfort-band|comfort band]]. The line below says how much ovenbird trusts the value ([[cooling-authority|trust in the room value]]).\n\n**Target 21.0 °C** is a button: it opens **Comfort temperature**, with − and + in steps of 0.1 °C. **Save** shows a one-sentence review (more under **Details**), then **Apply**. With wood-stove mode on, **Stove on…** offers 2 h, 4 h or 8 h.',
      target: 'home.room',
    },
    {
      id: 'pump',
      kind: 'see',
      title: 'Heat pump',
      body: 'The label top right is the pump state: Heating, Idle, Defrosting, Hot water, Off or HeishaMon offline, with the [[compressor]] speed in Hz and a moon when [[quiet-mode|quiet mode]] is on.\n\nBelow it: electricity in, heat out and the [[cop|COP]], then the water: [[inlet]] → [[outlet]], [[delta-t|ΔT]] and [[flow]]. **Water setpoint** is what ovenbird sent. When it is not sending ([[control-state|who controls the pump]]) the line shows **Would send** next to **Pump has** instead. Tap **why?** to see how it was built.',
      without: {
        hotWater: {
          body: 'The label top right is the pump state: Heating, Idle, Defrosting, Pump busy elsewhere, Off or HeishaMon offline, with the [[compressor]] speed in Hz and a moon when [[quiet-mode|quiet mode]] is on.\n\nBelow it: electricity in, heat out and the [[cop|COP]], then the water: [[inlet]] → [[outlet]], [[delta-t|ΔT]] and [[flow]]. **Water setpoint** is what ovenbird sent. When it is not sending ([[control-state|who controls the pump]]) the line shows **Would send** next to **Pump has** instead. Tap **why?** to see how it was built.',
        },
      },
      target: 'home.pump',
    },
    {
      id: 'why',
      kind: 'see',
      title: 'Why this setpoint',
      body: 'A short version of the [[setpoint]] calculation: the [[heating-curve|heating curve]] for the current outside temperature, every correction on top of it, and the whole degree that was sent. Rows that add nothing are left out.\n\nIt sits folded inside the Heat pump card, on a phone and on a wide screen alike; open it to see the rows. **Setpoint details** opens the full story on the [Setpoint](#/setpoint) page.',
      target: 'home.why',
    },
    {
      id: 'day',
      kind: 'see',
      title: 'Pump, last 24 hours',
      body: 'Four lanes show when the compressor ran (darker means faster), when the pump [[defrost|defrosted]], when it made [[dhw|hot water]] and when quiet mode was on.\n\nA healthy day has a few long runs rather than many short ones: every start costs efficiency and wear (see [[short-cycling|short cycling]]). **Show as list** gives the same as text.',
      without: {
        hotWater: {
          body: 'Three lanes show when the compressor ran (darker means faster), when the pump [[defrost|defrosted]] and when quiet mode was on. When the pump was busy elsewhere, a lane for that shows too.\n\nA healthy day has a few long runs rather than many short ones: every start costs efficiency and wear (see [[short-cycling|short cycling]]). **Show as list** gives the same as text.',
        },
      },
      target: 'home.day',
    },
    {
      id: 'chart',
      kind: 'see',
      title: 'Temperatures',
      body: 'Three panels on one time line: the room against its comfort band, the water (setpoint, outlet and inlet) and the outside temperature. Each has its own scale, so small room changes stay visible next to big water swings.\n\nPick **6 h**, **24 h** or **7 d** at the top. Move over the chart to read a moment, or use **Show as table**.',
      target: 'home.chart',
    },
    {
      id: 'tiles',
      kind: 'see',
      title: 'Today and this week',
      body: '**Energy today** is the electricity used since midnight, with the heat delivered below it. **COP today** is heat divided by electricity. **Starts today** counts compressor starts, with defrosts and the average run. **Next 24 h** shows the forecast range and opens [Weather](#/weather).\n\n"Today" starts at midnight in the service’s time zone, the same day as the daily figures on [Pump](#/pump); a line under the tiles names that zone when it is not yours. **This week** adds up the last 7 days.',
      target: 'home.tiles',
    },
  ],
  questions: [
    {
      id: 'reports-differ',
      q: 'Why does "Pump has" show a different number than ovenbird’s value?',
      a: 'ovenbird sends a whole degree and then checks what the pump reports back. For a minute or two after a change the two can differ while the command travels through [[heishamon|HeishaMon]]. While ovenbird does not send (Shadow, a pause or a hold) they can differ for longer: the pump keeps its own value.',
    },
    {
      id: 'idle-cold',
      q: 'The room is below target, so why is the pump idle?',
      a: 'ovenbird sets the water temperature; the pump itself decides when to start and stop, based on how far the water is from that setpoint. A floor or radiators full of warm water keep heating for a while, so an idle spell is normal and saves starts. If the room stays low, [[room-feedback|room feedback]] raises the setpoint step by step.',
    },
    {
      id: 'incomplete',
      q: 'What does "Incomplete data" under Energy today mean?',
      a: 'Less than 80 % of today has recorded values, for example after a restart or a HeishaMon gap. The figures are what was measured, so energy and COP may be too low or off.',
    },
    {
      id: 'no-forecast',
      q: 'Why is there no Next 24 h tile?',
      a: 'The weather forecast is off. It is opt-in, because it sends your rounded location to a weather service. You can switch it on under [Settings → Weather](#/settings/weather).',
    },
    {
      id: 'stove-banner',
      q: 'What does "Wood stove: heating backed off by 3 K" mean?',
      a: '[[wood-stove|Wood-stove mode]] is on: a stove warms the room with the sensor, so ovenbird lowers the heating curve by 3 K instead of cooling every room. The second line says whether a reference room watches the rest of the house. While ovenbird only watches, is paused or waits, the banner says what it would do and that nothing is sent. **Stop** ends it; automatic detection then waits until the room has cooled. See [Wood stove](#/settings/stove).',
    },
  ],
  related: ['setpoint', 'pump', 'weather', 'activity'],
};
