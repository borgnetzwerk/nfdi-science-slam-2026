"""Apply the published object renames (public_renames.yaml) to script and data files.

Usage: python tools/apply_renames.py <file> [<file> ...]
"""
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")
RENAMES = yaml.safe_load((Path(__file__).parent / "_work" / "public_renames.yaml").read_text(encoding="utf-8"))["renames"]

for name in sys.argv[1:]:
    path = Path(name)
    text = path.read_text(encoding="utf-8")
    counts = []
    for r in RENAMES:
        counts.append(text.count(r["old"]))
        text = text.replace(r["old"], r["new"])
    path.write_text(text, encoding="utf-8", newline="")
    print(f"{path.name}: {sum(counts)} replaced")
