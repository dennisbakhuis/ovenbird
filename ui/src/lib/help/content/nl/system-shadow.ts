import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system/shadow',
  title: 'Systeem: vergelijk met de andere regeling',
  lead: 'Zolang ovenbird alleen meekijkt, zet deze pagina wat hij zou sturen naast waar de pomp echt op draait, zodat je elk verschil kunt beoordelen.',
  art: 'system',
  sections: [
    {
      id: 'range',
      kind: 'do',
      title: 'Kies een periode',
      body: 'Kies **24 u**, **7 dagen**, **14 dagen** of **Zelf kiezen**. Bij Zelf kiezen geef je een begin en een eind op, hoogstens 31 dagen uit elkaar. De weergave van 24 u loopt vanzelf mee met nieuwe beslissingen; de langere laden één keer.',
      target: 'system/shadow.range',
    },
    {
      id: 'summary',
      kind: 'see',
      title: 'De cijfers',
      body: '**Vergeleken** is het deel van de periode met beide waarden; de rest zijn gaten. Daarna het gemiddelde en het grootste verschil, de tijd met meer dan 1 K verschil en het aantal episodes. De regel eronder zegt welke kant ovenbird op neigt: kouder of warmer dan de pomp.',
      target: 'system/shadow.summary',
    },
    {
      id: 'chart',
      kind: 'see',
      title: 'De grafiek',
      body: 'De doorgetrokken lijn is wat ovenbird zou sturen, de gestippelde lijn wat de pomp heeft. Het gekleurde vlak ertussen is de [[divergence|afwijking]]. De baan eronder laat zien wie de pomp schreef: ovenbird, een andere regelaar of niemand (geen gegevens). Een gat blijft een gat en telt nooit als overeenstemming.',
      target: 'system/shadow.chart',
    },
    {
      id: 'episodes',
      kind: 'see',
      title: 'Episodes',
      body: 'Een episode is een stuk waarin de twee meer dan 1 K uit elkaar blijven. Bij elke episode zie je wanneer en hoe lang, welke kant ovenbird op was gegaan, beide waarden bij het grootste verschil en de reden van ovenbird. Een verklaarde episode, zoals een nachtverlaging van de andere regeling, is prima: een beheerder kan **Markeren als verklaard…** met een korte notitie, en de checklist voor de overstap telt hem dan niet meer.',
      target: 'system/shadow.episodes',
    },
    {
      id: 'days',
      kind: 'see',
      title: 'Per dag',
      body: 'Eén regel per dag in de tijdzone van de service: het vergeleken deel, het gemiddelde en grootste verschil, de tijd boven 1 K en de episodes die die dag begonnen. Een dag aan de rand van de periode zegt hoeveel uur ervan meetelt.',
      target: 'system/shadow.days',
    },
    {
      id: 'why',
      kind: 'know',
      title: 'Waarom vergelijken',
      body: 'Voordat ovenbird de pomp mag sturen, kijkt hij minstens 14 dagen mee in [[shadow|Schaduw]] naast je huidige regeling. Geen onverklaarde afwijking in die tijd is een van de controles voor de overstap op de pagina [Proef](#/system/trial).',
    },
  ],
  questions: [
    {
      id: 'value',
      q: 'Welke waarde van de pomp wordt vergeleken?',
      a: 'De aanvoertemperatuur die de pomp als doel meldt (Z1_Water_Target_Temp), wie die ook schreef: Node-RED, de afstandsbediening of de veiligheidsregel op de HeishaMon.',
    },
    {
      id: 'difference',
      q: 'Er zit 2 K verschil tussen. Is dat fout?',
      a: 'Niet vanzelf. Lees de reden van ovenbird bij de episode, en bekijk de volledige uitleg van dat moment op de pagina [Aanvoer](#/setpoint). Een verschil dat je kunt verklaren is prima.',
    },
    {
      id: 'empty',
      q: 'De pagina zegt dat er niets te vergelijken is.',
      a: 'ovenbird heeft in deze periode nog niet lang genoeg meegekeken, of de waarde van de pomp ontbrak. Kies een langere periode of kom later terug.',
    },
  ],
  related: ['system/trial', 'setpoint', 'system'],
  aliases: ['baseline', 'Node-RED', 'afwijking', 'vergelijken', 'vergelijking'],
};
