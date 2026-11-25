import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/room',
  title: 'Comfort temperature',
  lead: 'Set the room temperature you want and choose the sensor that measures it. Room correction then nudges the water temperature up or down to get there.',
  art: 'settings',
  sections: [
    {
      id: 'comfort',
      kind: 'do',
      title: 'Comfort target',
      body: 'The room temperature ovenbird aims for, 21 °C unless you change it. Use − and + to move it in steps of 0.1 °C.\n\nNext to it you see the room now on a bar; the green part is the [[comfort-band]]. Between 18 and 24 °C is the usual range; outside it you confirm the change in the review.',
      target: 'settings/room.comfort',
    },
    {
      id: 'sensor',
      kind: 'do',
      title: 'Room sensor',
      body: 'Pick the thermometer in the room that matters most, usually the living room. The list shows sensors from Home Assistant and the pump, with their value now.\n\nWithout a sensor ovenbird runs on the heating curve alone, without room correction.',
      target: 'settings/room.sensor',
    },
    {
      id: 'status',
      kind: 'see',
      title: 'How ovenbird sees the sensor',
      body: '- **Sensor fresh** or **Sensor stale**: whether the value is trusted ([[stale]]).\n- **held**: how long the value has not changed.\n- **alive by**: another signal from the same device that shows it still works.\n- **Authority**: how much the room may still lower the water temperature.\n- **plausible**: whether the cross-check sensor agrees.\n\nChips only appear when they apply.',
      target: 'settings/room.status',
    },
    {
      id: 'behaviour',
      kind: 'know',
      title: 'Sensor behaviour',
      body: 'Tell ovenbird how your [[room-sensor]] reports. **Periodic** sensors report on a schedule: set the **Report interval**. **On change** sensors, like many battery Zigbee sensors, only report when the value moves by the **Sensor step size**, so silence is normal.\n\n**Liveness signals**, such as the humidity of the same device, prove it is alive. A **Cross-check sensor** must roughly agree, or room correction pauses.',
      target: 'settings/room.behaviour',
    },
    {
      id: 'correction',
      kind: 'know',
      title: 'Comfort temperature',
      body: 'With **Room correction** on, ovenbird compares the room with the target and raises or lowers the water temperature, by 3 K at most by default ([[room-feedback|how it works]]). Off means the curve alone.\n\n**More: Room correction** holds the tuning: how strongly and how quickly it reacts, and its limits. The emitter preset sets good values; change them only if the room keeps swinging or stays off target for days.',
      target: 'settings/room.correction',
    },
    {
      id: 'monitor',
      kind: 'know',
      title: 'Room monitor',
      body: 'Raises a warning when the room stays too cold: by default 1.5 K below the target for 30 minutes. Leave the margin empty to switch the monitor off. It only warns; it does not change the heating.',
      target: 'settings/room.monitor',
    },
  ],
  questions: [
    {
      id: 'silent',
      q: 'What happens when the sensor stops reporting?',
      a: 'ovenbird stops correcting and runs on the curve. A warming correction it had built up stays and fades out over 24 hours, so the house does not suddenly cool. An [alarm](#/activity) says what happened.',
    },
    {
      id: 'on-change',
      q: 'My sensor only reports when the temperature changes. Is that a problem?',
      a: 'No. Choose **On change** under **Sensor behaviour** and add a liveness signal from the same device. ovenbird then holds the last value while the device is alive, up to the **Silence limit** (24 hours by default). The longer a value is held, the less it may cool the water, so a dead sensor cannot leave the house cold.',
    },
    {
      id: 'raise',
      q: 'Is it safe to raise the comfort target?',
      a: 'Yes. The water still stays within the curve’s limits and the maximum supply temperature. The room responds slowly, especially with floor heating: give it a few hours to a day.',
    },
    {
      id: 'stove',
      q: 'A wood stove makes this room hot and the rest of the house cold. What helps?',
      a: 'Switch on [[wood-stove|wood-stove mode]] under [Wood stove](#/settings/stove). ovenbird then lowers the heating curve by a fixed amount while the stove burns, instead of letting room correction cut the water temperature for the whole house.',
    },
  ],
  related: ['settings/curve', 'settings/stove', 'activity', 'system/signals'],
};
