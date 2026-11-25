import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/pump-duty',
  title: 'Pomp',
  lead: 'Welke delen van de pomp de app toont, en hoe hard de waterpomp in je warmtepomp mag draaien. ovenbird kan het vermogen hoger zetten tijdens verwarmen en lager als de compressor rust.',
  art: 'settings',
  aliases: ['tapwater', 'warm water', 'boiler', 'pompvermogen'],
  sections: [
    {
      id: 'hot-water',
      kind: 'do',
      title: 'Tapwater',
      body: '**Tapwater** bepaalt of de app laat zien dat de pomp een tapwaterboiler opwarmt. **Automatisch (zoals de pomp meldt)** volgt wat de pomp over haar boiler zegt, zoals de regel onder de instelling vertelt; **Tonen** en **Verbergen** beslissen zelf.\n\nVerborgen verdwijnt tapwater uit de dagbanen, de signalen en deze hulp. Een run die toch gebeurt, staat er als **Pomp elders bezig**, en ovenbird verlaagt de aanvoertemperatuur in die tijd niet, zoals altijd. De instelling verandert niets aan hoe ovenbird de pomp regelt.',
      target: 'settings/pump-duty.hot-water',
    },
    {
      id: 'reported',
      kind: 'see',
      title: 'Wat de pomp meldt',
      body: '**Max** is het maximale [[pump-duty|pompvermogen]] dat de pomp nu heeft. **Nu** is het vermogen waarop hij werkelijk draait. **Bereik** is de band die ovenbird ooit mag sturen; de installatie legt die vast, vandaar het slotje.',
      target: 'settings/pump-duty.reported',
    },
    {
      id: 'settings',
      kind: 'do',
      title: 'De instellingen',
      body: '**Pompvermogen regelen** laat ovenbird het maximale vermogen instellen. **Vermogen tijdens verwarmen** geldt zolang de [[compressor]] draait en tijdens het verwarmen van tapwater. **Vermogen in rust** geldt zodra de compressor uit is geweest voor de **Vertraging voor rustvermogen**, standaard 5 minuten.\n\nHet rustvermogen mag niet hoger zijn dan het vermogen tijdens verwarmen, en beide moeten binnen het bereik liggen.',
      without: {
        hotWater: {
          body: '**Pompvermogen regelen** laat ovenbird het maximale vermogen instellen. **Vermogen tijdens verwarmen** geldt zolang de [[compressor]] draait. **Vermogen in rust** geldt zodra de compressor uit is geweest voor de **Vertraging voor rustvermogen**, standaard 5 minuten.\n\nHet rustvermogen mag niet hoger zijn dan het vermogen tijdens verwarmen, en beide moeten binnen het bereik liggen.',
        },
      },
      target: 'settings/pump-duty.settings',
    },
    {
      id: 'defrost',
      kind: 'know',
      title: 'Tijdens het ontdooien',
      body: 'Tijdens het [[defrost|ontdooien]] regelt de pomp zijn eigen vermogen en negeert hij de instelling. ovenbird stuurt dan niets voor het pompvermogen en zet zijn waarde terug zodra het ontdooien klaar is. [Opdrachten](#/activity/commands) toont zo’n opdracht als niet verstuurd.',
    },
    {
      id: 'safe',
      kind: 'know',
      title: 'Veilige waarden',
      body: 'ovenbird zet de pomp nooit stil: in rust blijft het water rondgaan. Een te laag vermogen tijdens verwarmen geeft te weinig [[flow|debiet]]; de bewaking op laag debiet geeft een kritiek alarm als het debiet onder het minimum zakt terwijl de compressor draait.\n\nZet **Pompvermogen regelen** uit om het vermogen aan de pomp zelf over te laten.',
    },
  ],
  questions: [
    {
      id: 'units',
      q: 'Wat betekenen de getallen?',
      a: 'Het is de eigen schaal van de pomp zoals HeishaMon die meldt, geen procenten of liters. Vergelijk ze met **Nu** en met het debiet op de pagina [Pomp](#/pump).',
    },
    {
      id: 'why-idle',
      q: 'Waarom het vermogen verlagen in rust?',
      a: 'Als de compressor rust, hoeft het water alleen in beweging te blijven, dus de pomp kan langzamer en stiller draaien.',
    },
    {
      id: 'off',
      q: 'Wat gebeurt er als ik het uitzet?',
      a: 'ovenbird stuurt dan geen opdrachten meer voor het pompvermogen. De pomp houdt het laatste maximale vermogen dat hij kreeg.',
    },
  ],
  related: ['pump', 'activity/commands'],
};
