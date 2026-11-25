/**
 * The two viewport breakpoints. `src/styles/media.css` defines them for CSS as
 * `@custom-media --narrow` and `--wide` (expanded by postcss-custom-media); these constants are the
 * same values for `matchMedia`, and a guard test keeps both in step.
 */
export const NARROW_QUERY = '(max-width: 40rem)';
export const WIDE_QUERY = '(min-width: 60rem)';
