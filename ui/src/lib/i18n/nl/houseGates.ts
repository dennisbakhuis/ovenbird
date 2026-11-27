import type { houseGates as en } from '$lib/i18n/en/houseGates';

export const houseGates: Record<keyof typeof en, string> = {
  houseGatesTitle: 'Waarvoor je het model kunt vertrouwen',
  houseGatesLead:
    'Elke toepassing heeft een eigen controle. Dat er één gehaald is, zegt niets over de andere.',
  houseGateName_heat_loss: 'Warmteverlies',
  houseGateName_dynamics: 'Gedrag van de kamer',
  houseGateName_sun: 'Reactie op de zon',
  houseGateUses_heat_loss: 'Gebruikt voor de isolatiescore, het stooklijnvoorstel en Wat als.',
  houseGateUses_dynamics: 'Gebruikt voor de voorspelling van het afkoelen.',
  houseGateUses_sun: 'Nog niet in gebruik: bedoeld voor een latere versie van het modelplan.',
  houseGateOk: 'Vertrouwd',
  houseGateNotYet: 'Nog niet',
  houseGateSource_fitted: 'Beoordeeld toen het model werd gemaakt.',
  houseGateSource_revalidated: 'Opnieuw beoordeeld op nieuwere gegevens.',
  houseGateSource_legacy: 'Gemaakt door een oudere versie; nog niet volledig beoordeeld.',
  houseGateNeedUnknown: 'Er is nog niet genoeg bewijs.',

  houseGateNeed_no_signature:
    'De dagelijkse energiecijfers laten nog geen duidelijk stookpatroon zien.',
  houseGateNeed_more_heating_days:
    'Er zijn meer stookdagen nodig: dagen die koud genoeg waren om de warmtepomp te laten draaien.',
  houseGateNeedAmount_more_heating_days:
    'Er zijn nog {n} stookdagen nodig: dagen die koud genoeg waren om de warmtepomp te laten draaien.',
  houseGateNeedAmountOne_more_heating_days:
    'Er is nog 1 stookdag nodig: een dag die koud genoeg was om de warmtepomp te laten draaien.',
  houseGateNeed_more_outside_spread:
    'Er is meer spreiding in de buitentemperatuur nodig om warmteverlies en vrije warmte uit elkaar te halen.',
  houseGateNeedAmount_more_outside_spread:
    'Er is nog {n} K meer spreiding in de buitentemperatuur nodig om warmteverlies en vrije warmte uit elkaar te halen.',
  houseGateNeed_ua_interval_wide:
    'Het warmteverlies is nog te onzeker: het bereik is nog te breed.',
  houseGateNeed_ua_disagrees:
    'De twee schattingen van het warmteverlies, uit het model en uit de dagelijkse energiecijfers, komen niet overeen.',
  houseGateNeed_ua_unstable: 'Het warmteverlies verschilt te veel tussen losse leerperiodes.',
  houseGateNeed_no_dynamics_skill:
    'Het model voorspelt de kamer voor de komende uren nog niet beter dan "de kamer blijft zoals hij is".',
  houseGateNeed_more_sunny_days:
    'Er zijn meer zonnige dagen nodig om te controleren hoe het model met de zon omgaat.',
  houseGateNeed_no_sun_skill:
    'Met de zon erbij voorspelt het model de kamer nog niet beter dan zonder.',
  houseGateNeed_sun_response_off:
    'De gemeten reactie van de kamer op de zon wijkt te veel af van die van het model.',
  houseGateNeed_legacy_model:
    'Dit model is gemaakt door een oudere versie; de volgende leerronde controleert het.',

  houseGateDetails: 'Uitkomst van de controles',
  houseGateDetailsGate: '{gate}: {state}',
  houseCheck_signature: 'Dagelijkse energiecijfers tonen een stookpatroon',
  houseCheck_excitation: 'Genoeg stookweer in de gegevens',
  houseCheck_ua_interval: 'Bereik van het warmteverlies smal genoeg',
  houseCheck_ua_agreement: 'Beide schattingen van het warmteverlies komen overeen',
  houseCheck_ua_stability: 'Warmteverlies stabiel tussen leerperiodes',
  houseCheck_skill_6h: 'Beter dan "geen verandering" voor de komende 6 uur',
  houseCheck_sunny_days: 'Zonnige dagen om op te toetsen',
  houseCheck_sun_skill: 'Zon verbetert de voorspelling van de kamer',
  houseCheck_sun_response: 'Reactie van de kamer op de zon klopt met het model',
  houseCheckPass: 'gehaald',
  houseCheckFail: 'nog niet',
  houseCheckValue: '{value}, grens {limit}',
  houseCheckValueOnly: '{value}',
  houseSkill24:
    'Over een hele dag vooruit scoort het model {value} tegen "geen verandering". Dit staat er alleen ter informatie en telt niet mee: een huis dat op een vaste temperatuur wordt gehouden, is moeilijk beter te voorspellen dan "geen verandering".',

  houseSunLineOk: 'Reactie op de zon: vertrouwd',
  houseSunLineNot: 'Reactie op de zon: nog niet. {reason}.',
  houseSunLineNotPlain: 'Reactie op de zon: nog niet',
  houseSunLineUse: 'Nog niet in gebruik: bedoeld voor een latere versie van het modelplan.',

  houseDriftNotTrusted:
    'Het afkoelen wordt nog niet vertrouwd: het model voorspelt nog niet goed genoeg hoe de kamer reageert, dus zie het als een ruwe schatting.',
  houseStatusTrusted: 'Vertrouwd',
  houseStatusPartly: 'Deels vertrouwd',
};
