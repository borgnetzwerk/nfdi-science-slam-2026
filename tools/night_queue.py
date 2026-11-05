"""Render queue in a plain console window: runs long render jobs unattended, with clean and forced shutdown.

Works through the jobs of a jobs file (at most "parallel" at a time, each through blender_run.py):
- before starting: half-written images (aborted run, closed window) move to segments/_old/truncated, otherwise they would count as done
- if a run crashes, it restarts up to "retries" times; segment mode continues with the missing images
- every five minutes progress and an estimate; for each finished piece small JPEG previews (every Nth frame and the last one)
  go to the preview folder, so progress can be seen without opening the render folder
- log under _scratch/night_queue_<date>.log
Paths in the jobs file are absolute or relative to the repository root. Commands typed into the window:
    clean      start no new runs, let running ones finish, then stop
    shutdown   stop at once (finished images stay)
    status     progress and estimate now
Closing the window is like shutdown. The script does not shut down the machine.

Usage from the repository root, in its own console window:
    python tools/night_queue.py --jobs <night_queue.yaml>
"""
import argparse
import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(__file__).resolve().parent.parent   # repository root

HINT = "Commands: clean = let running jobs finish, then stop | shutdown = stop now | status = progress"


def local(value):
    """Path from the jobs file: absolute or relative to the repository root."""
    if re.match(r"^[a-z_]+:[^\\/]", value):
        raise SystemExit(f"{value}: root-style path is not supported here; use a local folder")
    path = Path(value)
    return path if path.is_absolute() else BASE / path


def log(handle, text):
    line = f"{datetime.now():%H:%M:%S} {text}"
    print(line, flush=True)
    handle.write(line + "\n")
    handle.flush()


def stop(proc):
    """Stop a run together with its Blender child process (blender_run.py starts Blender as a separate process; Windows)."""
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)


def pieces(out_dir):
    for folder in sorted((out_dir / "segments").glob("*/")):
        if not folder.name.startswith("_"):
            yield folder


def remove_truncated(out_dir, handle):
    """Take images that an abort left half-written out of the pieces (move, never delete)."""
    moved = 0
    for folder in pieces(out_dir):   # an abort only hits the most recently written image of each piece
        newest = sorted(folder.glob("f_*.png"), key=lambda p: p.stat().st_mtime)[-2:]
        for png in newest:
            try:
                with Image.open(png) as img:
                    img.load()
            except Exception:
                target = out_dir / "segments" / "_old" / "truncated"
                target.mkdir(parents=True, exist_ok=True)
                png.replace(target / f"{folder.name}_{png.name}")
                moved += 1
    log(handle, f"Checked pieces: {moved} half-written images moved to _old/truncated")


def frame_ranges(jobs, out_dir):
    """Frame ranges of the jobs by panel name, resolved like station_scene.py does (end of the stop before to end of the last)."""
    check = out_dir / "ride_check.json"
    if not check.exists():
        return []
    stops = json.loads(check.read_text(encoding="utf-8"))["stops"]
    bounds = {s["name"]: (stops[k - 1]["frame"] if k else s["arrive"], s["frame"]) for k, s in enumerate(stops)}
    ranges = []
    for job in jobs:
        # several ranges separated by commas, and frame numbers instead of panel names (otherwise "03.4:06.4,7321:8523"
        # reported "ride still being computed" for hours while the job was rendering)
        m = re.search(r"--frame-range (\S+)", job["args"])
        for part in (m[1].split(",") if m else []):
            a, _, b = part.partition(":")
            lo = bounds[a][0] + 1 if a in bounds else int(a) if a.isdigit() else None
            hi = bounds[b][1] if b in bounds else int(b) if b.isdigit() else None
            if lo is not None and hi is not None:
                ranges.append((lo, hi))
    return sorted(set(ranges))   # two jobs with --shard name the same range


