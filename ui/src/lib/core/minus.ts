/**
 * Replace the hyphen-minus in front of digits with the typographic minus sign (U+2212).
 */
export function minus(text: string): string {
  return text.replace(/(^|[\s(\u00a0])-(?=\d)/g, '$1−');
}
