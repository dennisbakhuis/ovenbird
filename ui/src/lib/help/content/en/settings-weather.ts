import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/weather',
  title: 'Weather',
  lead: 'Switch on the outside temperature forecast and choose the place it is for. It feeds the Weather page and the curve chart; it does not steer the heating.',
  art: 'settings',
  sections: [
    {
      id: 'privacy',
      kind: 'know',
      title: 'Your location leaves the house',
      body: 'The forecast comes from Open-Meteo. The service fetches it, not your browser, and sends your location rounded to 0.01°, about 1 km. Nothing is sent until you switch the forecast on.',
      target: 'settings/weather.privacy',
    },
    {
      id: 'enable',
      kind: 'do',
      title: 'Weather forecast',
      body: 'Switch it on to see the [[forecast]] on the [Weather](#/weather) page and as a blue bar on the heating curve chart. Only the [[model-plan|model plan]] works with it, and until that is On it changes nothing in the control.',
      target: 'settings/weather.enable',
    },
    {
      id: 'location',
      kind: 'do',
      title: 'Location',
      body: '**From Home Assistant (zone.home)** uses your home zone, so you enter nothing. **Enter a location myself** shows fields for latitude and longitude. **Use my location** asks this browser for its position and fills them in; it only appears where the browser allows that.\n\nThe line at the bottom shows which source is in use.',
      target: 'settings/weather.location',
    },
    {
      id: 'off',
      kind: 'know',
      title: 'Switching it off',
      body: 'Switch **Weather forecast** off and apply. The service stops fetching, and the forecast disappears from the Weather page and the curve chart.',
    },
  ],
  questions: [
    {
      id: 'heating',
      q: 'Does the forecast change my heating?',
      a: 'No, not in this version. ovenbird heats on the measured outside temperature. The forecast lets you see what is coming and how well it was forecast before.',
    },
    {
      id: 'no-button',
      q: 'Why is there no “Use my location” button?',
      a: 'Browsers only share a position over a secure (https) connection. Enter the coordinates yourself instead; two decimals are enough.',
    },
  ],
  related: ['weather', 'settings/curve'],
};