def progress(ranges, out_dir, preview_dir, every):
    """Finished images inside the ranges; for finished pieces previews (every Nth and the last) as small JPEGs."""
    count = 0
    for folder in pieces(out_dir):
        frames = sorted(int(p.stem[2:]) for p in folder.glob("f_*.png"))
        count += sum(any(a <= n <= b for a, b in ranges) for n in frames)
        meta = folder / "segment.json"
        if not meta.exists() or len(frames) < json.loads(meta.read_text(encoding="utf-8"))["frames"]:
            continue
        target = preview_dir / folder.name
        for n in [f for f in frames if f % every == 0] + frames[-1:]:
            jpg = target / f"f_{n:04d}.jpg"
            if not jpg.exists():
                target.mkdir(parents=True, exist_ok=True)
                with Image.open(folder / f"f_{n:04d}.png") as img:
                    img.convert("RGB").resize((960, 540)).save(jpg, quality=85)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jobs", required=True, help="jobs file (YAML: out, preview, parallel, retries, preview_every, jobs)")
    args = parser.parse_args()
    plan = yaml.safe_load(Path(args.jobs).read_text(encoding="utf-8"))
    out_dir, preview_dir = local(plan["out"]), local(plan["preview"])
    parallel, retries, every = int(plan.get("parallel", 2)), int(plan.get("retries", 2)), int(plan.get("preview_every", 300))
    all_jobs = [dict(j, tries=0) for j in plan["jobs"]]   # insert {out} only after splitting: the path may contain spaces
    jobs = list(all_jobs)
    state = {"mode": "run", "status": False}

    def read_input():
        for line in sys.stdin:
            word = line.strip().lower()
            if word in ("clean", "shutdown"):
                state["mode"] = word
            elif word == "status":
                state["status"] = True
            elif word:
                print(HINT, flush=True)

    threading.Thread(target=read_input, daemon=True).start()
    (BASE / "_scratch").mkdir(exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = []   # (time, finished images) for the estimate
    with open(BASE / "_scratch" / f"night_queue_{datetime.now():%Y%m%d_%H%M}.log", "a", encoding="utf-8") as handle:
        log(handle, f"{len(jobs)} jobs, {parallel} at a time, pieces in {out_dir}, previews in {preview_dir}")
        log(handle, HINT)
        remove_truncated(out_dir, handle)
        running, last_report = [], 0
        while jobs or running:
            if state["mode"] == "shutdown":
                for job, proc, out, _ in running:
                    stop(proc)
                    out.close()
                    log(handle, f"stopped: {job['name']}")
                running, jobs = [], []
                break
            while jobs and len(running) < parallel and state["mode"] == "run":
                job = jobs.pop(0)
                job["tries"] += 1
                out = open(BASE / "_scratch" / f"night_{job['name']}.runlog", "a", encoding="utf-8")
                argv = [str(out_dir) if token == "{out}" else token for token in job["args"].split()]
                proc = subprocess.Popen([sys.executable, "tools/blender_run.py", *argv], cwd=BASE,
                                        stdout=out, stderr=subprocess.STDOUT)
                running.append((job, proc, out, time.time()))
                log(handle, f"Start {job['name']} (PID {proc.pid}, attempt {job['tries']})")
            if state["mode"] == "clean" and jobs:
                log(handle, f"clean: {len(jobs)} waiting jobs dropped, running ones finish")
                jobs = []
            for entry in list(running):
                job, proc, out, started = entry
                if proc.poll() is not None:
                    out.close()
                    running.remove(entry)
                    log(handle, f"End {job['name']}: return code {proc.returncode}, {(time.time() - started) / 60:.0f} min")
                    if proc.returncode != 0 and job["tries"] <= retries and state["mode"] == "run":
                        log(handle, f"{job['name']} queued again (crash; continues with the missing images)")
                        jobs.insert(0, job)
            if state["status"] or time.time() - last_report > 300:
                state["status"], last_report = False, time.time()
                ranges = frame_ranges(all_jobs, out_dir)
                if ranges:
                    total, done = sum(b - a + 1 for a, b in ranges), progress(ranges, out_dir, preview_dir, every)
                    samples.append((time.time(), done))
                    window = [s for s in samples if s[0] > time.time() - 1800] or samples
                    rate = (window[-1][1] - window[0][1]) / max(1, window[-1][0] - window[0][0])   # images per second
                    eta = f"done about {datetime.now() + timedelta(seconds=(total - done) / rate):%H:%M}" if rate > 0 else "estimate follows"
                    log(handle, f"Progress: {done} of {total} images ({100 * done / total:.0f} %), {rate * 60:.1f} images/min, {eta}")
                else:
                    log(handle, "Progress: ride still being computed")
                print(HINT, flush=True)
            time.sleep(5)
        log(handle, "Queue empty. The machine can be switched off.")
        input("Press Enter to close the window.")


if __name__ == "__main__":
    main()
