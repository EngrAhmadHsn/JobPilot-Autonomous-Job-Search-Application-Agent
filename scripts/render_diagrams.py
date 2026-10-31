"""Render the PlantUML diagrams in docs/diagrams to PNG.

The diagram sources are the record; the PNGs are the build output. A reviewer
only needs the PNGs, which are committed. Changing a diagram needs PlantUML.

The tool is looked for in this order:

    1. the PLANTUML_JAR environment variable
    2. tools/plantuml.jar in this repository
    3. plantuml on the PATH

A diagram is only useful in the document if its text is readable at the size
the document prints it. The text is 13 points in the source, so a diagram that
is naturally W inches wide prints at 13 * 6 / W points on a six inch column. A
diagram wider than about eleven inches therefore cannot be read, and the check
below refuses it.

Usage:

    python scripts/render_diagrams.py            # render every source
    python scripts/render_diagrams.py --check    # render and report, no write
    python scripts/render_diagrams.py erd-data   # render one source
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO / "docs" / "diagrams"
OUTPUT_DIR = SOURCE_DIR / "png"
LOCAL_JAR = REPO / "tools" / "plantuml.jar"

# The document prints a diagram six inches wide. A diagram naturally wider than
# this prints its thirteen point text too small to read.
COLUMN_INCHES = 6.0
FIGURE_HEIGHT_INCHES = 7.2
BODY_POINT_SIZE = 13
MIN_SCALE = 0.55
RENDER_DPI = 96
RENDER_DPI = 96


def find_plantuml() -> list[str]:
    """Return the command that runs PlantUML, or raise with what to do about it."""
    jar = os.environ.get("PLANTUML_JAR")
    if jar:
        path = Path(jar)
        if not path.is_file():
            raise SystemExit(f"PLANTUML_JAR points at {jar}, which is not a file.")
        return ["java", "-Dfile.encoding=UTF-8", "-jar", str(path)]

    if LOCAL_JAR.is_file():
        return ["java", "-Dfile.encoding=UTF-8", "-jar", str(LOCAL_JAR)]

    on_path = shutil.which("plantuml")
    if on_path:
        return [on_path]

    raise SystemExit(
        "PlantUML was not found.\n"
        "  Install it, then point this script at it:\n"
        "    set PLANTUML_JAR=<path to plantuml.jar>\n"
        "  or drop the jar at tools/plantuml.jar, or put plantuml on the PATH.\n"
        "  The jar is a build tool and is not committed to the repository."
    )


def sources() -> list[Path]:
    return sorted(p for p in SOURCE_DIR.glob("*.puml") if not p.name.startswith("_"))


def measure(png: Path) -> tuple[float, float]:
    from PIL import Image

    with Image.open(png) as image:
        return image.size[0] / RENDER_DPI, image.size[1] / RENDER_DPI


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="render only these sources, by stem")
    parser.add_argument(
        "--check", action="store_true", help="render to a temporary folder and report"
    )
    args = parser.parse_args()

    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"no diagram sources at {SOURCE_DIR}")

    wanted = sources()
    if args.names:
        wanted = [p for p in wanted if p.stem in args.names]
        if not wanted:
            raise SystemExit(f"no source matched {args.names}")

    command = find_plantuml()

    output = OUTPUT_DIR
    if args.check:
        import tempfile

        output = Path(tempfile.mkdtemp(prefix="plantuml-check-"))
    else:
        output.mkdir(parents=True, exist_ok=True)

    # PlantUML resolves a relative output path against its own working
    # directory, so it is given an absolute one.
    result = subprocess.run(
        command + ["-tpng", "-charset", "UTF-8", "-o", str(output)] + [str(p) for p in wanted],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode

    unreadable = []
    for source in wanted:
        png = output / f"{source.stem}.png"
        if not png.is_file():
            sys.stderr.write(f"no image was produced for {source.name}" + chr(10))
            return 1
        width, height = measure(png)
        scale = min(COLUMN_INCHES / width, FIGURE_HEIGHT_INCHES / height, 1.0)
        point = BODY_POINT_SIZE * scale
        flag = ""
        if scale < MIN_SCALE:
            flag = "  UNREADABLE"
            unreadable.append(source.stem)
        print(
            f"{source.name:<34} {width:5.1f} x {height:4.1f} in"
            f"   prints at {width * scale:4.1f} x {height * scale:4.1f} in,"
            f" text {point:4.1f} pt{flag}"
        )
        if not args.check:
            print(f"{'':<34} -> {png.relative_to(REPO)}")

    if unreadable:
        sys.stderr.write(
            "These diagrams print too small to read in the document; "
            "split them or make them wider:" + chr(10) + "  "
            + (chr(10) + "  ").join(unreadable)
            + chr(10)
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
