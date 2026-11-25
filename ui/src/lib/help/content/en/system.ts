import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system',
  title: 'System',
  lead: 'Whether ovenbird is in control and whether its connections are healthy. Pause and resume automatic control here.',
  art: 'system',
  sections: [
    {
      id: 'mode',
      kind: 'see',
      title: 'Control mode',
      body: 'Three steps: **Off**, **Shadow** and **Auto**; the filled dot is the mode now. The lock marks the highest mode the installation allows.\n\nIn [[auto-mode|Auto]] ovenbird sends the water setpoint to the pump. In [[shadow|Shadow]] it reads and decides every minute but sends nothing. The sentence below the mode says [[control-state|who controls the pump]] right now, for example "ovenbird is waiting until 18:25" during a hold in Auto.',
      target: 'system.mode',
    },
    {
      id: 'pause',
      kind: 'do',
      title: 'Pause and resume',
      body: '**Pause** stops sending at once, for example while you work on the installation. It stays paused after a restart. **Resume** goes back to Auto after you confirm; only an administrator can resume.',
    },
    {
      id: 'health',
      kind: 'see',
      title: 'Health',
      body: 'One tile per part: [[mqtt|MQTT]], the message broker; [[heishamon|HeishaMon]], the board on the pump, with its last heartbeat; Home Assistant ([[ha-link]]); the history store; the alarms, showing the most serious one; and the weather forecast. Green is fine; **disabled** means it is not set up.\n\nBelow: the service version, its API version, and whether it is live and ready.',
      target: 'system.health',
    },
    {
      id: 'notifications',
      kind: 'see',
      title: 'Notifications',
      body: 'Whether alerts reach your phone when no page is open. **Alerts (ntfy)** sends a push message for warnings and critical alarms. The **watchdog ping** calls an outside service every few minutes; when the pings stop, that service warns you that ovenbird itself has stopped.\n\nPress **Send test** to check that a message arrives. Both are set up in the add-on options or the environment, not in Settings.',
      target: 'system.notifications',
    },
    {
      id: 'safety',
      kind: 'know',
      title: 'Safety net',
      body: "If ovenbird stops, a small [[envelope|envelope]] rule on the HeishaMon keeps the water temperature inside a safe band. ovenbird cannot see that rule, so it shows what it knows: **Not declared**, **Declared** (the installer says it is there) or **Proven** (the pump was seen being pulled back into the band without ovenbird). Below: the band now and ovenbird's own limits.",
      target: 'system.safety',
    },
    {
      id: 'about',
      kind: 'know',
      title: 'About this installation',
      body: "Version, the service's clock and time zone, how long it runs and how often it started. **More about this installation** lists the control loop, the connections and the setpoint register. **Download diagnostics** saves a bundle for an issue report, without passwords or tokens; only an administrator can download it.",
      target: 'system.about',
    },
    {
      id: 'live',
      kind: 'know',
      title: 'Going live',
      body: 'Auto is only possible when the installation allows it. The mode ceiling and the permission to send commands are installation settings; this page cannot switch them on. A new installation starts in Shadow, so you can watch its decisions first.',
    },
  ],
  questions: [
    {
      id: 'shadow-heat',
      q: 'Is the heating off in Shadow?',
      a: 'No. The pump keeps heating on its own settings, or on those of another controller. ovenbird only stops sending.',
    },
    {
      id: 'offline',
      q: 'HeishaMon is offline. What now?',
      a: 'ovenbird gets no fresh data from the pump and sends nothing. Check HeishaMon’s power and WiFi. The pump keeps running on its last settings.',
    },
    {
      id: 'ready',
      q: 'Ready says no. Is something broken?',
      a: 'The service runs, but not everything is fine: usually a critical alarm is active or a needed connection is down. See [Activity](#/activity) and the tiles above.',
    },
    {
      id: 'alerts',
      q: 'How do I know an alarm at night reaches me?',
      a: 'Look at **Notifications**: it should say the alerts work and the watchdog ping is healthy. Send a test after every change. Without notifications an alarm only shows on these pages.',
    },
  ],
  related: ['system/signals', 'system/shadow', 'system/trial', 'activity'],
};
