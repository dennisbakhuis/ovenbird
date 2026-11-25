/**
 * The product name and the strings derived from it. Storage keys and download names built from
 * these stay byte-identical to what users already have, so remembered state survives.
 */
export const WORDMARK = { bold: 'oven', light: 'bird' } as const;
export const NAME = WORDMARK.bold + WORDMARK.light;
export const STORAGE_PREFIX = `${NAME}.`;
export const DOWNLOAD_PREFIX = `${NAME}-`;
