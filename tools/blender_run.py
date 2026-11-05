"""Runs Blender without a user interface with one of the scene scripts.

Usage (from the repository root):
    python tools/blender_run.py station_scene.py ...    build and render the scene (script from scripts/scene/)
    python tools/blender_run.py --version               show the installed Blender version

Blender's own Python has no PyYAML, so this runner reads scripts/data/config.yaml and passes the values
as JSON after "--" to the Blender script.
"""
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")

SCRIPTS = Path(__file__).resolve().parent
BASE = SCRIPTS.parent  # repository root; relative paths in the settings start here
SCENE = BASE / "scripts" / "scene"
DATA = BASE / "scripts" / "data"


def load_config():
    return yaml.safe_load((DATA / "config.yaml").read_text(encoding="utf-8"))


def resolve(raw):
    """Expand environment variables; paths without a root are relative to the repository root."""
    path = Path(os.path.expanduser(os.path.expandvars(raw)))
    return path if path.is_absolute() else (BASE / path).resolve()


def find_blender(config):
    root = resolve(config["blender"]["root"])
    candidates = []
    for folder in root.glob("Blender *"):
        exe = folder / "blender.exe"
        match = re.match(r"Blender (\d+)\.(\d+)", folder.name)
        if exe.exists() and match:
            candidates.append(((int(match[1]), int(match[2])), exe))
    if not candidates:
        sys.exit(f"No Blender installation found under {root}.")
    return max(candidates)[1]


