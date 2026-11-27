export const houseModel = {
  'houseTab_what-if': 'What if',
  houseAnd: 'and',

  houseSchemTitle: 'The house right now',
  houseSrcModel: 'Measured model',
  houseSrcEstimate: 'Estimate from your answers, not measured',
  houseSrcLearning: 'Still learning',
  houseSchemAsOf: 'As of {time}',
  houseError_house_model_missing:
    'Fill in a few facts about the house and this picture shows where its heat goes.',
  houseError_house_series_missing:
    'No room prediction yet: the model has not predicted the room so far.',
  houseNote_dhw_active:
    'The heat pump is making hot water now, so its output does not heat the house.',
  busy_houseNote_dhw_active:
    'The heat pump is busy with something else now, so its output does not heat the house.',
  houseNote_defrost: 'The heat pump is defrosting now, so its output does not heat the house.',
  houseNote_room_unknown: 'The room temperature is not known right now.',
  houseNote_outside_unknown: 'The outside temperature is not known right now.',
  houseNote_heat_unknown: 'The heat pump output is not known right now.',
  houseNote_stove_tail:
    'A wood stove was burning in the last 12 hours. The building is still releasing its heat, so how much it stores is not known.',
  houseSchemFactsLink: 'Enter your facts',
  houseSchemFailed: 'The heat balance could not be loaded.',

  houseNodeOutside: 'Outside',
  houseNodeEnvelope: 'Walls, roof, windows',
  houseNodeRoom: 'Room',
  houseNodeMass: 'Heat storage',
  houseNodeMassSub: 'Floor and house',
  houseNodeCapacity: 'floor and house, {value} kWh per K in total',
  houseNodePump: 'Heat pump',
  houseNodePumpSub: 'Heating loop',
  houseNodeSun: 'Sun',
  houseNodePeople: 'Free heat',
  houseNodeStove: 'Wood stove',
  houseFlowLoss: 'Heat loss',
  houseFlowUnknown: 'unknown',
  houseFlowNotMeasured: 'heat not measured',
  houseStorage_storing: 'storing {value}',
  houseStorage_giving: 'giving back {value}',
  houseStorage_steady: 'steady',
  houseStorage_unknown: 'unknown',
  houseSun: '{value} W/m²',

  houseBalSentence: '{head}; {list}, {tail}.',
  houseBalLoss: 'Right now the house loses about {loss} to outside',
  houseBalLossUnknown: 'Right now the heat loss to outside is not known',
  houseBalPump: 'the heat pump delivers {value}',
  houseBalPumpNegative: 'the heat pump is drawing about {value} from the house (defrost)',
  houseBalPumpUnknown: 'the heat pump output is not known',
  houseBalSun: 'the sun adds about {value}',
  houseBalSunUnknown: "the sun's share is not known",
  houseBalInternal: 'free heat from people and appliances adds about {value}',
  houseBalTailStoring: 'so the building is storing about {value}',
  houseBalTailGiving: 'so the building is giving back about {value}',
  houseBalTailSteady: 'so the building stores or gives back almost nothing',
  houseBalTailUnknown: 'so how much heat the building stores is not known',
  houseBalTailStoveTail:
    'but a wood stove burned in the last 12 hours and the building is still releasing its heat, so how much it stores is not known',
  houseBalTailStove:
    'but the wood stove is burning too, so how much heat the building stores is not known',

  houseToldTitle: 'What you told us and what was measured',
  houseToldRow: 'You told us ≈ {told} · measured {measured} (90 % range {lo}–{hi})',
  houseToldRowPlain: 'You told us ≈ {told} · measured {measured}',
  houseToldDiffers:
    'The measurements disagree with your answers; the model follows the measurements.',
  houseTold_ua: 'Heat loss',
  houseTold_solar: 'Solar aperture',
  houseTold_gains: 'Net free heat',
  houseSettingsChanged:
    'You changed the house settings, so this model took over even though it predicted slightly worse: {challenger} K against {champion} K for the previous one.',
  houseSettingsChangedPlain:
    'You changed the house settings, so this model took over from the previous one.',

  housePredTitle: 'Measured and predicted room temperature',
  housePredMeasured: 'Measured',
  housePredPredicted: 'Predicted 24 h ahead',
  housePredRange: 'Period shown',
  housePredDays: '{n} d',
  housePredSummary:
    'Over the last {days} days the prediction was typically {typical} K off and at most {largest} K (around {when}).',
  housePredTypical: 'On unseen days the model is typically {typical} °C off.',
  housePredTypicalCold:
    'On unseen days the model is typically {typical} °C off, and on average {lean} °C too cold.',
  housePredTypicalWarm:
    'On unseen days the model is typically {typical} °C off, and on average {lean} °C too warm.',
  housePredTypicalLevel:
    'On unseen days the model is typically {typical} °C off, without a lasting lean to cold or warm.',
  housePredLargest: 'The largest difference in this window was {largest} K around {when}.',
  housePredUnseen: 'unseen days from here',
  housePredEventsTitle:
    'Left out of the comparison (no prediction is drawn there or for the 24 hours after)',
  housePredEventStove: 'Wood stove {from} to {to}, recovery until {tail}',
  housePredEventDay: 'Day left out: {day}',
  housePredLegendStove: 'Wood stove: hatched, recovery lighter',
  housePredLegendDay: 'Day left out: dotted',
  housePredNone: 'There are no measured and predicted values to compare yet.',
  housePredLoading: 'Loading the room temperatures.',

  houseTrendTime: 'Time constant',
  houseTrendHeat: 'Heat loss',
  houseTrendTimeSummary: 'The time constant of {n} models went from {first} to {last} hours.',
  houseTrendUnitH: 'h',

  houseWiTitle: 'What if',
  houseWiLead:
    'Try other weather and see what the heat pump would have to do. Nothing here changes any setting.',
  houseWiInputs: 'Conditions',
  houseWiOutside: 'Outside temperature',
  houseWiComfort: 'Comfort temperature',
  houseWiSun: 'Sunshine',
  houseWiSunExact: 'Sunshine (W/m²)',
  houseWiSun_0: 'None',
  houseWiSun_150: 'Hazy',
  houseWiSun_500: 'Bright',
  houseWiStove: 'Wood stove',
  houseWiStove_0: 'Off',
  houseWiStove_2000: 'Low · 2 kW',
  houseWiStove_5000: 'High · 5 kW',
  houseWiResults: 'What the house needs',
  houseWiUpdating: 'Updating…',
  houseWiDemand: 'The heat pump has to deliver about {value}.',
  houseWiFree: 'The house loses {loss}; sun, people and appliances already give {free}.',
  houseWiWater:
    'That needs about {supply} °C water leaving the heat pump ({mean} °C on average in the loop). Your heating curve gives {curve} °C at this outside temperature, the model needs {supply} °C.',
  houseWiLimitMax:
    'Your maximum supply of {max} °C limits this: the heat pump cannot send warmer water, so the room may stay below {comfort} °C.',
  houseWiLimitNone:
    'No heating is needed at {outside} °C outside with this sun: the free heat covers the loss.',
  houseWiBalance: 'With this sun, no heating is needed above {value} °C outside.',
  houseWiDriftTitle: 'With the heating off',
  houseWiDriftCools: 'With the heating off, the room cools to {end} °C in {hours} hours.',
  houseWiDriftHolds: 'With the heating off, the room stays at about {end} °C for {hours} hours.',
  houseWiDriftTau: 'The house cools with a time constant of about {tau} hours.',
  houseWiDriftAria:
    'Room temperature over {hours} hours with the heating off, from {start} °C to {end} °C.',
  houseWiSourceModel: 'From the measured model.',
  houseWiSourceEstimate: 'Estimate from your answers, not measured.',
  houseWiNotCredible:
    'The heat-loss check does not pass yet, so treat the heat demand and water temperature as rough.',
  houseWiNoModel:
    'The house model has no facts to work with yet. Fill in a few facts on the Overview tab first.',
  houseWiAbsent: 'This service does not offer the what-if yet.',
  houseWiFailed: 'The calculation did not work. Check the values and try again.',
  houseWiFactsLink: 'Open the Overview tab',
};
