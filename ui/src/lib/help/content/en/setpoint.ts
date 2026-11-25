import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'setpoint',
  title: 'Setpoint',
  lead: 'Every minute ovenbird works out one number: the water temperature for the pump. This page shows how that number was built, and what would change it.',
  art: 'setpoint',
  sections: [
    {
      id: 'now',
      kind: 'see',
      title: 'Now',
      body: 'The big number is the water [[setpoint]] of the latest [[decision]], with the reason in one word and one plain sentence. Coloured lines below it mention anything special: a [[defrost]], a [[dhw|hot-water run]] or [[wood-stove|wood-stove mode]]. In wood-stove mode the reason reads **Wood stove**, room correction pauses with its integrator held for afterwards, and a line says in plain words when the detection waits.\n\nThe chips at the top show the [[config-version|configuration version]] and the time of the decision.',
      without: {
        hotWater: {
          body: 'The big number is the water [[setpoint]] of the latest [[decision]], with the reason in one word and one plain sentence. Coloured lines below it mention anything special: a [[defrost]], the pump being busy elsewhere or [[wood-stove|wood-stove mode]]. In wood-stove mode the reason reads **Wood stove**, room correction pauses with its integrator held for afterwards, and a line says in plain words when the detection waits.\n\nThe chips at the top show the [[config-version|configuration version]] and the time of the decision.',
        },
      },
      target: 'setpoint.now',
    },
    {
      id: 'waterfall',
      kind: 'see',
      title: 'How the setpoint is built',
      body: 'Read it from top to bottom, on one °C scale:\n\n- **Heating curve**: the start, from the outside temperature.\n- Each correction, such as [[room-feedback|Room feedback]], [[start-ramp|Start ramp]] or **Wood stove**, up or down.\n- **Safety limits**: the allowed range, so the water never gets too hot or too cold.\n- **Rounding, dead band, wait time**: whether the change is worth sending yet.\n- **Water setpoint**: the whole degree sent, and **Pump has**: what the pump reports back. When nothing was sent (Shadow, a pause or a hold) the row reads **Would send**.',
      target: 'setpoint.waterfall',
    },
    {
      id: 'change',
      kind: 'see',
      title: 'What would change it',
      body: 'The scale shows how far the room (or the outside temperature) has to move before the setpoint changes, and to what. The green zone is where it stays the same; the dashed mark is the room target.\n\n**Room sensor** shows the value ovenbird uses, how old it is, and whether a second sensor agrees. If the sensor cannot be trusted, ovenbird falls back to the heating curve alone.',
      target: 'setpoint.change',
    },
    {
      id: 'details',
      kind: 'see',
      title: 'Controller state, inputs and commands',
      body: 'Three folded blocks for when you want the full picture:\n\n- **Controller state**: each step of the calculation, the integrator of room feedback, the start ramp and the remaining wait time.\n- **Inputs used**: every measurement with its value and age.\n- **What went to the pump**: what the decision wanted, what the pump had, and what was actually sent.',
      target: 'setpoint.details',
    },
    {
      id: 'history',
      kind: 'do',
      title: 'Look back in time',
      body: 'The water panel stacks every correction on the heating curve; the thick line is the setpoint that was sent, the green band the allowed range. Below it the room, and a lane with the reason per moment.',
      steps: [
        'Pick **6 h**, **24 h** or **7 d**.',
        'Click or tap the chart: the cards above now show that moment.',
        'Choose **Back to now** to return.',
      ],
      target: 'setpoint.history',
    },
    {
      id: 'episodes',
      kind: 'do',
      title: 'What happened',
      body: 'A table of what ovenbird did, newest first. **Episodes** merges minutes with the same reason into one row, so a compressor start or a [[hold]] is one line. **Every decision** lists the minutes one by one.\n\nOpen a row to see that moment in the cards above.',
      target: 'setpoint.episodes',
    },
    {
      id: 'calm',
      kind: 'know',
      title: 'Why the setpoint moves so little',
      body: 'ovenbird changes the setpoint on purpose rarely and in whole degrees. A change is only sent when the calculated value is at least the [[dead-band|dead band]] away (1 K or more), and not sooner than the [[dwell|wait time]] after the previous change.\n\nThat keeps the pump calm: fewer starts and stops, and fewer writes to its memory. A floor or radiators react slowly anyway, so a few minutes of waiting cost nothing.',
    },
  ],
  questions: [
    {
      id: 'below-curve',
      q: 'Why is the setpoint below the heating curve right after a start?',
      a: 'That is the [[start-ramp|start ramp]]. After the compressor starts, ovenbird keeps the water a little below the curve and releases it slowly. The pump then warms up gently instead of overshooting and stopping again.',
    },
    {
      id: 'defrost',
      q: 'What happens during a defrost or a hot-water run?',
      without: {
        hotWater: { q: 'What happens during a defrost, or while the pump is busy elsewhere?' },
      },
      a: 'The pump is busy with something else, so the room does not react as usual. ovenbird freezes room feedback and never lowers the setpoint meanwhile, so it does not over-react to the dip. Afterwards it continues where it was.',
    },
    {
      id: 'room-cold',
      q: 'The room got colder, but the setpoint did not change. Why?',
      a: 'Look at **What would change it**: the room may still be inside the zone where the setpoint stays the same, or a change is due but the wait time holds it. Room feedback also builds up slowly on purpose, because a house takes hours to warm up.',
    },
    {
      id: 'plan',
      q: 'What is "Plan" in the list of contributions?',
      a: 'A place for a future planner that could preheat before a cold night or cheap hours. It is not active yet, so it always adds nothing.',
    },
    {
      id: 'nothing-sent',
      q: 'Why does a row say "nothing sent"?',
      a: 'ovenbird decided but did not write to the pump, for example because [[heishamon|HeishaMon]] was not answering, a [[hold]] was active or it runs in [[shadow|Shadow]]. The pump then keeps the last value it had.',
    },
  ],
  related: ['home', 'settings/curve', 'settings/room', 'settings/behaviour', 'activity'],
};
