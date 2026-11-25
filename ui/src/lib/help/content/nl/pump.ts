import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'pump',
  title: 'Pomp',
  lead: 'De warmtepomp van dichtbij: de waterkring op dit moment, hoe ze vandaag en deze week draaide, en de drie pompinstellingen die je zelf kunt wijzigen.',
  art: 'pump',
  sections: [
    {
      id: 'loop',
      kind: 'see',
      title: 'Waterkring',
      body: 'Links staat de buitenunit: wat ze doet, het toerental van de [[compressor]] in Hz, stroom erin, warmte eruit en de [[cop|COP]]. Het water vertrekt op de [[outlet|aanvoertemperatuur]], geeft zijn warmte af in je vloer of radiatoren en komt terug op de [[inlet|retourtemperatuur]].\n\nIn het midden: het [[flow|debiet]], de [[delta-t|ΔT]] naast de ingestelde waarde, en het [[pump-duty|pompvermogen]] tegen zijn maximum.',
      target: 'pump.loop',
    },
    {
      id: 'day',
      kind: 'see',
      title: 'Laatste 24 uur',
      body: 'De banen laten zien wanneer de compressor draaide, de pomp [[defrost|ontdooide]], [[dhw|warm water]] maakte en in de [[quiet-mode|stille modus]] stond.\n\nDe cijfers eronder tellen vanaf middernacht in de tijdzone van de service (in de kop als die niet de jouwe is), dezelfde dag als op Thuis: starts, gemiddelde en langste looptijd, ontdooiingen, elektriciteit, warmte en COP. Een run die om middernacht al liep, telt vandaag niet als start. Minder, langere runs zijn beter (zie [[short-cycling|pendelen]]).',
      without: {
        hotWater: {
          body: 'De banen laten zien wanneer de compressor draaide, de pomp [[defrost|ontdooide]] en in de [[quiet-mode|stille modus]] stond. Was de pomp elders bezig, dan staat daar ook een baan voor.\n\nDe cijfers eronder tellen vanaf middernacht in de tijdzone van de service (in de kop als die niet de jouwe is), dezelfde dag als op Thuis: starts, gemiddelde en langste looptijd, ontdooiingen, elektriciteit, warmte en COP. Een run die om middernacht al liep, telt vandaag niet als start. Minder, langere runs zijn beter (zie [[short-cycling|pendelen]]).',
        },
      },
      target: 'pump.day',
    },
    {
      id: 'flow',
      kind: 'see',
      title: 'Watertemperaturen en debiet',
      body: 'Drie panelen over de laatste 24 uur: ΔT met de ingestelde waarde, debiet, en pompvermogen met zijn maximum. Gearceerde stukken zijn ontdooicycli.\n\nBij ontdooien draait de pomp om om het ijs te smelten: aanvoer en retour wisselen van rol en ze kiest haar eigen pompvermogen, vaak boven het maximum. Daarom schieten ΔT en pompvermogen daar buiten hun normale bereik.',
      target: 'pump.flow',
    },
    {
      id: 'cop',
      kind: 'see',
      title: 'COP tegen buitentemperatuur',
      body: 'Elk punt is één uur uit de laatste 7 dagen waarin de pomp stroom gebruikte: de buitentemperatuur tegen de COP van dat uur. De gestippelde lijn is de trend.\n\nVerwacht dat de punten naar rechts stijgen: hoe warmer het buiten is, hoe makkelijker de pomp warmte uit de lucht haalt. Punten die laag liggen zijn vaak uren met een ontdooicyclus.',
      target: 'pump.cop',
    },
    {
      id: 'daily',
      kind: 'see',
      title: 'Cijfers per dag',
      body: 'Eén balk per dag voor de laatste **7 dagen** of **30 dagen**: elektriciteit, geleverde warmte, COP, compressorstarts, looptijd, ontdooiingen, en hoeveel de kamer onder de [[comfort-band|comfortband]] zat (in [[degree-hours|graaduren]]).\n\nDe lichte balk is vandaag, nog bezig. Een lege balk betekent geen gegevens die dag. De cijfers komen uit de eigen schattingen van de pomp voor stroom en warmte.',
      target: 'pump.daily',
    },
    {
      id: 'settings',
      kind: 'do',
      title: 'Een pompinstelling wijzigen',
      body: 'Je kunt drie instellingen wijzigen: **Delta-T bij verwarmen** (3–10 K), **Doorstromingsmodus van de pomp** ([[flow-mode|Delta-T of Maximaal debiet]]) en **Verwarming uit boven buitentemperatuur** (zie [[heating-off-temperature|verwarming uit]]). ovenbird controleert daarna of de pomp de nieuwe waarde heeft overgenomen.',
      steps: [
        'Kies **Wijzigen** naast de instelling.',
        'Vul de nieuwe waarde in bij **Nieuwe waarde**.',
        'Typ de waarde nog een keer ter bevestiging en kies **Naar de pomp sturen**.',
      ],
      target: 'pump.settings',
    },
    {
      id: 'when-not',
      kind: 'know',
      title: 'Als een wijziging geweigerd wordt',
      body: 'Alleen een beheerder kan pompinstellingen wijzigen, en alleen als ovenbird op [[auto-mode|Automatisch]] staat. Een wijziging wordt geweigerd tijdens ontdooien, warm water maken of een [[hold|blokkade]], of als er al een andere wijziging onderweg is. Elke instelling kan één keer per 10 minuten en zes keer per dag veranderen, om de pomp te sparen.\n\nAlles onder **Alleen-lezen details** hoort bij ovenbird, de pomp zelf of de installateur. Je ziet het hier wel, maar wijzigt het niet.',
      without: {
        hotWater: {
          body: 'Alleen een beheerder kan pompinstellingen wijzigen, en alleen als ovenbird op [[auto-mode|Automatisch]] staat. Een wijziging wordt geweigerd tijdens ontdooien, als de pomp elders bezig is, tijdens een [[hold|blokkade]] of als er al een andere wijziging onderweg is. Elke instelling kan één keer per 10 minuten en zes keer per dag veranderen, om de pomp te sparen.\n\nAlles onder **Alleen-lezen details** hoort bij ovenbird, de pomp zelf of de installateur. Je ziet het hier wel, maar wijzigt het niet.',
        },
      },
    },
  ],
  questions: [
    {
      id: 'duty-defrost',
      q: 'Waarom springt het pompvermogen bij ontdooien boven het maximum?',
      a: 'Tijdens het ontdooien stuurt de pomp haar circulatiepomp zelf aan en negeert ze het maximum. ovenbird weet dat: het stuurt tijdens ontdooien geen opdracht voor het pompvermogen en gaat daarna verder waar het was.',
    },
    {
      id: 'delta-small',
      q: 'Moet ik de delta-T kleiner of groter maken?',
      a: 'Een kleinere delta-T geeft meer debiet en water dat warmer terugkomt; een grotere minder debiet en meer afkoeling per liter. Er is geen enkele juiste waarde. Verander hem 1 K per keer en kijk een paar dagen naar de kamer, de starts en de COP voor je de volgende stap zet.',
    },
    {
      id: 'idle-delta',
      q: 'Waarom is de ΔT bijna nul als de pomp stand-by staat?',
      a: 'Met de compressor uit komt er geen warmte bij, dus het water gaat er ongeveer even warm uit als het terugkwam. De circulatiepomp kan op een laag pompvermogen blijven draaien.',
    },
    {
      id: 'no-change-button',
      q: 'Waarom kan ik niets wijzigen?',
      a: 'Bovenaan de kaart staat een regel die zegt waarom, bijvoorbeeld [[shadow|Schaduw]], een blokkade of ontdooien. Ben je niet als beheerder aangemeld, dan zie je de instellingen wel maar kun je ze niet wijzigen.',
    },
  ],
  related: ['home', 'settings/pump-duty', 'settings/quiet', 'activity/commands'],
};
