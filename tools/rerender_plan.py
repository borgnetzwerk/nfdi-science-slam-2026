"""Frame-exact re-render: render only the images in which something changed; reuse everything else.

Steps (from the repository root):
1. Check run of the new scene without rendering, with the changed objects (semicolon separates; id, name:<part>, box:x0,y0,z0,x1,y1,z1):
       python tools/blender_run.py station_scene.py --building --storyboard scripts/data/storyboard_station.yaml --ride --no-render
           --changed-frames "r6_door;r7_open_curve" --out _scratch/check_<name> --gpu-minutes 20
   Result rerender_input.json (stops, pieces, images with a visible change) next to ride_path.json.
2. Plan:      python tools/rerender_plan.py --new _scratch/check_<name> --final <final render folder>
3. Apply:     python tools/rerender_plan.py --new _scratch/check_<name> --final <final render folder> --apply
4. The next final render with --segments fills exactly the gaps (missing images; render_segments skips existing ones).

For each image of the new ride the plan looks for a finished image with the same camera pose: first under the same number,
then shifted by the offset of the stops before and after it (timeline shifted, path the same: rename instead of re-render).
An image is rendered again if no pose matches (path changed) or a changed object is in the picture (rerender_input.json,
plus --margin images before and after).

--apply moves every affected piece as a whole to segments/_old/<name>_<time>/ (nothing is deleted) and places the reused
images as hard links (same drive, no extra space) under their new name in the new folder; segment.json gets the range and
fingerprint of the new path. Pieces without any change stay untouched. A piece in which an image was written within the last
--busy-minutes is not touched (a final render is running).

Limits: light and reflections of a changed object on neighbouring surfaces are not detected by the visibility check (use
--margin and box: for that); animations count as bound to the stops (videos from leg_start, doors), so a renamed image then
shows the same moment.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")
SCRIPTS = Path(__file__).resolve().parent
BASE = SCRIPTS.parent   # repository root

LOC_TOL, ROT_TOL = 2e-4, 2e-5   # same pose: location within 0.2 mm, quaternion per component (ride_path.json rounds to 4 and 5 places)


def load_path(folder):
    """ride_path.json of a run: frame number -> (x, y, z, w, qx, qy, qz)."""
    rows = json.loads((Path(folder) / "ride_path.json").read_text(encoding="utf-8"))
    return {int(r[0]): r[1:] for r in rows}


def fingerprint(path, first, last):
    """Like render_segments in station_scene.py: sha1 over the rounded path of the piece."""
    return hashlib.sha1(json.dumps([path[f] for f in range(first, last + 1)]).encode()).hexdigest()[:12]


def same_pose(a, b):
    if a is None or b is None:
        return False
    if any(abs(x - y) > LOC_TOL for x, y in zip(a[:3], b[:3])):
        return False
    q1, q2 = a[3:], b[3:]
    sign = 1 if sum(x * y for x, y in zip(q1, q2)) >= 0 else -1   # q and -q are the same rotation
    return all(abs(x - sign * y) <= ROT_TOL for x, y in zip(q1, q2))


def pieces_from_board(stops, total):
    """Pieces per click like segment_pieces in station_scene.py (for check runs without rerender_input.json)."""
    board = yaml.safe_load((BASE / "scripts" / "data" / "storyboard_station.yaml").read_text(encoding="utf-8"))
    clicks = {p["id"] for s in board.get("scenes", []) for p in s.get("panels", []) if p.get("click")}
    pieces, prev_name, prev_frame = [], "start", 0
    for s in stops:
        if s["name"] in clicks and not s.get("pass") and s["frame"] > prev_frame:
            pieces.append({"name": f"{prev_name}_{s['name']}", "end": s["name"], "first": prev_frame + 1, "last": s["frame"]})
            prev_name, prev_frame = s["name"], s["frame"]
    if prev_frame < total:
        pieces.append({"name": f"{prev_name}_end", "end": "end", "first": prev_frame + 1, "last": total})
    return pieces


def load_new(folder, margin, extra=None):
    folder = Path(folder)
    path = load_path(folder)
    source = folder / "rerender_input.json"
    if source.exists():
        data = json.loads(source.read_text(encoding="utf-8"))
        stops, pieces, visible = data["stops"], data["pieces"], data["visible"]
        checked = data.get("checked") or [[1, len(path)]]
        hub_turn, fps = data.get("hub_turn"), data.get("fps")
    else:   # check run without --changed-frames: path comparison only, no changed objects
        stops = json.loads((folder / "ride_check.json").read_text(encoding="utf-8"))["stops"]
        pieces, visible, checked, hub_turn, fps = pieces_from_board(stops, len(path)), {}, [[1, len(path)]], None, None
        print(f"Note: {source.name} missing, path comparison only (no changed objects)")
    for p in pieces:
        p.setdefault("fingerprint", fingerprint(path, p["first"], p["last"]))
    dirty = {}
    for label, frames in visible.items():
        m = (extra or {}).get(label, margin)   # own margin per target (--margin-for), for example when the check run's scene
        for f in frames:                       # was loaded shortly before the object's last change
            for g in range(f - m, f + m + 1):
                dirty.setdefault(g, set()).add(label)
    return {"path": path, "stops": stops, "pieces": pieces, "dirty": dirty, "checked": checked, "hub_turn": hub_turn,
            "fps": fps, "targets": list(visible)}


def load_old(final, extra_runs, fps=None, hub_turn=None):
    """Finished images: per piece folder the run path whose fingerprint matches segment.json (otherwise the pose is unknown)."""
    runs = []
    for folder in [final, *extra_runs]:
        if (Path(folder) / "ride_path.json").exists() and (Path(folder) / "ride_check.json").exists():
            runs.append({"folder": Path(folder), "path": load_path(folder),
                         "stops": json.loads((Path(folder) / "ride_check.json").read_text(encoding="utf-8"))["stops"]})
    frames, folders, unknown = {}, {}, []   # frames: (run, frame number) -> file
    for folder in sorted((Path(final) / "segments").iterdir()):
        meta_file = folder / "segment.json"
        if folder.name.startswith("_") or not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        run = next((k for k, r in enumerate(runs) if all(f in r["path"] for f in range(meta["first"], meta["last"] + 1))
                    and fingerprint(r["path"], meta["first"], meta["last"]) == meta["fingerprint"]), None)
        files = {int(p.stem[2:]): p for p in folder.glob("f_*.*") if p.stem[2:].isdigit()}
        newest = max((p.stat().st_mtime for p in files.values()), default=0)
        folders[folder.name] = {"folder": folder, "meta": meta, "run": run, "files": files, "newest": newest}
        if run is None or (fps and meta.get("fps") != fps):   # other frame rate: same pose, different moment
            unknown.append(folder.name)
            continue
        if hub_turn is not None and meta.get("hub_turn") is not None and abs(meta["hub_turn"] - hub_turn) > 1e-4:
            print(f"Warning: {folder.name} with hub turn {meta['hub_turn']}, new {hub_turn} (seam when the hub is in the picture)")
        for f, p in files.items():
            frames[(run, f)] = (folder.name, p)
    return runs, frames, folders, unknown


def offsets(f, new_stops, old_stops):
    """Offset new - old for image f: that of the last event before it (arrival or departure of a stop with the same name), else 0.
    Only this one: during a stop the camera stands still and every image of the stop has the same pose; an offset from another
    event would find an image from another moment (book page, video). Movement and animation run from the last event."""
    old = {s["name"]: s for s in old_stops}
    events = sorted((s[k], s[k] - old[s["name"]][k]) for s in new_stops if s["name"] in old for k in ("arrive", "frame"))
    before = [d for e, d in events if e <= f]
    return [before[-1] if before else 0]


def plan(new, runs, frames, folders):
    """Per new piece: keep images (same folder, same number), rename (other folder or number), new."""
    result = []
    checked = [tuple(r) for r in new["checked"]]
    for piece in new["pieces"]:
        rows = {"keep": [], "move": [], "new": [], "dirty": []}
        span = range(piece["first"], piece["last"] + 1)
        if not any(a <= f <= b for f in span for a, b in checked):   # piece entirely outside the visibility check: do not plan
            continue
        for f in span:
            if not any(a <= f <= b for a, b in checked):   # edge of a piece without visibility check: unknown, so new
                rows["new"].append(f)
                continue
            if f in new["dirty"]:
                rows["dirty"].append(f)
                continue
            found = None
            for k, run in enumerate(runs):
                for d in offsets(f, new["stops"], run["stops"]):
                    g = f - d
                    if (k, g) in frames and same_pose(run["path"].get(g), new["path"].get(f)):
                        found = (k, g)
                        break
                if found:
                    break
            if not found:
                rows["new"].append(f)
                continue
            name, source = frames[found]
            (rows["keep"] if name == piece["name"] and found[1] == f else rows["move"]).append((f, name, found[1], str(source)))
        unchecked = [f for f in range(piece["first"], piece["last"] + 1) if not any(a <= f <= b for a, b in checked)]
        result.append({**piece, **rows, "unchecked": len(unchecked)})
    return result


def touched(entry, folders):
    """Must the folder of this piece be rebuilt? No if it exists, everything is kept and the path is the same."""
    old = folders.get(entry["name"])
    if old is None:
        return bool(entry["move"])
    meta = old["meta"]
    same = (meta["first"], meta["last"], meta["fingerprint"]) == (entry["first"], entry["last"], entry["fingerprint"])
    return not (same and not entry["move"] and len(entry["keep"]) == len(old["files"]))


def spans(numbers):
    out = []
    for f in sorted(numbers):
        if out and f == out[-1][1] + 1:
            out[-1][1] = f
        else:
            out.append([f, f])
    return ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--new", required=True, help="folder of the check run of the new scene (rerender_input.json, ride_path.json)")
    parser.add_argument("--final", required=True, help="final render folder with segments/")
    parser.add_argument("--old-runs", default="",
                        help="further runs (comma-separated) whose ride_path.json matches older pieces")
    parser.add_argument("--margin", type=int, default=2, help="images before and after each visible change that are also rendered again")
    parser.add_argument("--margin-for", default="", help="own margin per target, for example name:Staffelei=15 (comma-separated)")
    parser.add_argument("--only", default="", help="only these pieces (comma-separated)")
    parser.add_argument("--busy-minutes", type=float, default=15, help="do not touch pieces with images younger than this")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    final = Path(args.final) if Path(args.final).is_absolute() else BASE / args.final
    new_dir = (BASE / args.new) if not Path(args.new).is_absolute() else Path(args.new)
    extra = {k: int(v) for k, v in (x.rsplit("=", 1) for x in args.margin_for.split(",") if x)}
    new = load_new(new_dir, args.margin, extra)
    # paths of earlier runs: --old-runs and final/runs/* (render_segments keeps each one)
    known = [BASE / r for r in args.old_runs.split(",") if r] + sorted((final / "runs").glob("*"), reverse=True)
    runs, frames, folders, unknown = load_old(final, known, new["fps"], new["hub_turn"])
    if not new["fps"]:
        print("Warning: frame rate of the check run unknown (no rerender_input.json); compare only runs with the same frame rate")
    entries = plan(new, runs, frames, folders)
    only = {x for x in args.only.split(",") if x}
    if only:
        entries = [e for e in entries if e["name"] in only]
    now = time.time()

    print(f"New ride: {len(new['path'])} images, {len(new['pieces'])} pieces; changed: {', '.join(new['targets']) or 'nothing'}"
          f" (margin {args.margin}); finished images known: {len(frames)} from {len(folders)} folders")
    if unknown:
        print(f"Without a matching path (images not usable): {', '.join(unknown)}")
    print(f"{'Piece':16} {'Images':>11} {'keep':>8} {'renamed':>9} {'new':>5} {'of them seen':>14}  Note")
    totals = {"frames": 0, "keep": 0, "move": 0, "new": 0}
    for e in entries:
        n = e["last"] - e["first"] + 1
        new_count = len(e["new"]) + len(e["dirty"])
        old = folders.get(e["name"])
        busy = bool(old and now - old["newest"] < args.busy_minutes * 60)
        e["busy"], e["touched"] = busy, touched(e, folders)
        notes = []
        if not old:
            notes.append("folder missing")
        if busy:
            notes.append("rendering right now, do not touch")
        if e["unchecked"]:
            notes.append(f"{e['unchecked']} images without visibility check (counted as new)")
        if e["move"]:
            shifts = sorted({m[0] - m[2] for m in e["move"]})
            notes.append(f"offset {', '.join(f'{s:+d}' for s in shifts)}")
        if not e["touched"]:
            notes.append("unchanged")
        print(f"{e['name']:16} {e['first']:5}-{e['last']:<5} {len(e['keep']):8} {len(e['move']):9} {new_count:5} {len(e['dirty']):14}  "
              f"{'; '.join(notes)}")
        totals["frames"] += n
        totals["keep"] += len(e["keep"])
        totals["move"] += len(e["move"])
        totals["new"] += new_count
    print(f"{'Total':16} {totals['frames']:11} {totals['keep']:8} {totals['move']:9} {totals['new']:5}")
    gaps = [e for e in entries if e["new"] or e["dirty"]]
    if gaps:   # render run only over the pieces with gaps (render_segments takes only pieces that touch a range)
        seconds = sum(len(e["new"]) + len(e["dirty"]) for e in gaps) * 10   # about 10 s per image
        frame_range = ",".join(f"{e['first']}:{e['last']}" for e in gaps)
        print("Render run after --apply (from the repository root; pieces with gaps, per piece only the missing images):")
        print(f'python tools/blender_run.py station_scene.py --building --threads 8 --storyboard scripts/data/storyboard_station.yaml --ride '
              f'--quality final --segments --order biggest --frame-range {frame_range} '
              f'--out "{final}" --gpu-minutes {max(30, round(seconds / 60 * 1.3))}')
    stamp = time.strftime("%Y%m%d_%H%M%S")
    report = {"written": time.strftime("%Y-%m-%dT%H:%M:%S"), "final": str(final), "new": str(new_dir), "margin": args.margin,
              "targets": new["targets"], "totals": totals,
              "pieces": [{"name": e["name"], "first": e["first"], "last": e["last"], "keep": len(e["keep"]), "move": len(e["move"]),
                          "new": spans(e["new"] + e["dirty"]), "visible": spans(e["dirty"]), "busy": e["busy"],
                          "touched": e["touched"]} for e in entries]}
    (new_dir / f"rerender_plan_{stamp}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Plan: {new_dir / f'rerender_plan_{stamp}.json'}")
    if not args.apply:
        print("plan only; apply with --apply")
        return

    root = final / "segments"
    busy = [e["name"] for e in entries if e["busy"] and e["touched"]]
    sources = {m[1] for e in entries for m in e["move"]}   # folders the images come from
    if any(folders[s]["newest"] > now - args.busy_minutes * 60 for s in sources if s in folders):
        busy += [s for s in sources if s in folders and folders[s]["newest"] > now - args.busy_minutes * 60]
    if busy:
        print(f"Stopped: a run is rendering at {', '.join(sorted(set(busy)))}; try later or use --only without these pieces")
        sys.exit(1)
    moved = {}   # old folder name -> new place under _old
    for name in sorted({e["name"] for e in entries if e["touched"] and e["name"] in folders} | (sources - {e["name"] for e in entries if not e["touched"]})):
        target = root / "_old" / f"{name}_{stamp}"
        target.parent.mkdir(exist_ok=True)
        shutil.move(str(folders[name]["folder"]), str(target))
        moved[name] = target
        print(f"to _old: {name} -> {target.name}")
    log = []
    for e in entries:
        if not e["touched"] or not (e["keep"] or e["move"]):
            continue
        folder = root / e["name"]
        folder.mkdir(exist_ok=True)
        for f, name, g, source in e["keep"] + e["move"]:
            src = moved.get(name, Path(source).parent) / Path(source).name
            dst = folder / f"f_{f:04d}{Path(source).suffix}"
            if dst.exists():
                continue
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
        old_meta = folders.get(e["name"], {}).get("meta", {})
        meta = {**{k: v for k, v in old_meta.items() if k in ("fps", "quality", "hub_turn", "culled")},
                "name": e["name"], "first": e["first"], "last": e["last"], "frames": e["last"] - e["first"] + 1,
                "fingerprint": e["fingerprint"], "written": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "rerender": {"on": stamp, "kept": len(e["keep"]), "renamed": len(e["move"]), "missing": len(e["new"]) + len(e["dirty"]),
                             "targets": new["targets"], "tool": "tools/rerender_plan.py"}}
        (folder / "segment.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        log.append(f"{e['name']}: {len(e['keep']) + len(e['move'])} images taken over, {len(e['new']) + len(e['dirty'])} missing")
    print("\n".join(log))
    print("applied; the next run with --segments renders exactly the missing images")


if __name__ == "__main__":
    main()
