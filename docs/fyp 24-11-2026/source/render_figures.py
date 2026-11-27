"""Regenerate the print figures locally; give PLANTUML_JAR or install the PlantUML CLI.

    python source/render_figures.py [--check] [stem ...]

A failed render or typography check leaves the existing set in place. The nominal
label size assumes 15 px at 96 dpi and the same fit box as publish.py.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import zlib

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "diagrams"
DPI = 192


def print_metadata(png: Path) -> None:
    # PlantUML's DPI macro changes the pixels, but may omit PNG physical resolution.
    raw = png.read_bytes()
    parts = [raw[:8]]
    i = 8
    ppm = round(DPI / 0.0254)
    while i < len(raw):
        n = int.from_bytes(raw[i : i + 4], "big")
        kind = raw[i + 4 : i + 8]
        end = i + 12 + n
        if kind != b"pHYs":
            parts.append(raw[i:end])
        if kind == b"IHDR":
            body = b"pHYs" + struct.pack(">IIB", ppm, ppm, 1)
            parts.append(
                struct.pack(">I", 9) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
            )
        i = end
    png.write_bytes(b"".join(parts))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true")
    p.add_argument("stems", nargs="*")
    a = p.parse_args()
    sources = {f.stem: f for f in sorted(ROOT.glob("*.puml")) if not f.name.startswith("_")}
    chosen = a.stems or list(sources)
    if not chosen or set(chosen) - set(sources):
        p.error("Unknown or empty diagram selection.")
    jar = os.environ.get("PLANTUML_JAR")
    command = (
        [
            shutil.which("java") or "java",
            "-Xmx300m",
            "-Dfile.encoding=UTF-8",
            "-jar",
            str(Path(jar).resolve()),
        ]
        if jar
        else [shutil.which("plantuml") or "plantuml"]
    )
    with tempfile.TemporaryDirectory(prefix="jobpilot-diagrams-") as td:
        td = Path(td).resolve()
        for key in chosen:
            t = sources[key].read_text(encoding="utf-8")
            if (
                not re.search(r"(?m)^@startuml\s+" + re.escape(key) + r"\s*$", t)
                or "!include _theme.puml" not in t
            ):
                raise SystemExit("Missing named block/theme: " + key)
        # Limit Java to one render thread; this build also runs on small Windows machines.
        subprocess.run(
            command
            + [
                "-nbthread",
                "1",
                "-DFYP_DPI=192",
                "-charset",
                "UTF-8",
                "-tpng",
                "-o",
                str(td),
                *[str(sources[s]) for s in chosen],
            ],
            check=True,
            timeout=240,
        )
        for key in chosen:
            f = td / (key + ".png")
            print_metadata(f)
            with Image.open(f) as im:
                w, h = im.size
                im.verify()
            scale = min(1, 6.04 / (w / DPI), 5.6 / (h / DPI))
            pt = 15 * 72 / 96 * scale
            print(f"{key:<22} {w:>4} x {h:<4} px   estimated label {pt:.1f} pt")
            if pt < 7:
                raise SystemExit("Split or shorten the labels in " + key)
        if not a.check:
            (ROOT / "png").mkdir(exist_ok=True)
            for key in chosen:
                shutil.copyfile(td / (key + ".png"), ROOT / "png" / (key + ".png"))
    print(f"{len(chosen)} figures verified" + (" (check only)" if a.check else " and published"))


if __name__ == "__main__":
    main()
