import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'switching',
  title: 'Overstappen van een andere regeling',
  lead: 'Gebruikte je eerder een Node-RED-flow of een andere regeling voor je warmtepomp? Hier staat waar de gebruikelijke instellingen in ovenbird zitten, en wat ovenbird anders doet.',
  art: 'welcome',
  sections: [
    {
      id: 'mapping',
      kind: 'know',
      title: 'Waar je instellingen zitten',
      body: '- **WAR** (weersafhankelijke regeling) → [Stooklijn](#/settings/curve), met een eigen aan/uit-schakelaar\n- **RTC** (ruimtetemperatuurcorrectie) → ruimtecorrectie, bij [Comforttemperatuur](#/settings/room), los aan of uit te zetten\n- **SoftStart** → **Zachte start**, bij [Gedrag](#/settings/behaviour)\n- **HEAT_SP_lower_limit** → **Minimale aanvoertemperatuur**, bij [Gedrag](#/settings/behaviour)\n- **NightReduction** → nog geen nachtverlaging; [Stille modus](#/settings/quiet) gaat alleen over geluid\n- **Pompsnelheid** (pump duty) → [Pomp](#/settings/pump-duty)\n\nImporteren kan niet: vul je waarden met de hand in.',
    },
    {
      id: 'curve',
      kind: 'do',
      title: 'De stooklijn overnemen',
      body: 'WAR geeft een watertemperatuur bij een paar buitentemperaturen. Vul dezelfde punten in bij de [[heating-curve|stooklijn]], die 2 tot 6 punten aanneemt, en hetzelfde kamerdoel bij [Comforttemperatuur](#/settings/room).\n\nHet doel geldt voor de sensor die het meet. Las je vorige regeling een andere kamerwaarde dan de sensor die je hier kiest, dan kan hetzelfde getal net iets warmer of koeler aanvoelen.',
    },
    {
      id: 'night',
      kind: 'know',
      title: 'Nachtverlaging',
      body: 'ovenbird heeft vandaag geen nachtverlaging. [[quiet-mode|Stille modus]] maakt de buitenunit stiller in de tijdvakken die je instelt; hij verlaagt de temperatuur niet expres, al kan het huis met minder vermogen iets afkoelen. De kamer ’s nachts lager zetten is werk voor een planner die later komt.',
    },
    {
      id: 'different',
      kind: 'know',
      title: 'Wat ovenbird anders doet',
      body: '- Eén [[setpoint|aanvoertemperatuur]] uit benoemde delen, uitgelegd bij elke [[decision|beslissing]] op [Aanvoer](#/setpoint).\n- Een [[envelope|veiligheidsband]] waar geen aanvoertemperatuur uit kan.\n- Een [[dead-band|dode band]] en een [[dwell|wachttijd]], zodat hij niet bij elk klein verschil schrijft.\n- Elke opdracht wordt gecontroleerd tegen wat de pomp meldt.\n- Schrijft iemand anders, dan [[hold|wacht]] hij in plaats van te vechten.\n- [[wood-stove|Houtkachelmodus]] voor een kachel in de kamer van de sensor.',
    },
    {
      id: 'side-by-side',
      kind: 'do',
      title: 'Laat hem eerst naast Node-RED draaien',
      body: 'In [[shadow|Schaduw]] leest en beslist ovenbird elke minuut maar schrijft hij nooit, dus Node-RED houdt de regie. Node-RED is dan de verwachte schrijver: geen alarm, geen blokkade. Vergelijk **zou sturen** met **pomp heeft** op [Aanvoer](#/setpoint).\n\nLaat Node-RED stoppen met schrijven naar de pomp voordat ovenbird op Automatisch stuurt. Anders ziet ovenbird een [[foreign-writer|vreemde schrijver]] en wacht hij.',
    },
  ],
  questions: [
    {
      id: 'import',
      q: 'Kan ovenbird de instellingen van mijn vorige regeling importeren?',
      a: 'Nog niet. Vul je waarden met de hand in: de WAR-punten bij [Stooklijn](#/settings/curve), je kamerdoel bij [Comforttemperatuur](#/settings/room), de waarden voor de pompsnelheid bij [Pomp](#/settings/pump-duty).',
    },
    {
      id: 'both',
      q: 'Kunnen Node-RED en ovenbird de pomp allebei aansturen?',
      a: 'Nee, er mag er maar één schrijven. In Schaduw kijkt ovenbird alleen mee, dus Node-RED kan de regie houden. Op Automatisch [[hold|blokkeert]] ovenbird zijn opdrachten als hij een andere schrijver ziet; na drie blokkades binnen 12 uur wacht hij tot jij vrijgeeft bij [Blokkades](#/activity/holds).',
    },
    {
      id: 'timing',
      q: 'Mijn vorige regeling keek om de paar minuten. Schrijft ovenbird vaker?',
      a: 'ovenbird beslist elke minuut, maar stuurt alleen hele graden, alleen als de wijziging de dode band haalt en pas als de wachttijd voorbij is. De meeste minuten gaat er niets heen. Elke schrijfactie telt mee voor een dagbudget.',
    },
    {
      id: 'defrost-duty',
      q: 'Waarom stuurt ovenbird geen pompsnelheid tijdens het ontdooien?',
      a: 'Tijdens het ontdooien kiest de pomp haar eigen pompsnelheid en negeert ze de instelling. ovenbird stuurt dan niets en zet zijn waarde daarna weer.',
    },
  ],
  related: ['start', 'settings/curve', 'settings/room', 'settings/behaviour'],
  aliases: ['Node-RED', 'WAR', 'RTC', 'SoftStart', 'NightReduction', 'importeren'],
};
