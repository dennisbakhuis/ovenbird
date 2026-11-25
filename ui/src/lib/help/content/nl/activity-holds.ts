import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'activity/holds',
  title: 'Activiteit: blokkades',
  lead: 'Een blokkade betekent dat ovenbird een tijdje geen opdrachten naar de pomp stuurt, meestal omdat iets anders een pompinstelling wijzigde. Beslissen gaat intussen gewoon door.',
  art: 'activity',
  sections: [
    {
      id: 'why',
      kind: 'know',
      title: 'Waarom ovenbird gaat wachten',
      body: 'ovenbird controleert of de pomp de waarden houdt die hij stuurde. Verandert een waarde buiten ovenbird om, dan is er een [[foreign-writer|vreemde schrijver]] bezig: de afstandsbediening van Panasonic, Node-RED of een andere app. In plaats van om de pomp te vechten, stopt ovenbird even.\n\nOok een opdracht die de pomp na een paar pogingen niet bevestigt, start een [[hold|blokkade]].',
    },
    {
      id: 'current',
      kind: 'see',
      title: 'Blokkade van opdrachten',
      body: 'De blokkade van nu in gewone woorden, zoals **Iemand anders heeft de pomp aangepast**; wanneer ovenbird weer stuurt en hoeveel tijd er nog over is; en hoeveel blokkades er kort geleden waren, zoals "2 blokkades in de laatste 12 uur". **Geen blokkade** betekent dat ovenbird opdrachten mag sturen.',
      target: 'activity/holds.current',
    },
    {
      id: 'escalation',
      kind: 'know',
      title: 'Blokkades duren steeds langer',
      body: 'Binnen 12 uur duurt de eerste blokkade 1 uur en de tweede 4 uur; de derde is **vergrendeld** en duurt tot een beheerder haar opheft. Dat zijn de standaardwaarden van de installatie. Zo wisselen ovenbird en een andere regelaar elkaar niet de hele dag af.',
    },
    {
      id: 'release',
      kind: 'do',
      title: 'Een blokkade opheffen',
      body: 'Oorzaak gevonden, bijvoorbeeld een instelling die op de afstandsbediening veranderd was? Hef de blokkade op, dan neemt ovenbird het weer over. Alleen een beheerder kan dat.',
      steps: [
        '**Blokkade opheffen** opent het formulier.',
        '**Reden (optioneel)**: noteer wat je hebt nagekeken.',
        '**Nu opheffen**: ovenbird stuurt zijn waarden weer en de telling begint opnieuw.',
      ],
    },
    {
      id: 'history',
      kind: 'see',
      title: 'Blokkadehistorie',
      body: 'Elke blokkade in de gekozen periode, genummerd binnen het escalatievenster, met hoelang ze duurde en hoe ze eindigde: **verlopen**, **opgeheven** of nog **actief**. **Waarom?** toont de melding van de service.',
      target: 'activity/holds.history',
    },
  ],
  questions: [
    {
      id: 'heating',
      q: 'Staat de verwarming uit tijdens een blokkade?',
      a: 'Nee. De pomp verwarmt verder op de waarden die hij heeft. ovenbird blijft beslissen, dus [Aanvoer](#/setpoint) laat zien wat hij zou sturen.',
    },
    {
      id: 'remote',
      q: 'Ik heb zelf de temperatuur op de afstandsbediening veranderd. Is dat fout?',
      a: 'Het werkt, maar ovenbird ziet het als een andere schrijver en wacht. Wil je het warmer of koeler, gebruik dan het comfortdoel bij [Comforttemperatuur](#/settings/room).',
    },
    {
      id: 'cannot',
      q: 'Waarom kan ik de blokkade niet opheffen?',
      a: 'Alleen een beheerder kan dat. Een blokkade door een kritiek alarm kun je hier niet opheffen; die eindigt als het alarm verdwijnt.',
    },
  ],
  related: ['activity', 'activity/commands'],
};