def main():
    config = load_config()
    blender = find_blender(config)
    if len(sys.argv) < 2 or sys.argv[1] == "--version":
        subprocess.run([str(blender), "--version"], check=True)
        return
    script = SCENE / sys.argv[1]
    extra = sys.argv[2:]
    # Optionally open an existing scene (for example to check it with check_motion.py).
    blend = []
    if "--blend" in extra:
        index = extra.index("--blend")
        blend = [str(resolve(extra[index + 1]))]
        extra = extra[:index] + extra[index + 2:]
    # Resolve paths up front so the Blender script needs no knowledge of the folder layout.
    for section in config.values():
        if isinstance(section, dict):
            for key in ("output", "slide_image", "figure_image"):
                if key in section:
                    section[key] = str(resolve(section[key]))
    # Optionally pass the station block of building.yaml (Blender itself reads no YAML).
    if "--building" in extra:
        extra.remove("--building")
        # building.yaml with the state of the station planner (depth, processes, fittings from station_plan.json)
        sys.path.insert(0, str(SCENE))
        import station_source  # noqa: E402
        config["station"] = station_source.load_station()
        cells = DATA / "hub_layout_cells.yaml"   # honeycomb grid of the hub
        if cells.exists():
            config["hub_cells"] = yaml.safe_load(cells.read_text(encoding="utf-8"))
    # Optionally a storyboard: panels and placeholders as JSON, image paths relative to the repository root.
    if "--storyboard" in extra:
        index = extra.index("--storyboard")
        # Render the slides of a PowerPoint deck onto their panels, only when the deck changed; skipped when the
        # helper is not available
        try:
            import render_slide_boards
        except ImportError:
            render_slide_boards = None
        if render_slide_boards is not None:
            render_slide_boards.sync(resolve(extra[index + 1]))
        board = yaml.safe_load(resolve(extra[index + 1]).read_text(encoding="utf-8"))
        for item in board.get("placeholders", []) + [p for s in board.get("scenes", []) for p in s.get("panels", [])]:
            for key in ("image", "image_override", "left", "right", "back_image"):
                if item.get(key):
                    item[key] = str(resolve(item[key]))
            if item.get("book"):   # double page of the book on the lectern: [left, right]
                item["book"] = [str(resolve(p)) for p in item["book"]]
        board["output"] = str(resolve("_scratch/storyboard"))
        if "--out" in extra:   # own output folder, for example for comparison images
            out_index = extra.index("--out")
            board["output"] = str(resolve(extra[out_index + 1]))
            extra = extra[:out_index] + extra[out_index + 2:]
        Path(board["output"]).mkdir(parents=True, exist_ok=True)
        board_file = Path(board["output"]) / "storyboard.json"   # as a file: the Windows command line is too short for it
        board_file.write_text(json.dumps(board), encoding="utf-8")
        config["storyboard_file"] = str(board_file)
        extra = extra[:index] + extra[index + 2:]
    if "--museum-scale" in extra:   # compare sizes of the museum
        index = extra.index("--museum-scale")
        config["museum_scale"] = float(extra[index + 1])
        extra = extra[:index] + extra[index + 2:]
    if "--doors" in extra:   # compare door dimensions: name=value,...
        index = extra.index("--doors")
        def value(text):   # number or word (entrance_style=canopy)
            try:
                return float(text)
            except ValueError:
                return text
        config["museum_doors"] = {k: value(v) for k, v in (pair.split("=") for pair in extra[index + 1].split(","))}
        extra = extra[:index] + extra[index + 2:]
    payload = json.dumps(config)
    if len(payload) > 20000:   # the Windows command line ends at 32 767 characters: write the settings to a file per run
        # (parallel runs) and pass only its path; the scene scripts load it via config_file
        config_dir = BASE / "_scratch" / "blender_run"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"config_{os.getpid()}_{int(time.time())}.json"
        config_path.write_text(payload, encoding="utf-8")
        payload = json.dumps({"config_file": str(config_path)})
    # Limit CPU threads so the machine stays usable
    threads = []
    if "--threads" in extra:
        index = extra.index("--threads")
        threads = ["-t", extra[index + 1]]
        extra = extra[:index] + extra[index + 2:]
    command = [str(blender), "-b", *blend, "--factory-startup", *threads, "--python-exit-code", "1",
               "-P", str(script), "--", payload, *extra]
    print(f"Blender: {blender}")
    # Optional shared GPU queue (gpu_queue module, not part of this repository): waits until this run gets a slot.
    # --gpu-task <label> and --gpu-minutes N are for its log and time limit; without the module Blender starts directly.
    gpu = {}
    for flag in ("--gpu-task", "--gpu-minutes"):
        if flag in command:
            index = command.index(flag)
            gpu[flag] = command[index + 1]
            command = command[:index] + command[index + 2:]
    try:
        import gpu_queue
    except ImportError:
        gpu_queue = None
    label = " ".join(filter(None, [script.name, Path(config.get("storyboard_file", "")).parent.name or None]))
    if gpu_queue is None:
        start = time.perf_counter()
        result = subprocess.run(command)
        seconds = time.perf_counter() - start
    else:
        # Bypass the queue for runs that barely load the GPU: check runs without rendering (--no-render without
        # --segments) and short probes (--gpu-minutes at most 1), but only with enough free RAM, since a run without
        # rendering still builds the whole scene (up to about 10 GB)
        ram_free = gpu_queue.measure()["ram_free_gb"]
        quick = ("--no-render" in command and "--segments" not in command and ram_free >= 5) \
            or (float(gpu.get("--gpu-minutes", 99)) <= 1 and ram_free >= 4)
        with (contextlib.nullcontext() if quick else
              gpu_queue.slot(task=gpu.get("--gpu-task"), label=label, minutes=gpu.get("--gpu-minutes"))) as outcome:
            start = time.perf_counter()
            result = subprocess.CompletedProcess(command, gpu_queue.run_command(command))
            seconds = time.perf_counter() - start
            if outcome is not None:
                outcome["returncode"] = result.returncode
    print(f"Total run time: {seconds:.1f} s, return code {result.returncode}")
    entry = {"date": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": "blender_run", "script": script.name,   # every run is
             "storyboard": Path(config.get("storyboard_file", "")).parent.name or None, "seconds": round(seconds, 1),   # logged,
             "returncode": result.returncode}   # for the render-time figures of the making-of
    (BASE / "_scratch").mkdir(exist_ok=True)
    with (BASE / "_scratch" / "render_runs.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
