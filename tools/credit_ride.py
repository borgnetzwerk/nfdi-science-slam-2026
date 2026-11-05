"""Lays credits for third-party works over the ride as chat messages (ride from station_scene.py --ride).

Usage (from the repository root): python tools/credit_ride.py [_scratch/ride_station]
For each panel the chat history from credit_overlay.chat_history() (oldest message on top, at most three); it applies from
arrival at the panel until arrival at the next panel with a different history. The same history over several panels stays.
Each layer fades in over fade_in_seconds and out over fade_out_seconds (credits.yaml). Input master.mp4 and ride_check.json
of the ride, output master_credits.mp4 next to them (build_pptx.py uses it when it is newer than master.mp4).
"""
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
SCRIPTS = Path(__file__).resolve().parent
BASE = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import credit_overlay  # noqa: E402


def size_of(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                          "-of", "json", str(video)], capture_output=True, text=True, check=True).stdout
    stream = json.loads(out)["streams"][0]
    num, den = (int(x) for x in stream["r_frame_rate"].split("/"))
    return stream["width"], stream["height"], num / den


GAP_SECONDS = 1.0   # shorter gaps (a pillar or frame passing by) count as continuously visible, otherwise the chat jumps
                    # (0.3 s gave states of 0.1 to 0.3 s)
MIN_SECONDS = 0.5   # visible for less than this does not count


def frame_spans(frames_file, stops, fps):
    """Time spans from the visibility per frame (station_scene.py --credit-frames): a credit shows from the moment the work
    is in the picture. Frame numbers of the check run are mapped onto the rendered run via the panels: the distance to the
    departure from the panel before stays the same. A work joins on top as soon as it is in the picture and drops out as soon
    as it leaves; panels with works set by hand (field credits, for example a photo on a book page) apply from arrival to departure."""
    data = json.loads(Path(frames_file).read_text(encoding="utf-8"))
    known = credit_overlay.works()
    target = {s["name"]: s for s in stops}
    anchors = sorted((s["frame"], s["name"]) for s in data["stops"] if s["name"] in target)

    def mapped(f):
        before = [(frame, name) for frame, name in anchors if frame <= f]
        frame, name = before[-1] if before else anchors[0]
        return target[name]["frame"] + f - frame

    seen = {}
    for work_id, runs in data["frames"].items():
        if work_id not in known:
            continue
        for a, b in runs:
            seen.setdefault(work_id, []).append((mapped(a), mapped(b)))
    for panel, ids in data.get("panel_credits", {}).items():
        if panel in target:
            for work_id in ids:
                if work_id in known:
                    # two frames after arrival: otherwise the start falls on the last frame of the clip before and fades in
                    # during its hold padding
                    seen.setdefault(work_id, []).append((target[panel]["arrive"] + 2, target[panel]["frame"]))
    gap = round(GAP_SECONDS * fps)
    for work_id, runs in seen.items():
        merged = []
        for a, b in sorted(runs):
            if merged and a <= merged[-1][1] + gap:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        # shorter than MIN_SECONDS: only clipped in passing (one frame), otherwise the chat flashes for an instant
        seen[work_id] = [(a, b) for a, b in merged if b - a + 1 >= MIN_SECONDS * fps]
    seen = {w: runs for w, runs in seen.items() if runs}
    events = sorted({f for runs in seen.values() for a, b in runs for f in (a, b + 1)})
    spans, chat = [], []
    for k, f in enumerate(events):
        on = [w for w, runs in seen.items() if any(a <= f <= b for a, b in runs)]
        chat = [w for w in chat if w in on] + sorted((w for w in on if w not in chat), key=lambda w: min(a for a, _ in seen[w]))
        if chat and k + 1 < len(events):
            spans.append(((f - 1) / fps, (events[k + 1] - 1) / fps, list(chat)))
    return spans


def chat_spans(stops, fps, frames_file=None):
    """Time spans (start s, end s, history) of the ride; waypoints belong to the panel before. fps is the frame rate of the
    frame numbers in ride_check.json, not that of the video (a preview with --frame-step has fewer images per second). With
    frames_file (credit_frames.json) frame-exact from the visibility per frame (frame_spans)."""
    if frames_file:
        # never fall back silently to the panel logic: it carries a credit on over the next panels
        if not Path(frames_file).exists():
            raise SystemExit(f"credit_frames missing: {frames_file}; run station_scene.py --credit-frames first")
        return frame_spans(frames_file, stops, fps)
    history = credit_overlay.chat_history()
    spans, current, start = [], None, 0.0
    for stop in stops:
        if stop["name"].startswith("Durchgang"):   # no work is in the picture in a passage: the chat fades out there
            chat = []
        elif stop["name"] in history:
            chat = history[stop["name"]]
        else:
            continue
        t = (stop["arrive"] - 1) / fps
        if chat != current:
            if current:
                spans.append((start, t, current))
            current, start = chat, t
    if current:
        spans.append((start, (stops[-1]["frame"]) / fps, current))
    return spans


