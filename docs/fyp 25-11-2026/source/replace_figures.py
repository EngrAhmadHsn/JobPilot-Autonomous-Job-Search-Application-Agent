"""Swap embedded figures inside copies of the university documents.

The image at a given relationship id is replaced byte-for-byte with a new PNG of
the same aspect ratio. Paragraphs, captions, alt text, sizes and all other
content are untouched. The mapping is explicit so no image slot is guessed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from PIL import Image


def replace_images(docx: Path, out: Path, mapping: dict[str, Path]):
    doc = Document(docx)
    blips = {}
    for body in doc.element.body.iter():
        for blip in body.findall(qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if rid:
                blips[rid] = True
    unknown = set(mapping) - set(blips)
    if unknown:
        raise SystemExit(f"Relationship ids not present in {docx}: {sorted(unknown)}")
    rels = doc.part.rels
    replacements: dict[str, tuple[Path, str]] = {}
    for rid, path in mapping.items():
        rel = rels[rid]
        old_name = Path(str(rel.target_ref)).name
        path = Path(path)
        if not path.is_file():
            raise SystemExit(f"Missing replacement: {path}")
        with Image.open(path) as image:
            w, h = image.size
        # Read the old image from the package to compare aspect ratios.
        with ZipFile(docx) as z:
            old = z.read(f"word/media/{old_name}")
        import io

        with Image.open(io.BytesIO(old)) as old_image:
            ow, oh = old_image.size
        old_ratio, new_ratio = ow / oh, w / h
        if abs(old_ratio - new_ratio) / old_ratio > 0.02:
            # Keep the width of the original drawing box and set its height from
            # the new aspect ratio. This prevents Word from stretching the new
            # PlantUML render into the old box.
            for blip in doc.element.body.iter(qn("a:blip")):
                if blip.get(qn("r:embed")) != rid:
                    continue
                inline = blip.getparent()
                while inline is not None and inline.tag != qn("wp:inline"):
                    inline = inline.getparent()
                if inline is None:
                    continue
                extent = inline.find(qn("wp:extent"))
                if extent is not None:
                    old_w = int(extent.get("cx"))
                    old_h = int(extent.get("cy"))
                    # Keep the original width, but cap height to a page figure.
                    new_w = min(old_w, round(5.6 * 914400 * w / h))
                    new_h = round(new_w * h / w)
                    extent.set("cx", str(new_w))
                    extent.set("cy", str(new_h))
                    print(f"{rid}: box {new_w / 914400:.2f} x {new_h / 914400:.2f} in")
                for tag, attr in (("a:ext", "cy"), ("a:ext", "cx")):
                    for child in inline.iter(qn(tag)):
                        if attr == "cy":
                            child.set(attr, str(round(int(extent.get("cx")) * h / w)))
                        else:
                            child.set(attr, str(extent.get("cx")))
        ext = path.suffix.lower().lstrip(".") or "png"
        replacements[old_name] = (path, ext)

    out.parent.mkdir(parents=True, exist_ok=True)
    # Save document.xml (with the resized drawing boxes) into a staging copy,
    # then swap the media bytes in that copy.
    staged = out.with_name(out.stem + ".staged.docx")
    doc.save(staged)
    with ZipFile(staged) as src, ZipFile(out, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            name = Path(item.filename).name
            if name in replacements:
                data = replacements[name][0].read_bytes()
            dst.writestr(item, data)
    staged.unlink()
    return len(replacements)


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("docx", type=Path)
    a.add_argument("mapping", type=Path)
    a.add_argument("--out", type=Path, required=True)
    args = a.parse_args()
    n = replace_images(args.docx, args.out, json.loads(args.mapping.read_text()))
    print(f"{args.out}: {n} figures replaced")
