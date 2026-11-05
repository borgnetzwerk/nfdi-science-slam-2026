"""Inside Blender: fail if the open .blend file carries local paths or names of the machine it was made on.

Usage: run Blender in background on a .blend file with this script (the command is in tools/README.md).
Checks (1) the file paths of images, fonts, libraries and other data, including the paths stored inside packed data,
and (2) the raw, decompressed bytes of the file for drive letters and folder names that must not be published
(UI data such as file browsers also lands there). Prints one line per finding; exit code 1 if there is any.
"""
import re
import sys

import bpy

from pathlib import Path

# a drive letter only counts when a folder name follows (random binary data contains "q:/" by chance); words that would
# themselves reveal something (user or folder names) go one per line into tools/_work/private_patterns.txt, which is not published
PATTERNS = [rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/][A-Za-z0-9 _.\-]{2,}[\\/]", rb"\\Users\\", rb"/Users/", rb"/home/", rb"_scratch"]
private = Path(__file__).resolve().parent / "_work" / "private_patterns.txt"
if private.exists():
    PATTERNS += [re.escape(line.strip().encode("utf-8")) for line in private.read_text(encoding="utf-8").splitlines() if line.strip()]
FORBIDDEN = re.compile(b"|".join(PATTERNS))
found = []
for collection in (bpy.data.images, bpy.data.fonts, bpy.data.libraries, bpy.data.sounds, bpy.data.movieclips, bpy.data.cache_files):
    for block in collection:
        path = getattr(block, "filepath", "") or ""
        if path and path != "<builtin>" and not path.startswith("//"):
            found.append(f"{type(block).__name__} {block.name}: {path}")
        for packed in getattr(block, "packed_files", []) or []:
            if packed.filepath and not packed.filepath.startswith("//"):
                found.append(f"packed {type(block).__name__} {block.name}: {packed.filepath}")

raw = open(bpy.data.filepath, "rb").read()
if raw[:4] == b"\x28\xb5\x2f\xfd":   # zstd-compressed .blend
    import zstandard
    raw = zstandard.ZstdDecompressor().stream_reader(raw).read()
for hit in sorted({m.group(0) for m in FORBIDDEN.finditer(raw)}):
    start = raw.find(hit)
    context = raw[max(0, start - 40): start + 60].decode("utf-8", "replace").replace("\x00", " ")
    found.append(f"bytes {hit.decode('utf-8', 'replace')!r}: ...{context}...")

for line in found:
    print("FOUND", line)
print(f"{bpy.data.filepath}: {len(found)} findings", flush=True)
sys.exit(1 if found else 0)
