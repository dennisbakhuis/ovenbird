"""Build the ovenbird lockups (mark + outlined wordmark) as font-free SVG files.

Usage: ``uv run --no-project --with fonttools python docs/brand/build_wordmark.py
ui/src/assets/brand <directory with atkinson-hyperlegible-{bold,regular}.ttf>``.
"""

import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

NIGHT = "#14263D"
LOCKUPS = (("logo-light", NIGHT, NIGHT), ("logo-dark", "#EAF2F8", "#EAF2F8"))
DOOR = 'd="M24 54 V47.5'


def outline(font_path: Path, text: str, x: float, size: float) -> tuple[str, float]:
    """Return an SVG path for ``text`` on the lockup baseline and the x after it."""
    font = TTFont(font_path)
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    scale = size / font["head"].unitsPerEm
    pen = SVGPathPen(glyphs)
    for char in text:
        name = cmap[ord(char)]
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, 48)))
        x += glyphs[name].width * scale
    return pen.getCommands(), x


def recolour_bird(mark: str, ink: str) -> str:
    """Give the bird ``ink`` while the door keeps the night colour."""
    lines = []
    for line in mark.splitlines():
        lines.append(line if DOOR in line else line.replace(NIGHT, ink))
    return "\n".join(lines)


def lockup(fonts: Path, mark: str, ink: str, bird_ink: str) -> tuple[str, float]:
    """Return the horizontal lockup body and its width."""
    bold, end = outline(fonts / "atkinson-hyperlegible-bold.ttf", "oven", 74, 40)
    regular, end = outline(fonts / "atkinson-hyperlegible-regular.ttf", "bird", end + 0.5, 40)
    body = (
        f"<g>{recolour_bird(mark, bird_ink)}</g>"
        f'<path d="{bold}" fill="{ink}"/><path d="{regular}" fill="{ink}"/>'
    )
    return body, end + 4


def main() -> None:
    """Write logo-light.svg and logo-dark.svg next to mark.svg."""
    out = Path(sys.argv[1])
    fonts = Path(sys.argv[2])
    mark = (out / "mark.svg").read_text().split("\n", 1)[1].rsplit("</svg>", 1)[0]
    for name, ink, bird in LOCKUPS:
        body, width = lockup(fonts, mark, ink, bird)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} 64" '
            f'width="{width * 2:.0f}" height="128">{body}</svg>\n'
        )
        (out / f"{name}.svg").write_text(svg)


if __name__ == "__main__":
    main()
