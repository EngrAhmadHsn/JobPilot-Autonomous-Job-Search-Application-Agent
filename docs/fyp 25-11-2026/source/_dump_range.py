from pathlib import Path
import json

p = Path(".scratch/fyp-20261125/full/SRS-full.txt")
for l in p.read_text(encoding="utf-8").splitlines():
    i = int(l.split("\t")[0])
    if 236 <= i <= 465:
        print(l[:300])
