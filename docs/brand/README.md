# ovenbird brand

## The mark

The rufous hornero (*Furnarius rufus*), the ovenbird, builds a dome of clay with a door in
it: an oven that keeps its young warm. ovenbird the controller does the same for a house.
The mark is that nest, with an ember in the door, standing on a blue water line (the heating
loop that carries the heat in). The bird sits on top and looks ahead: the forecast.

Files (source of truth in `ui/src/assets/brand/`):

| File | Use |
|---|---|
| `mark.svg` | the mark, 64 × 64, light backgrounds |
| `favicon.svg` | 32 × 32 without the bird, for 16–32 px (the UI build serves and emits it as `/favicon.svg`) |
| `logo-light.svg`, `logo-dark.svg` | mark + wordmark, outlined (no font needed) |
| `ui/public/apple-touch-icon.png` | 180 px, mark on sand |
| `app/ovenbird/icon.png`, `logo.png` | Home Assistant app store (128 × 128, 250 × 100) |

In the UI, use `components/brand/Logo.svelte` (the bird takes the theme's ink, so it works
on dark surfaces). Rebuild the outlined lockups with
`docs/brand/build_wordmark.py` (usage in its docstring).

Below 24 px use `favicon.svg`; the bird does not survive at that size. Keep clear space of
a quarter of the mark's height around it. Do not recolour the clay, the door or the ember.

## Wordmark

"ovenbird", lower case, in Atkinson Hyperlegible: **oven** bold, bird regular. Atkinson
Hyperlegible was designed by the Braille Institute for letter shapes that cannot be confused
(1/l/I, 0/O, 5/S): good for a screen full of numbers. It is self-hosted (latin subset,
`ui/src/assets/fonts/`, SIL OFL 1.1) and used for headings and large values
(`--font-display`); body text stays in the system font.

## Colour

| Token | Hex | Role |
|---|---|---|
| `--brand-night` | `#14263D` | ink, the door, dark surfaces |
| `--brand-cobalt` | `#3F73AA` | water, interactive accent (`--accent`, 4.9:1 on white) |
| `--brand-pale` | `#CDE0EC` | cool fills, illustration ground |
| `--brand-clay` | `#C9652E` | the nest; warm fills in illustrations |
| `--brand-clay-deep` | `#8F3F1C` | clay shade (offset shadow) |
| `--brand-clay-light` | `#E7A274` | clay highlight |
| `--brand-sand` | `#F6EDE4` | warm ground |
| `--brand-ember` | `#F0842F` | the one spot of heat per drawing; never text |

The interface itself stays cool (navy, cobalt, greys) so that the status colours (green,
amber, red, purple) keep their meaning; clay and ember belong to the brand and the
illustrations, not to buttons or states. Dark theme: navy surfaces (`#0D1724`, `#142235`),
the accent lifts to `#7FB0E0`.

## Illustrations

Flat geometric drawings in the DinkelLabs manner: a soft blob as ground, objects built from
simple shapes with a solid offset "shadow" shape behind them (no gradients, no outlines),
and exactly one ember accent per drawing. Small clay pellets tumble around the scene the
way the cubes do on the DinkelLabs site. Colours come from the brand tokens only, so the
drawings follow the theme. Motion is a single short sequence when the drawing appears;
`prefers-reduced-motion` gets the finished picture. Drawings are decorative
(`aria-hidden`); the text next to them carries the meaning.
