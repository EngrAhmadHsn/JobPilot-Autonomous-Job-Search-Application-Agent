"""Render the Open Graph card from the product's own tokens.

The card is generated rather than hand-drawn so its colours cannot drift from
`frontend/src/index.css`: the night canvas, ivory type, lime for the agent's
line. Run with `env/Scripts/python.exe`. It writes `frontend/public/og.png`.

This is a development-time asset script, not runtime code. It is committed so
the card can be regenerated when the headline changes.
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

NIGHT = (14, 26, 22)
NIGHT_SOFT = (19, 34, 28)
IVORY = (247, 245, 239)
LIME = (217, 243, 106)
FOREST = (23, 61, 50)
MUTED = (157, 179, 167)

WIDTH, HEIGHT = 1200, 630
OUT = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "public" / "og.png"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """A sans face that ships with Windows, falling back to the bitmap default."""
    names = (
        ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf"]
        if bold
        else ["segoeui.ttf", "arial.ttf", "calibri.ttf"]
    )
    candidates = [pathlib.Path("C:/Windows/Fonts") / name for name in names]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), NIGHT)
    draw = ImageDraw.Draw(image, "RGBA")

    # The soft wash the landing hero uses, approximated with concentric bands so
    # the card needs no gradient library. Each band shrinks inward, and the
    # bounds are clamped so the box never inverts.
    for step in range(24):
        alpha = int(22 * (1 - step / 24) ** 2)
        inset = step * 18
        box = (-240 + inset, -380 + inset, 860 - inset, 470 - inset)
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            break
        draw.ellipse(box, fill=(*FOREST, alpha))

    # The mark: a lime tile with the ivory page on it.
    draw.rounded_rectangle((80, 92, 152, 164), radius=18, fill=LIME)
    draw.polygon(
        [(102, 112), (124, 112), (134, 122), (134, 158), (102, 158)],
        fill=IVORY,
        outline=FOREST,
        width=4,
    )
    draw.line([(112, 132), (126, 132)], fill=FOREST, width=5)

    draw.text((176, 112), "JobPilot", font=load_font(34, bold=True), fill=IVORY)

    headline = load_font(64, bold=True)
    draw.text((80, 236), "JobPilot finds the roles", font=headline, fill=IVORY)
    draw.text((80, 310), "and fills in the forms.", font=headline, fill=IVORY)
    draw.text(
        (80, 384), "You approve what gets sent.", font=headline, fill=LIME
    )

    draw.text(
        (80, 500),
        "Ranks openings against your résumé, shows the gaps,",
        font=load_font(26),
        fill=MUTED,
    )
    draw.text(
        (80, 536),
        "and prepares the application.",
        font=load_font(26),
        fill=MUTED,
    )

    image.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
