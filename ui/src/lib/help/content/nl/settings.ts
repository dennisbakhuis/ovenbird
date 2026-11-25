import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings',
  title: 'Instellingen',
  lead: 'Alles wat ovenbird aan je verwarming mag veranderen, op één plek. Elke wijziging wordt gecontroleerd en doorgerekend voordat ze ingaat, en elke eerdere versie kun je terugzetten.',
  art: 'settings',
  sections: [
    {
      id: 'cards',
      kind: 'see',
      title: 'De kaarten van het overzicht',
      body: 'Elke kaart toont de huidige waarde van één onderdeel: de [[heating-curve|stooklijn]] bij drie buitentemperaturen, je comforttemperatuur met de kamer nu, het pompvermogen, de grenzen, de stille tijdvakken, de houtkachelmodus, de afgifte, het weer en de [[config-version|configuratieversie]].\n\nEen gekleurde stip betekent dat er in dat onderdeel niet-opgeslagen wijzigingen zijn. Klik op een kaart om het te openen.',
      target: 'settings.cards',
    },
    {
      id: 'change',
      kind: 'do',
      title: 'Een instelling wijzigen',
      body: 'Wijzigingen gaan niet meteen in. Ze komen in een [[draft|concept]] in deze browser. Een balk onderaan laat zien hoeveel het er zijn en of ze door de controles komen.',
      steps: [
        'Open een onderdeel: in de lijst links, of met de keuzelijst bovenaan op een telefoon.',
        'Wijzig een waarde. Een stip markeert hem; de pijl voor ongedaan maken zet hem terug.',
        '**Bekijken en toepassen** in de balk onderaan controleert en bewaart je concept. **Weggooien** gooit het weg.',
      ],
    },
    {
      id: 'preview',
      kind: 'know',
      title: 'Wat je bij het bekijken ziet',
      body: 'Voordat er iets wordt bewaard, wordt je wijziging [[preview|doorgerekend]]: de beslissing van dit moment met de huidige instellingen en met de jouwe, en een terugblik op de afgelopen 24 uur met de jouwe.\n\nProblemen blokkeren het toepassen; waarschuwingen moet je aanvinken. De terugblik is een open lus: hij laat zien hoe de [[setpoint|aanvoertemperatuur]] was afgeweken, niet hoe warm het huis was geweest.',
    },
    {
      id: 'apply',
      kind: 'know',
      title: 'Wanneer een wijziging ingaat',
      body: '**Toepassen** bewaart een nieuwe versie. De regelaar neemt haar over tussen twee beslissingen, binnen ongeveer een minuut. Wat hij geleerd heeft blijft behouden, dus de watertemperatuur verandert in haar gewone stappen, nooit met een sprong.\n\nToch niet goed? Draai het terug bij [Versies en back-up](#/settings/versions).',
    },
    {
      id: 'locked',
      kind: 'know',
      title: 'Vastgezette instellingen',
      body: 'Een slotje betekent dat de waarde uit de installatie komt: een omgevingsvariabele of het opties-bestand. Je ziet hem wel, maar je kunt hem hier niet wijzigen. De kaart Versies en back-up telt deze instellingen; dat onderdeel noemt ze allemaal, met hun variabele.',
      target: 'settings.locked',
    },
    {
      id: 'reset',
      kind: 'know',
      title: 'Als de opgeslagen instellingen kwijt zijn',
      body: 'Zijn de opgeslagen instellingen weg of beschadigd, dan start ovenbird met de standaardwaarden van de installatie in [[shadow|Schaduw]]: hij beslist, maar stuurt niets. Een gele melding vraagt je de instellingen na te lopen en op **Bevestigen** te klikken. Pas dan gaat hij terug naar zijn gewone modus.',
    },
  ],
  questions: [
    {
      id: 'safe',
      q: 'Kan ik veilig iets uitproberen?',
      a: 'Ja. Er gaat niets naar de warmtepomp totdat je toepast. Je ziet eerst het effect, de service bewaakt harde grenzen, en elke versie kun je terugdraaien.',
    },
    {
      id: 'undo',
      q: 'Hoe maak ik een toegepaste wijziging ongedaan?',
      a: 'Open [Versies en back-up](#/settings/versions) en klik bij de versie daarvoor op **Deze versie herstellen**. Dat bewaart een nieuwe versie met de oude waarden.',
    },
    {
      id: 'default',
      q: 'Hoe zet ik een instelling terug naar de standaard?',
      a: 'Klik op het **?** ernaast. Daar staat de standaardwaarde of de waarde van de voorinstelling en, als jouw waarde afwijkt, een knop **Terug naar standaard** of **Terug naar voorinstelling**. Dat verandert alleen je concept.',
    },
    {
      id: 'busy',
      q: 'Waarom staat er “Te veel wijzigingen kort na elkaar”?',
      a: 'De service accepteert één keer toepassen per minuut en hooguit 30 keer per dag. Wacht een minuut en probeer het opnieuw.',
    },
  ],
  related: ['settings/curve', 'settings/room', 'settings/versions'],
};
