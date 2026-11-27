"""Check the FYP Word editions, figure sources and evidence against the baseline.

    python source/check_package.py [--dir <published>] [--rev 7190151]

Read-only. Reports a non-zero exit when a required part, marker, figure or
evidence path is missing. Page numbers are checked by eye from the rendered PDF.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

PACK = Path(__file__).resolve().parents[1]
SRC = PACK / "source"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def word_parts(docx: Path) -> tuple[set[str], str]:
    with ZipFile(docx) as z:
        names = set(z.namelist())
        doc = z.read("word/document.xml").decode("utf-8")
    return names, doc


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--dir", type=Path, default=PACK)
    a.add_argument("--rev", default="7190151")
    args = a.parse_args()
    problems: list[str] = []
    try:
        tracked = set(
            subprocess.check_output(
                ["git", "ls-tree", "-r", "--name-only", args.rev], text=True, cwd=PACK.parents[1]
            ).splitlines()
        )
    except Exception as exc:  # a checkout may be absent; then only note it
        tracked = set()
        problems.append(f"cannot list git revision {args.rev}: {exc}")

    # 1. Figure sources, renders and manifests agree.
    sources = {p.stem for p in (PACK / "diagrams").glob("[!_]*.puml")}
    renders = {p.stem for p in (PACK / "diagrams" / "png").glob("*.png")}
    manifest: dict[str, dict] = {}
    for name in ("structure-figures.json", "behavior-figures.json", "plates.json"):
        manifest.update(json.loads((SRC / name).read_text(encoding="utf-8")))
    for stem, entry in manifest.items():
        for key in ("type", "caption", "alt", "evidence"):
            if key not in entry:
                problems.append(f'{stem}: manifest missing "{key}"')
        for path in entry.get("evidence", []):
            if tracked and path not in tracked:
                problems.append(f"{stem}: evidence path not at {args.rev}: {path}")
        if entry["type"].startswith("Recorded") and not entry.get("provenance"):
            problems.append(f"{stem}: a recorded capture needs provenance")
    stems = set(manifest)
    if not sources <= stems:
        problems.append(
            "diagram sources without manifest entry: " + ", ".join(sorted(sources - stems))
        )

    # 2. Registers: every requirement id is unique with a group and status.
    reqs = json.loads((SRC / "requirements.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in reqs]
    if len(ids) != len(set(ids)):
        problems.append("duplicate requirement ids in the register")
    for r in reqs:
        if r["status"] not in ("Implemented", "Limited", "Deferred"):
            problems.append(f"{r['id']}: unexpected status {r['status']!r}")
        if r["test"] and tracked and r["test"] not in tracked:
            problems.append(f"{r['id']}: evidence path not at {args.rev}: {r['test']}")

    # 3. Manuscript markers resolve to a known figure and one requirements block per group.
    per_doc: dict[str, list[str]] = {}
    for kind in ("srs", "sdd"):
        text = (SRC / f"{kind}.md").read_text(encoding="utf-8")
        figures = re.findall(r"(?m)^@figure\s+([\w-]+)\s*$", text)
        plates = re.findall(r"(?m)^@plate\s+([\w-]+)\s*$", text)
        used = figures + plates
        per_doc[kind] = used
        if len(used) != len(set(used)):
            problems.append(f"{kind}.md: a figure marker repeats")
        for key in figures:
            if key not in manifest:
                problems.append(f"{kind}.md: @figure {key} has no manifest entry")
            if not (PACK / "diagrams" / "png" / f"{key}.png").is_file():
                problems.append(f"{kind}.md: @figure {key} has no rendered PNG")
        for key in plates:
            if key not in manifest:
                problems.append(f"{kind}.md: @plate {key} has no manifest entry")
            if not (PACK / "ui" / f"{key}.png").is_file():
                problems.append(f"{kind}.md: @plate {key} has no image in ui/")
        for ref in re.findall(r"\{fig:([\w-]+)\}", text):
            if ref not in used:
                problems.append(f"{kind}.md: {{fig:{ref}}} has no marker")
        for group in re.findall(r"(?m)^@requirements\s+(\d+)\s*$", text):
            if not any(int(r["group"]) == int(group) for r in reqs):
                problems.append(f"{kind}.md: @requirements {group} is empty")

    # 4. Each Word edition embeds its own marker images and keeps a live contents field.
    for kind in ("SRS", "SDD"):
        docx = args.dir / f"{kind}.docx"
        if not docx.is_file():
            problems.append(f"{kind}.docx is absent from {args.dir}")
            continue
        names, doc = word_parts(docx)
        if "word/settings.xml" in names:
            settings = etree.fromstring(ZipFile(docx).read("word/settings.xml"))
            if settings.find(W + "updateFields") is None:
                problems.append(f"{kind}.docx: fields are not set to update on open")
        if not re.search(r"(?ms)w:instrText[^>]*>\s*TOC[^<]*", doc):
            problems.append(f"{kind}.docx: no contents or figure-list field found")
        text = re.sub(r"<[^>]+>", "", doc)
        for key in per_doc[kind.lower()]:
            head = manifest[key]["caption"].split(":")[0].strip()
            if head.lower() not in text.lower():
                problems.append(f"{kind}.docx: caption not found for figure {key}")

    if problems:
        print("FAILED checks:")
        for p in problems:
            print("  - " + p)
        return 1
    print(f"All package checks passed for {args.dir} at {args.rev}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
