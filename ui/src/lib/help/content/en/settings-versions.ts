import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/versions',
  title: 'Versions and backup',
  lead: 'Every applied change becomes a numbered version. Here you see who changed what, go back to an earlier version, and save or load your settings as a file.',
  art: 'settings',
  sections: [
    {
      id: 'list',
      kind: 'see',
      title: 'Versions',
      body: 'Newest first. Each [[config-version|version]] shows its number, when and by whom, where it came from (web UI, rollback or seed file) and its comment. Open the line below it to see what changed, from old to new. **current** marks the version in use.',
      target: 'settings/versions.list',
    },
    {
      id: 'rollback',
      kind: 'do',
      title: 'Go back to a version',
      body: '**Roll back to this version** saves a new version with that version’s settings, after the same checks as any change. Settings fixed by the installation stay as they are.\n\n**Load as draft** puts those settings in your [[draft]] instead, so you can adjust them before you review and apply.',
    },
    {
      id: 'export',
      kind: 'do',
      title: 'Export and import',
      body: '**Export settings** downloads your stored settings as a file: a backup, or a way to move them to another installation. **Import from file…** only fills your draft; nothing changes until you review and apply. Locked and unknown settings in the file are skipped.',
      target: 'settings/versions.export',
    },
    {
      id: 'locked',
      kind: 'see',
      title: 'Settings from the installation',
      body: '**Set by environment or options file** lists settings you could edit here but that the installation overrides; change them where the **Variable** column says. **Fixed by installation** holds the rest: connections, safety thresholds and other values this page never changes.',
      target: 'settings/versions.locked',
    },
    {
      id: 'kept',
      kind: 'know',
      title: 'History is kept',
      body: 'Versions are never edited or deleted; a rollback adds a new one. The [Audit](#/activity/audit) tab records who applied, rolled back or acknowledged what.',
    },
  ],
  questions: [
    {
      id: 'when',
      q: 'Does a rollback take effect immediately?',
      a: 'At the next decision, within about a minute. From there the water temperature moves in its normal steps.',
    },
    {
      id: 'file',
      q: 'What is in the export file?',
      a: 'Your stored values, plus the value in effect of every setting for reference. No passwords or tokens.',
    },
    {
      id: 'no-button',
      q: 'Why can I not roll back?',
      a: 'Only an administrator can, and the current version has no buttons. If the settings are already the same, the dialog says so.',
    },
  ],
  related: ['settings', 'activity/audit'],
};
