/**
 * A request to open the settings review dialog from outside Settings (the comfort sheet on
 * Home): the draft bar picks it up, clears it and opens the review of the current draft.
 */
export const reviewRequest = $state({ pending: false });
