import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'start',
  title: 'Begin hier',
  lead: 'Wat ovenbird met je warmtepomp doet, wie de pomp nu aanstuurt, wat er gebeurt als ovenbird stopt, en waar je eerst kijkt.',
  art: 'welcome',
  sections: [
    {
      id: 'what',
      kind: 'know',
      title: 'Wat ovenbird doet',
      body: 'Elke minuut rekent ovenbird één getal uit: de watertemperatuur voor de pomp, de [[setpoint|aanvoertemperatuur]]. Hij begint bij de [[heating-curve|stooklijn]] voor de buitentemperatuur en telt er [[room-feedback|ruimtecorrectie]] bij op als de kamer kouder of warmer is dan je comforttemperatuur.\n\novenbird stuurt dat getal via [[heishamon|HeishaMon]] en controleert of de pomp het overnam. Wanneer de pomp start en stopt, beslist ze nog steeds zelf.',
    },
    {
      id: 'modes',
      kind: 'know',
      title: 'De standen',
      body: '- **Automatisch**: ovenbird leest de pomp, beslist en stuurt ([[auto-mode|automatisch]]).\n- **Schaduw**: hij leest en beslist elke minuut maar stuurt nooit ([[shadow|Schaduw]]). De pomp draait dan op haar eigen instellingen of op een andere regelaar.\n- **Gepauzeerd**: ovenbird stuurt niets tot je hervat; hij blijft lezen en beslissen.\n- **Uit**: hij beslist en stuurt niets.\n\nDe modusknop in de bovenbalk opent het venster met de details.',
    },
    {
      id: 'who',
      kind: 'see',
      title: 'Wie stuurt de pomp',
      body: 'De regel onder de statusbalk zegt in één zin wat ovenbird nu doet, bijvoorbeeld "ovenbird stuurt de warmtepomp aan", "ovenbird kijkt alleen mee; een andere regelaar stuurt de pomp" of "ovenbird wacht tot 18:25". Hij volgt wat er echt gebeurt, niet alleen de modus ([[control-state|wie stuurt de pomp]]).\n\nStuurt ovenbird niet, dan zie je **zou sturen** (de waarde van ovenbird) naast **pomp heeft** (waar de pomp op draait).',
    },
    {
      id: 'stops',
      kind: 'know',
      title: 'Als ovenbird stopt',
      body: 'De pomp houdt de laatste watertemperatuur die ze kreeg en verwarmt daarop door: ze gaat niet uit. Alleen het bijsturen stopt: geen aanpassingen voor het weer of de kamer tot ovenbird weer draait.\n\nNa een herstart stuurt ovenbird niets tot er verse gegevens van de pomp zijn, en gaat hij verder met wat hij geleerd had. Een veiligheidsregel op HeishaMon zelf, voor als ovenbird uitvalt, staat gepland maar zit niet in deze versie.',
    },
    {
      id: 'first',
      kind: 'do',
      title: 'Waar je eerst kijkt',
      body: 'Begin op [Thuis](#/home). De regel bovenaan vat het huis samen: "Het huis is op temperatuur", "Aan het opwarmen" of "Aandacht nodig: …".\n\nIs er iets mis, dan geeft ovenbird een [[alarm]]. De statusbalk telt ze, en [Activiteit](#/activity) toont elk alarm, met wat ovenbird er nu aan doet en wat jij kunt doen.',
    },
    {
      id: 'warmer',
      kind: 'do',
      title: 'Warmer of koeler',
      body: 'Tik op het doel op de kamerkaart van Thuis ("Doel 21,0 °C") om de comforttemperatuur in stappen van 0,1 °C te veranderen, of open [Instellingen → Comforttemperatuur](#/settings/room). Een wijziging gaat binnen ongeveer een minuut in, en elke eerdere versie kun je terugzetten.',
    },
  ],
  questions: [
    {
      id: 'notification',
      q: 'Krijg ik een melding als er iets mis is?',
      a: 'Nog niet. ovenbird stuurt vandaag geen berichten naar je telefoon of naar Home Assistant. Alarmen zie je alleen in de app: in de statusbalk, op Thuis en bij [Activiteit](#/activity). Kijk daar af en toe, zeker in de eerste weken.',
    },
    {
      id: 'fallback',
      q: 'Is er een terugval als ovenbird of het netwerk uitvalt?',
      a: 'De pomp houdt de laatste watertemperatuur die ze kreeg, dus het huis blijft verwarmd, alleen zonder bijsturing. Een regel op HeishaMon die de pomp binnen de [[envelope|veiligheidsband]] houdt terwijl ovenbird uitligt, staat gepland maar is er nog niet. Zolang ovenbird draait, blijft elke aanvoertemperatuur binnen die band.',
    },
    {
      id: 'home-assistant',
      q: 'Wat gebeurt er als Home Assistant herstart?',
      a: 'ovenbird draait door: het is een aparte service die via HeishaMon met de pomp praat. De kamersensor leest hij uit Home Assistant; zonder die sensor regelt hij op de stooklijn en laat hij een opgebouwde correctie die verwarmt in 24 uur afzwakken.',
    },
    {
      id: 'try',
      q: 'Kan ik ovenbird proberen zonder dat hij de pomp aanstuurt?',
      a: 'Ja, daar is [[shadow|Schaduw]] voor. ovenbird beslist elke minuut naast je huidige regelaar, zoals Node-RED, zonder iets te schrijven. Op [Aanvoer](#/setpoint) zie je wat hij zou sturen naast wat de pomp heeft.',
    },
  ],
  related: ['switching', 'home', 'activity', 'system'],
  aliases: [
    'wie stuurt',
    'who controls',
    'melding',
    'notificatie',
    'notification',
    'beginnen',
    'overzicht',
  ],
};
