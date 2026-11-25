import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system/data',
  title: 'System: data',
  lead: 'How large the history is, how long it is kept, and how to download it: a few signals as a spreadsheet, the journals, everything as one archive, or the yearly archive of frozen months.',
  art: 'system',
  sections: [
    {
      id: 'storage',
      kind: 'see',
      title: 'Storage',
      body: 'The size of the history database and of its backup copy, the free disk space, and the size to expect once every limited resolution is full at the current settings. Data kept forever keeps growing; the line below says by how much per year.\n\nThe table lists each resolution: raw samples as they arrived, the 1-minute, 15-minute and hourly averages, and the journal of decisions, commands and alarms. **Per day** is what a day of it costs on disk.',
      target: 'system/data.storage',
    },
    {
      id: 'retention',
      kind: 'do',
      title: 'How long data is kept',
      body: 'Each resolution has its own retention, in Settings under **Data**. Older raw samples are not lost: the averages keep the shape of every signal much longer. **Keep forever** removes the limit; any other retention is at least one day. A change takes effect within a minute, without a restart.',
      target: 'system/data.retention',
    },
    {
      id: 'presets',
      kind: 'do',
      title: 'Short, Standard, Long or Unlimited',
      body: 'Settings → Data offers four choices with the size the database reaches with each. **Short** keeps about a month of detail, **Standard** (the default) 90 days of 1-minute data, **Long** a year of detail, **Unlimited** everything. The 15-minute and hourly averages stay forever in all but Short. Values that match none of them show as **Custom**; the five fields under **Advanced** set each resolution on its own.',
    },
    {
      id: 'compact',
      kind: 'do',
      title: 'Free space now',
      body: 'After a shorter retention the database file keeps its size until it is rebuilt. **Free space now** rebuilds it between two writes; history writing waits a few seconds meanwhile. It needs free disk space of about twice the database. Only an administrator can start it.',
      target: 'system/data.compact',
    },
    {
      id: 'export',
      kind: 'do',
      title: 'Download series',
      body: 'Pick a range, the signals and a resolution. **Long** gives one row per value (with minimum and maximum for averages); **Wide** gives one row per time with a column per signal, handy for a spreadsheet. NDJSON suits scripts. The estimate shows the size before you download; there is no limit on the number of rows.',
      steps: [
        'Choose a range, or **Custom** for your own days.',
        'Tick the signals you need; the filter narrows the list.',
        'Choose resolution, layout and format, check the estimate and press **Download series**.',
      ],
      target: 'system/data.export',
    },
    {
      id: 'journals',
      kind: 'see',
      title: 'Journals',
      body: 'Every decision, command, alarm or weather forecast in the chosen range, in the chosen format. Unlike the Activity pages there is no 5,000-row limit.',
      target: 'system/data.journals',
    },
    {
      id: 'archive',
      kind: 'do',
      title: 'Full archive',
      body: 'A zip with a fresh copy of the whole history database, the configuration and a manifest that describes them. Open the database with any SQLite tool. Passwords and tokens are never included. Only an administrator can download it.',
      target: 'system/data.archive',
    },
    {
      id: 'yearly',
      kind: 'see',
      title: 'Yearly archive',
      body: 'Besides the live history, every finished month is frozen into a zip of its own in the data directory, in the installation’s time zone: the 1-minute, 15-minute and hourly averages, the decisions, commands, alarms, the forecasts and the configuration versions of that month. It does not depend on the retention, so a short retention still leaves every month in the archive. The month is copied every quarter of an hour and frozen six hours after it ends; a month the history no longer fully held shows the missing days. A full month takes about 30 MB.',
      target: 'system/data.yearly',
    },
    {
      id: 'yearly-switch',
      kind: 'do',
      title: 'Archive on or off',
      body: 'The switch on the card (or **Yearly archive** in Settings → Data) starts or stops freezing new months. Months already stored stay until you delete them. Switching needs the admin login. When switched on again, the archive first catches up on the months the history still holds.',
      target: 'system/data.yearly-switch',
    },
    {
      id: 'yearly-download',
      kind: 'do',
      title: 'Download a year or a heating season',
      body: 'Choose **Calendar year** or **Heating season** (August to July) and download: one zip with the frozen months and a manifest that says which months it holds. A year that is not over yet, or one the archive started in, is marked partial with its months. The current month joins once it is frozen; download it on its own from the list of months. Downloads need the admin login.',
      target: 'system/data.yearly-download',
    },
    {
      id: 'yearly-months',
      kind: 'do',
      title: 'Single months and deleting',
      body: 'Each month shows on how many days it holds data and its size. **Delete** removes a frozen month for good after you confirm, and that month is not archived again; on a calendar year it removes all its frozen months. The live history is not touched. Deleting needs the admin login.',
      target: 'system/data.yearly-months',
    },
    {
      id: 'privacy',
      kind: 'know',
      title: 'Your data says when you are home',
      body: 'Room temperatures, hot water and the pump show when the house is lived in, heated or empty, and the signal names include your Home Assistant entities. Share exports only with people you trust.',
      without: {
        hotWater: {
          body: 'Room temperatures and the pump show when the house is lived in, heated or empty, and the signal names include your Home Assistant entities. Share exports only with people you trust.',
        },
      },
    },
  ],
  related: ['system', 'settings'],
};