def burn(video, spans, size, layers, target, offset=0.0, length=None, shown_until=None, fresh_from=None, frame=0.0):
    """Lays the time spans over video and writes target; returns False if no span falls inside (then no target).
    With offset and length, video counts as a part of the ride from offset seconds (one piece per click). A change in the last
    frame of the clip (arrival at the click panel) fades in during the hold padding at the end, where PowerPoint stays. A
    history already shown in the previous clip (start before shown_until, seconds of the ride) is fully there at once, otherwise
    it would fade in again at the invisible slide change; if it only began at the end there (from fresh_from), the dark phase
    continues here as well. A history that applies beyond the piece runs to the end of the clip without fading out (hold
    padding included)."""
    width, height = size
    style = credit_overlay.STYLE
    known = credit_overlay.works()
    layers.mkdir(parents=True, exist_ok=True)
    inside = []
    for a_abs, b_abs, chat in spans:
        a, b = a_abs - offset, b_abs - offset
        if length is not None and (b <= 1.5 * frame or a > length + 0.01):
            continue
        before = a < 0 and (shown_until is None or a_abs < shown_until)
        fresh_carry = before and fresh_from is not None and a_abs >= fresh_from
        after = length is not None and b > length + 0.01
        if length is not None:
            a = min(max(a, 0.0), length - frame)
        inside.append((a, length + 60.0 if after else b, chat, before, after, fresh_carry))
    if not inside:
        return False
    inputs, filters, last, n = [], [], "[0:v]", 0

    def add(png, start, duration, fade_in, fade_out_at=None):
        """One layer from start for duration seconds; fade in over fade_in s, fade out from fade_out_at (relative) over fade_out_seconds."""
        nonlocal last, n
        n += 1
        inputs.extend(["-loop", "1", "-t", f"{duration:.3f}", "-i", str(png)])
        chain = f"[{n}:v]format=rgba"
        if fade_in:
            chain += f",fade=t=in:st=0:d={fade_in}:alpha=1"
        if fade_out_at is not None:
            chain += f",fade=t=out:st={fade_out_at:.3f}:d={style['fade_out_seconds']}:alpha=1"
        filters.append(chain + f",setpts=PTS+{start:.3f}/TB[c{n}]")
        filters.append(f"{last}[c{n}]overlay=0:0:eof_action=pass[v{n}]")
        last = f"[v{n}]"

    # Three layers per span: box at its resting opacity, box very dark for fresh_seconds after a new message (then fades),
    # and the text. If a span follows directly (new message), the old one ends hard; if nothing follows (the work leaves the
    # picture), the box fades to 0 over fade_out_seconds. The text fades out with the box: alone in front of a bright wall it
    # was below the contrast threshold.
    for k, (a, b, chat, before, after, fresh_carry) in enumerate(inside, 1):
        msgs = [(known[c], 1.0) for c in chat if c in known]
        files = {}
        for part, alpha in (("background", None), ("fresh", style["fresh_alpha"]), ("text", None)):
            png = layers / f"chat_{k:02d}_{part}.png"
            credit_overlay.chat_layer((width, height), msgs, part=("background" if part == "fresh" else part), bg_alpha=alpha).save(png)
            files[part] = png
        follows = after or (k < len(inside) and inside[k][0] <= b + 0.05)
        tail = 0.0 if follows else style["fade_out_seconds"]
        duration = b - a + tail
        # new message exactly at the click while the previous clip already showed a credit: the box changes without fading in from zero
        switch = length is not None and shown_until is not None and a <= 1.5 * frame
        fade_in = 0 if before or switch or style.get("pop") else style["fade_in_seconds"]
        add(files["background"], a, duration, fade_in, None if follows else b - a)
        if (not before or fresh_carry) and not style.get("pop"):   # pop: no dark phase after a new message
            fresh = min(duration, style["fresh_seconds"] + style["fresh_fade_seconds"])
            add(files["fresh"], a, fresh, fade_in, max(0.0, fresh - style["fresh_fade_seconds"]))
        add(files["text"], a, duration, fade_in, None if follows else b - a)
        print(f"Chat {k}: {a:6.1f} s to {b:6.1f} s{' +' + str(tail) + ' s fade out' if tail else ''}: {', '.join(chat)}")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), *inputs, "-filter_complex", ";".join(filters),
                    "-map", last, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16" if length is not None else "20",
                    "-movflags", "+faststart", str(target)], check=True)
    return True


def main():
    ride_dir = BASE / (sys.argv[1] if len(sys.argv) > 1 else "_scratch/ride_station")
    master = ride_dir / "master.mp4"
    width, height, fps = size_of(master)
    stops = json.loads((ride_dir / "ride_check.json").read_text(encoding="utf-8"))["stops"]
    spans = chat_spans(stops, fps)
    target = ride_dir / "master_credits.mp4"
    if not burn(master, spans, (width, height), ride_dir / "credit_layers", target):
        print("no third-party work in the ride")
        return
    print("written:", target)


if __name__ == "__main__":
    main()
