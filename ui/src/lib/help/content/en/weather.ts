import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'weather',
  title: 'Weather',
  lead: 'The outside temperature as the pump measures it, the weather forecast, and the water temperature the heating curve will ask for in the coming days.',
  art: 'weather',
  sections: [
    {
      id: 'now',
      kind: 'see',
      title: 'Now',
      body: '**Now … outside** is what the pump measures, in whole degrees. **filtered** is the smoothed value the [[heating-curve|heating curve]] actually uses (see [[filtered-outside|filtered outside temperature]]). **forecast** is what the [[forecast]] expects for this moment.\n\nOn the right: the forecast range for the next 48 hours, and the water temperature the curve would ask for over that time.',
      target: 'weather.now',
    },
    {
      id: 'chart',
      kind: 'see',
      title: 'Outside temperature and forecast',
      body: 'Left of **now** is the past: **Measured** (steps of a whole degree), **Filtered**, and dashed **Forecast −24 h**, what was predicted a day earlier. Right of now is the newest **Forecast**.\n\nThe panels below show **Curve water**, sun, cloud and wind on the same time line; nights are shaded. The source line names the provider and when the forecast was issued.',
      target: 'weather.chart',
    },
    {
      id: 'days',
      kind: 'see',
      title: 'Coming days',
      body: 'One card per day: the sky, the highest and lowest temperature, cloud, hours of sun, wind, and the **Curve water** range for that day. A star (*) marks a day of which only the remaining hours count.',
      target: 'weather.days',
    },
    {
      id: 'error',
      kind: 'see',
      title: 'Forecast error by lead time',
      body: 'How good the forecast has been here over the last 14 days, measured against what the pump saw. **6 h ahead** and **24 h ahead** are the [[lead-time|lead times]].\n\nThe bars show the [[mae|MAE]], the typical size of the error. **Bias** is the average error: +0.8 K means the forecast was on average 0.8 K too warm. **Forecasts** is how many hours were compared.',
      target: 'weather.error',
    },
    {
      id: 'display-only',
      kind: 'know',
      title: 'Does the forecast steer?',
      body: 'The forecast is for you to look at, with one exception: the [[model-plan|model plan]] (House → Control). In Shadow the plan computes with the forecast but changes nothing. On, which moves the room target a little ahead of sun or colder weather, is locked for now. Otherwise ovenbird controls on the measured outside temperature alone.\n\n**Curve water** is the heating curve alone, before [[room-feedback|room feedback]], limits and rounding, so the real setpoint can differ by a few degrees. ovenbird stores every forecast as it was issued, so its quality can be judged honestly.',
    },
    {
      id: 'privacy',
      kind: 'do',
      title: 'Switch the forecast on or off',
      body: 'The forecast is opt-in. While it is on, only your location rounded to about 1 km goes to the provider (Open-Meteo), once an hour. While it is off, nothing leaves the house.',
      steps: [
        'Open [Settings → Weather](#/settings/weather).',
        'Switch **Weather forecast** on or off and choose the location.',
        'Choose **Review and apply**, then **Apply**.',
      ],
    },
  ],
  questions: [
    {
      id: 'steps',
      q: 'Why does the measured temperature go up in steps?',
      a: 'The pump reports the outside temperature in whole degrees. That is why ovenbird smooths it: otherwise every jump of a degree would move the water setpoint.',
    },
    {
      id: 'filtered-lags',
      q: 'Why does the filtered line lag behind?',
      a: 'The filter averages over several hours on purpose. A house with a lot of mass reacts slowly to the weather, so the heating curve should too. A short sunny spell or a cold gust should not change the water temperature.',
    },
    {
      id: 'stale',
      q: 'What does "The forecast is out of date" mean?',
      a: 'No new forecast came in for more than 3 hours, for example because the internet was down. Heating carries on as normal, because control uses the measured outside temperature.',
    },
    {
      id: 'curve-differs',
      q: 'Curve water says 33 °C, but the setpoint is 31 °C. Who is right?',
      a: 'Both. Curve water is the starting point only. The [Setpoint](#/setpoint) page shows the corrections on top of it, such as room feedback when the room is already warm enough.',
    },
  ],
  related: ['settings/weather', 'settings/curve', 'setpoint', 'home'],
};
