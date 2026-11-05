"""Cut a built station scene into modules: reads modules.yaml and a Poly Haven list, starts Blender with split_scene.py.

Usage:
    python tools/run_split.py <station.blend> <output folder> --polyhaven <polyhaven.yaml> [--blender <path to blender>]

Blender renders nothing here (open, remove, save, export), so no GPU is needed.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent


def find_blender():
    """Highest installed Blender under the usual Windows folder, else `blender` on PATH."""
    root = Path(os.path.expandvars("%ProgramFiles%/Blender Foundation"))
    found = []
    for folder in root.glob("Blender *"):
        hit = re.match(r"Blender (\d+)\.(\d+)", folder.name)
        if hit and (folder / "blender.exe").exists():
            found.append(((int(hit[1]), int(hit[2])), folder / "blender.exe"))
    if found:
        return max(found)[1]
    on_path = shutil.which("blender")
    if on_path:
        return Path(on_path)
    sys.exit("Blender not found; pass --blender.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("out")
    parser.add_argument("--polyhaven", required=True)
    parser.add_argument("--blender")
    parser.add_argument("--threads", default="2")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    modules = yaml.safe_load((HERE / "modules.yaml").read_text(encoding="utf-8"))
    polyhaven = yaml.safe_load(Path(args.polyhaven).read_text(encoding="utf-8"))
    config = {"source": str(Path(args.source).resolve()), "out": str(out), "modules": modules["modules"],
              "transform_roots": modules.get("transform_roots", []),
              "withhold_images": modules.get("withhold_images", []),
              "withhold_objects": modules.get("withhold_objects", []),
              "renames": yaml.safe_load((HERE / "_work" / "public_renames.yaml").read_text(encoding="utf-8"))["renames"],
              "polyhaven_ids": [a["id"] for a in polyhaven["assets"]]}
    # the run config holds local paths, so it stays in tools/_work/ (ignored by git), not next to the output
    config_path = HERE / "_work" / "split_config.json"
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    blender = Path(args.blender) if args.blender else find_blender()
    command = [str(blender), "-b", "--factory-startup", "-t", args.threads, "--python-exit-code", "1",
               "-P", str(HERE / "split_scene.py"), "--", str(config_path)]
    sys.exit(subprocess.run(command).returncode)


if __name__ == "__main__":
    main()
