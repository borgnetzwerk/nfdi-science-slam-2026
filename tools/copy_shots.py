"""Copy the chosen making-of shots into making-of/images/ (resized, cropped as on the wall) and print a list.

Usage:
    python tools/copy_shots.py --register making_of.yaml --base <folder the register paths start from> --root <root for "repo:" paths>
                               [--sheet <contact sheet.png>]

Only shots with chosen: true are copied. Images are scaled to at most 1920 px wide and saved as JPEG.
"""
import argparse
import sys
from pathlib import Path

import yaml
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parent.parent
MAX_WIDTH = 1920


def source_path(entry, base, root):
    file = entry["file"]
    return root / file[len("repo:"):] if file.startswith("repo:") else base / file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--sheet")
    parser.add_argument("--withhold", default="", help="shot ids not to copy, comma separated (e.g. images showing illustrations we may not license)")
    args = parser.parse_args()
    withheld = {s for s in args.withhold.split(",") if s}
    shots = yaml.safe_load(Path(args.register).read_text(encoding="utf-8"))["shots"]
    out = REPO / "making-of" / "images"
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for shot in shots:
        if shot.get("chosen") is not True or shot["id"] in withheld:
            continue
        image = Image.open(source_path(shot, Path(args.base), Path(args.root))).convert("RGB")
        if shot.get("crop_bottom"):
            image = image.crop((0, 0, image.width, round(image.height * (1 - shot["crop_bottom"]))))
        if image.width > MAX_WIDTH:
            image = image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)), Image.LANCZOS)
        name = f"{shot['date']}_{shot['id']}.jpg"
        image.save(out / name, quality=88)
        written.append((name, image))
        print(f"{name}  {image.width}x{image.height}  pair {shot.get('pair')}")
    if args.sheet and written:
        thumbs = [im.copy() for _, im in written]
        for t in thumbs:
            t.thumbnail((640, 400))
        cols = 3
        rows = (len(thumbs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 650, rows * 410), "white")
        for i, t in enumerate(thumbs):
            sheet.paste(t, ((i % cols) * 650 + 5, (i // cols) * 410 + 5))
        sheet.save(args.sheet, quality=80)


if __name__ == "__main__":
    main()
