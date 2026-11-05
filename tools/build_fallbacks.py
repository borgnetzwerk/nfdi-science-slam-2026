"""Fallback versions of a built deck: one video and one PowerPoint with still images.

Usage: python tools/build_fallbacks.py <deck folder> <name without extension>
Reads pieces.json of the deck (build_pptx.py, from_pieces) and writes into the deck folder:
- <name>.mp4: all clips in slide order plus the closing loop, without re-encoding (they are encoded alike)
- <name>_stills.pptx: one slide per click with the image the clip ends on (arrival at the stop), the start image before it;
  for clicking through without video
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.util import Emu

sys.stdout.reconfigure(encoding="utf-8")
deck = Path(sys.argv[1]).resolve()
name = sys.argv[2]
pieces = json.loads((deck / "pieces.json").read_text(encoding="utf-8"))
clips = pieces["clips"]

# Video
listing = deck / f"{name}_list.txt"
files = [c["clip"] for c in clips] + (["schluss_schleife.mp4"] if (deck / "schluss_schleife.mp4").exists() else [])
listing.write_text("".join(f"file '{f}'\n" for f in files), encoding="utf-8")
video = deck / f"{name}.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(video)],
               cwd=deck, check=True)

# Stills: start image and the last image of each clip, scaled to 1920 x 1080 (preview pieces are smaller)
stills = deck / f"{name}_stills"
stills.mkdir(exist_ok=True)
images = [clips[0]["first"]] + [c["last"] for c in clips]
prs = Presentation()
prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
blank = prs.slide_layouts[6]
for k, source in enumerate(images):
    target = stills / f"still_{k:02d}.jpg"
    Image.open(source).convert("RGB").resize((1920, 1080), Image.LANCZOS).save(target, quality=92)
    slide = prs.slides.add_slide(blank)
    slide.shapes.add_picture(str(target), 0, 0, prs.slide_width, prs.slide_height)
    if k:
        slide.notes_slide.notes_text_frame.text = f"{clips[k - 1]['from']} to {clips[k - 1]['to']} ({clips[k - 1]['quality']})"
out = deck / f"{name}_stills.pptx"
prs.save(out)
print(video)
print(out, len(images), "slides")
