"""Checks the cuts of a deck from build_pptx.py frame by frame: every clip must start and end exactly at its stop.

Usage (from the repository root): python tools/check_deck_cuts.py station_ride_preview
Reads the deck section of scripts/data/config.yaml (like build_pptx.py), determines the cuts (from_ride) and compares per clip
- the first image of the clip with the image of the stop in the master video,
- the last image before the hold padding (hold_pad_seconds) with the image of the next stop,
- the length of the clip with the expected number of frames plus padding,
- the transition: last image of clip k against the first image of clip k+1 (invisible slide change).
The measure is the mean absolute difference per pixel (0 to 255) after decoding; one frame off gives clearly higher values
with a moving camera than the encoding alone. Threshold: MAX_DIFF; report as JSON next to the deck.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import yaml

sys.stdout.reconfigure(encoding="utf-8")
SCRIPTS = Path(__file__).resolve().parent
BASE = SCRIPTS.parent   # repository root
DATA = BASE / "scripts" / "data"
sys.path.insert(0, str(SCRIPTS))
from build_pptx import master_of  # noqa: E402

MAX_DIFF = 2.0   # encoding alone (crf 16) stays clearly below; one frame offset while moving lies above (cross-check in the report)


def frames(video, indices, size):
    """Decodes the images with the numbers indices (0-based) as greyscale arrays."""
    w, h = size
    expr = "+".join(f"eq(n\\,{i})" for i in indices)
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", f"select={expr},scale={w}:{h},format=gray",
                          "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w).astype(np.int16)
    if len(arr) != len(indices):
        raise SystemExit(f"{video.name}: decoded {len(arr)} instead of {len(indices)} images ({indices})")
    return dict(zip(sorted(indices), arr))   # ffmpeg returns them in ascending order


def count(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_frames", "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True).stdout
    return int(out.strip())


def mean_diff(a, b):
    return float(np.abs(a - b).mean())


def image(path, size):
    from PIL import Image
    return np.asarray(Image.open(path).convert("L").resize(size), dtype=np.int16)


def check_pieces(name, deck):
    """Deck from pieces (segments: from_pieces): per clip in pieces.json, first and last image against the single images of
    the run, length against the duration of the piece plus padding (within one frame: previews have only every second image),
    transition last image against the first of the next clip. Cross-check: the first image against the last (shows how large
    a movement would be)."""
    out_dir = BASE / deck["output"]
    manifest = json.loads((out_dir / "pieces.json").read_text(encoding="utf-8"))
    fps, pad = manifest["deck_fps"], round(manifest["hold_pad_seconds"] * manifest["deck_fps"])
    size = (320, 180)
    report, failed, previous = [], 0, None
    for clip in manifest["clips"]:
        video = out_dir / clip["clip"]
        raw = out_dir / clip.get("raw", clip["clip"])   # without credits: against the single images; the transition on the finished clip
        n = count(raw)
        expected = round(clip["duration_s"] * fps) + (0 if clip.get("loop") else pad)
        last_index = min(n, expected) - 1 - (0 if clip.get("loop") else pad)
        c = frames(raw, sorted({0, last_index}), size)
        # transition at the last image of the finished clip (end of padding, where PowerPoint stays): a credit that starts
        # at arrival fades in during the padding
        shown_last = count(video) - 1
        shown = frames(video, sorted({0, shown_last}), size)
        first_src, last_src = image(BASE / clip["first"], size), image(BASE / clip["last"], size)
        row = {"clip": clip["clip"], "from": clip["from"], "to": clip["to"], "source": clip["source"], "frames": n, "expected": expected,
               "start": round(mean_diff(c[0], first_src), 2), "end": round(mean_diff(c[last_index], last_src), 2),
               "cross_check_start_vs_end": round(mean_diff(first_src, last_src), 2)}
        # scene transition on the clip without credits (frame-exact, decides); with credits only reported: a new message may
        # appear at the click (intended), a jump without a new message is visible there and must be checked by hand
        if previous is not None and not clip.get("loop"):
            row["transition"] = round(mean_diff(previous[0], c[0]), 2)
            row["transition_with_credits"] = round(mean_diff(previous[1], shown[0]), 2)
        previous = (c[last_index], shown[shown_last])
        ok = abs(n - expected) <= 1 and row["start"] <= MAX_DIFF and row["end"] <= MAX_DIFF and row.get("transition", 0) <= MAX_DIFF
        row["ok"] = ok
        failed += not ok
        report.append(row)
        credit_jump = row.get("transition_with_credits", 0) > MAX_DIFF
        print(f"{'ok ' if ok else 'ERROR'} {clip['clip']} {clip['from']} -> {clip['to']} ({clip['quality']}): frames {n}/{expected}, "
              f"start {row['start']}, end {row['end']} (cross-check {row['cross_check_start_vs_end']})"
              + (f", transition {row['transition']}" if "transition" in row else "")
              + (f"; credit changes at the click ({row['transition_with_credits']}), look at it" if credit_jump else ""))
    (out_dir / "cut_check.json").write_text(json.dumps({"deck": name, "max_diff": MAX_DIFF, "clips": report}, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print(f"{len(report) - failed} of {len(report)} clips frame-exact; report {out_dir.relative_to(BASE) / 'cut_check.json'}")
    sys.exit(1 if failed else 0)


def main():
    config = yaml.safe_load((DATA / "config.yaml").read_text(encoding="utf-8"))
    name = sys.argv[1] if len(sys.argv) > 1 else "station_ride_preview"
    deck = config[name]
    if deck["segments"] == "from_pieces":
        check_pieces(name, deck)
        return
    if deck["segments"] != "from_ride":
        sys.exit("only segments: from_ride and from_pieces so far")
    frames_dir, out_dir = BASE / deck["frames"], BASE / deck["output"]
    fps = deck.get("fps", config["render"]["fps"])
    pad = round(config["render"].get("hold_pad_seconds", 0) * fps)
    ride = json.loads((frames_dir / "ride_check.json").read_text(encoding="utf-8"))
    board = yaml.safe_load((BASE / deck.get("storyboard", "scripts/data/storyboard_station.yaml")).read_text(encoding="utf-8"))
    clicks = {p["id"] for s in board["scenes"] for p in s["panels"] if p.get("click")}
    stops = [s for k, s in enumerate(ride["stops"]) if k == 0 or s["name"] in clicks]
    master = master_of(frames_dir)
    size = (320, 180)
    report, failed = [], 0
    previous_last = None
    for number, (a, b) in enumerate(zip(stops, stops[1:]), 2):
        clip = out_dir / f"segment_{number:02d}.mp4"
        n = count(clip)
        expected = b["frame"] - a["frame"] + 1 + pad
        m = frames(master, [a["frame"] - 1, b["frame"] - 1, a["frame"], b["frame"] - 2], size)   # scene frame k = video frame k-1
        c = frames(clip, [0, b["frame"] - a["frame"]], size)
        row = {"clip": clip.name, "from": a["name"], "to": b["name"], "frames": n, "expected": expected,
               "start": round(mean_diff(c[0], m[a["frame"] - 1]), 2),
               "start_cross_check_1_frame_later": round(mean_diff(c[0], m[a["frame"]]), 2),
               "end": round(mean_diff(c[b["frame"] - a["frame"]], m[b["frame"] - 1]), 2),
               "end_cross_check_1_frame_earlier": round(mean_diff(c[b["frame"] - a["frame"]], m[b["frame"] - 2]), 2)}
        if previous_last is not None:
            row["transition"] = round(mean_diff(previous_last, c[0]), 2)
        previous_last = c[b["frame"] - a["frame"]]
        ok = n == expected and row["start"] <= MAX_DIFF and row["end"] <= MAX_DIFF and row.get("transition", 0) <= MAX_DIFF
        row["ok"] = ok
        failed += not ok
        report.append(row)
        print(f"{'ok ' if ok else 'ERROR'} {clip.name} {a['name']} -> {b['name']}: frames {n}/{expected}, start {row['start']} "
              f"(cross-check {row['start_cross_check_1_frame_later']}), end {row['end']} (cross-check {row['end_cross_check_1_frame_earlier']})"
              + (f", transition {row['transition']}" if "transition" in row else ""))
    (out_dir / "cut_check.json").write_text(json.dumps({"deck": name, "master": master.name, "max_diff": MAX_DIFF, "clips": report},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(report) - failed} of {len(report)} clips frame-exact; report {out_dir.relative_to(BASE) / 'cut_check.json'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
