"""Builds a PowerPoint deck from rendered image sequences, one clip per slide.

Usage (from the repository root):
    python tools/build_pptx.py probe_deck      section "probe_deck" of scripts/data/config.yaml

Per segment: ffmpeg encodes the images from "start" to "end" into an MP4; the slide gets the first
image as background and as poster frame, the video starts by itself when the slide appears and stays
on its last image at the end. The last image of a segment is the first of the next one, so the slide
change is invisible. "still" makes a slide with a single still image.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from lxml import etree
from pptx import Presentation
from pptx.util import Emu

sys.stdout.reconfigure(encoding="utf-8")

SCRIPTS = Path(__file__).resolve().parent
BASE = SCRIPTS.parent   # repository root; relative paths in the settings start here
DATA = BASE / "scripts" / "data"
W, H = Emu(12192000), Emu(6858000)  # 16:9
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"

# Timing "starts automatically", taken over from an earlier slam deck builder.
AUTOPLAY = (
    '<p:timing xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:tnLst><p:par>'
    '<p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
    '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
    '<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>'
    '<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst>'
    '<p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
    '<p:par><p:cTn id="5" presetID="1" presetClass="mediacall" presetSubtype="0" fill="hold" nodeType="afterEffect">'
    '<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
    '<p:cmd type="call" cmd="playFrom(0.0)"><p:cBhvr><p:cTn id="6" dur="1" fill="hold"/>'
    '<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:cmd>'
    '</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
    '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
    '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
    '</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>')

# Media node with fill="hold": without it the clip jumps back to its first image at the end, even when
# PowerPoint reports "rewind" as off (measured with a PowerPoint export).
# python-pptx writes it in add_movie; AUTOPLAY replaces the timing, so it is added again here.
MEDIA_NODE = (
    '<p:video xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
    '<p:cMediaNode vol="80000"><p:cTn id="20" fill="hold" display="0">'
    '<p:stCondLst><p:cond delay="indefinite"/></p:stCondLst></p:cTn>'
    '<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cMediaNode></p:video>')


def master_of(frames_dir):
    """Master video of the scene, otherwise None: then there is an image sequence frame_NNNN.png. If master_credits.mp4
    (ride with credits, credit_ride.py) lies next to it, that one is used when it is newer than master.mp4."""
    master, credited = frames_dir / "master.mp4", frames_dir / "master_credits.mp4"
    if credited.exists() and (not master.exists() or credited.stat().st_mtime >= master.stat().st_mtime):
        return credited
    return master if master.exists() else None


def frame_path(frames_dir, number, out_dir=None):
    """Single image of a scene frame number; from the master it is cut out into out_dir."""
    master = master_of(frames_dir)
    if master is None:
        return frames_dir / f"frame_{number:04d}.png"
    target = out_dir / f"still_{number:04d}.png"
    # scene frame 1 is video frame 0
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(master),
                    "-vf", f"select=eq(n\\,{number - 1})", "-frames:v", "1", str(target)], check=True)
    return target


def encode(frames_dir, start, end, fps, target, hold_pad):
    # The last image is repeated for hold_pad seconds: PowerPoint does not hold the very last image at the end
    # but a slightly earlier one (measured: frame 22 of 24), which looked like a jerk backwards.
    # Limit the length in the filter, not with -frames:v: that applies to the output and would cut off the repetition.
    master = master_of(frames_dir)
    if master is None:
        source = ["-framerate", str(fps), "-start_number", str(start), "-i", str(frames_dir / "frame_%04d.png")]
        filters = f"trim=end_frame={end - start + 1},setpts=PTS-STARTPTS"
    else:
        source = ["-i", str(master)]
        filters = f"trim=start_frame={start - 1}:end_frame={end},setpts=PTS-STARTPTS"
    if hold_pad:
        filters += f",tpad=stop_mode=clone:stop_duration={hold_pad}"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *source, "-vf", filters,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-movflags", "+faststart",
                    str(target)], check=True)


def blank_slide(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def add_video_slide(prs, video, poster):
    slide = blank_slide(prs)
    # Background = first image, so nothing black flashes while the video loads.
    slide.shapes.add_picture(str(poster), 0, 0, W, H)
    movie = slide.shapes.add_movie(str(video), 0, 0, W, H, poster_frame_image=str(poster), mime_type="video/mp4")
    sld = slide._element
    for old in sld.findall(P + "timing"):
        sld.remove(old)
    timing = etree.fromstring(AUTOPLAY.format(spid=movie.shape_id))
    timing.find(".//" + P + "cTn[@nodeType='tmRoot']/" + P + "childTnLst").append(
        etree.fromstring(MEDIA_NODE.format(spid=movie.shape_id)))
    clr = sld.find(P + "clrMapOvr")
    (clr if clr is not None else sld.find(P + "cSld")).addnext(timing)
    return slide


def latest_frames(run_dir):
    """Frame number -> file from the newest image folder frames_<time> of a run (station_scene.py --ride); each run creates
    its own, and only the newest matches the ride_check.json next to it (every run overwrites that)."""
    folders = sorted(run_dir.glob("frames_*"))
    if not folders:
        return {}
    return {int(p.stem[2:]): p for p in folders[-1].iterdir() if p.stem.startswith("f_") and p.suffix in (".png", ".jpg")}


def source_dir(value):
    """Folder of a source: absolute or relative to the repository root."""
    if re.match(r"^[a-z_]+:[^\\/]", value):
        raise SystemExit(f"{value}: root-style path is not supported here; set a local folder in the deck's sources")
    return BASE / Path(os.path.expandvars(os.path.expanduser(value)))


def segment_frames(root, stops):
    """Images of all finished pieces of the final render per click (station_scene.py --ride --segments): one folder per click
    <fromPanel>_<toPanel> with f_NNNN.png in frame numbers of the whole ride and segment.json; a piece is finished when its number
    of images equals "frames" in segment.json. Unfinished pieces and the folder _old (old states) are left out, as is a piece
    whose first/last does not match the stops of ride_check.json (from another state of the ride)."""
    frames = {}
    for folder in sorted(root.glob("*")) if root.exists() else []:
        meta_file = folder / "segment.json"
        if folder.name.startswith("_") or not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        pictures = {int(p.stem[2:]): p for p in folder.iterdir() if p.stem.startswith("f_") and p.suffix in (".png", ".jpg")}   # final render as JPEG as well
        a, _, b = folder.name.partition("_")
        if a in stops and b in stops and not (stops[a]["arrive"] <= meta["first"] <= stops[a]["frame"] + 1
                                              and stops[b]["arrive"] <= meta["last"] <= stops[b]["frame"]):
            print(f"  piece {folder.name}: frames {meta['first']} to {meta['last']} do not match the ride, left out")
        elif len(pictures) == meta["frames"]:
            frames.update(pictures)
        else:
            print(f"  piece {folder.name}: {len(pictures)} of {meta['frames']} images, not finished yet")
    return frames


def gray(path, size=(320, 180)):
    from PIL import Image
    import numpy as np
    return np.asarray(Image.open(path).convert("L").resize(size), dtype=np.int16)


def near(available, number, step):
    """The frame number itself or the nearest available image before or after it, when a preview has only every step-th image; else None."""
    for k in [number, *[number + s * d for d in range(1, step) for s in (-1, 1)]]:
        if k in available:
            return k
    return None


def hold_moves(available, arrive, depart, threshold, step=1):
    """Does something move during the stop (video, book, globe)? Compares arrival, middle and departure; None if images of the
    stop are missing (then it was not rendered and the clip ends on the arrival image)."""
    if depart - arrive < step:
        return False
    picks = [k for k in (near(available, n, step) for n in (arrive, (arrive + depart) // 2, depart)) if k is not None]
    if len(picks) < 3 or not complete(available, arrive, depart, step):
        return None
    first = gray(available[picks[0]])
    return any(float(abs(first - gray(available[n])).mean()) > threshold for n in picks[1:])


def complete(available, first, last, step):
    """Are all images from first to last there (for previews with --frame-step only every step-th)?"""
    if first > last:   # piece without movement, for example clicks at the book: only the stop of the next panel
        return True
    numbers = sorted(n for n in available if first <= n <= last)
    return bool(numbers) and numbers[0] - first < step and last - numbers[-1] < step and \
        all(b - a <= step for a, b in zip(numbers, numbers[1:]))


def encode_pieces(items, source_fps, deck_fps, size, target, hold_pad):
    """Clip from single images (scene number, file); each image stays until the next number (gaps of a preview with
    --frame-step stay real time), output at deck_fps and in final size, so all clips of the deck are alike."""
    listing = target.with_suffix(".txt")
    lines = []
    for (n, path), nxt in zip(items, [*[k for k, _ in items[1:]], items[-1][0] + 1]):
        lines.append(f"file '{path.as_posix()}'\nduration {(nxt - n) / source_fps:.6f}\n")
    listing.write_text("".join(lines) + f"file '{items[-1][1].as_posix()}'\n", encoding="utf-8")
    # Limit the length to the duration of the piece: repeating the last file (otherwise concat ignores its duration) would add one image
    frames = round((items[-1][0] + 1 - items[0][0]) / source_fps * deck_fps)
    filters = f"scale={size[0]}:{size[1]}:flags=lanczos,fps={deck_fps},trim=end_frame={frames}"
    if hold_pad:
        filters += f",tpad=stop_mode=clone:stop_duration={hold_pad}"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-vf", filters,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-movflags", "+faststart", str(target)], check=True)


def ellipse_cutout(off, ext, scale):
    """White area over the whole slide with an elliptic cutout (shape of the template), as its own geometry with two sub-paths
    running in opposite directions like the "Ring" preset: the clip runs through the cutout, the shape stays editable in PowerPoint."""
    x, y = off[0] * scale, off[1] * scale
    rx, ry = ext[0] * scale / 2, ext[1] * scale / 2
    cx, cy = x + rx, y + ry
    w, h = int(W), int(H)
    return (
        '<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:nvSpPr><p:cNvPr id="{id}" name="Closing overlay area"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
        f'<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/><a:pathLst>'
        f'<a:path w="{w}" h="{h}">'
        f'<a:moveTo><a:pt x="0" y="0"/></a:moveTo><a:lnTo><a:pt x="{w}" y="0"/></a:lnTo>'
        f'<a:lnTo><a:pt x="{w}" y="{h}"/></a:lnTo><a:lnTo><a:pt x="0" y="{h}"/></a:lnTo><a:close/>'
        f'<a:moveTo><a:pt x="{round(cx + rx)}" y="{round(cy)}"/></a:moveTo>'
        f'<a:arcTo wR="{round(rx)}" hR="{round(ry)}" stAng="0" swAng="-10800000"/>'
        f'<a:arcTo wR="{round(rx)}" hR="{round(ry)}" stAng="10800000" swAng="-10800000"/><a:close/>'
        '</a:path></a:pathLst></a:custGeom>'
        '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="de-DE"/></a:p></p:txBody></p:sp>')


def add_closing_overlay(slide, overlay):
    """Lay the shapes of the closing slide (a slide of a template deck, closing_overlay in the settings) over the loop clip: the
    template's ellipse becomes the cutout of a white area, the text boxes are added unchanged (scaled to the deck's slide
    size); the small "<" inside the ellipse is not taken over (it looks like a leftover)."""
    import copy
    source = Presentation(BASE / overlay["deck"])
    scale = int(W) / source.slide_width
    tree = slide.shapes._spTree
    next_id = max(int(e.get("id")) for e in tree.iter("{*}cNvPr")) + 1
    for shape in source.slides[overlay.get("slide", 2) - 1].shapes:
        if shape.name == overlay["cutout"]:
            element = etree.fromstring(ellipse_cutout((shape.left, shape.top), (shape.width, shape.height), scale).replace("{id}", str(next_id)))
        else:
            element = copy.deepcopy(shape._element)
            element.find(".//{*}cNvPr").set("id", str(next_id))
            xfrm = element.find(".//{*}xfrm")
            for child in xfrm:
                for key in ("x", "y", "cx", "cy"):
                    if child.get(key) is not None:
                        child.set(key, str(round(int(child.get(key)) * scale)))
            for run in element.iter("{*}rPr", "{*}defRPr", "{*}endParaRPr"):   # scale font size with the slide
                if run.get("sz"):
                    run.set("sz", str(round(int(run.get("sz")) * scale)))
            for key in ("lIns", "rIns", "tIns", "bIns"):
                body = element.find(".//{*}bodyPr")
                if body is not None and body.get(key):
                    body.set(key, str(round(int(body.get(key)) * scale)))
        tree.append(element)
        next_id += 1


def loop_video(slide):
    """Clip loops until the next click (PowerPoint: "Loop until stopped")."""
    for ctn in slide._element.iter(P + "cTn"):
        if ctn.getparent().tag == P + "cMediaNode":
            ctn.set("repeatCount", "indefinite")


def shown_path(path):
    """Path for pieces.json: relative to the repository root, absolute when the image lies outside (final render on another drive)."""
    return str(path.relative_to(BASE)) if path.is_relative_to(BASE) else str(path)


def pieces_deck(config, deck):
    """Deck from pieces per click: final render in several runs, boundaries per run from its ride_check.json by panel name
    (frame numbers shift between runs); for each piece the first run in deck["sources"] that has it complete, otherwise the
    preview (marked in pieces.md and in the slide notes). Stops without movement end on the arrival image (PowerPoint stays
    on the last image); the final stop runs as a loop with the closing overlay on top."""
    import credit_ride   # only here: pulls in credit_overlay and the list of works
    out_dir = BASE / deck["output"]
    out_dir.mkdir(parents=True, exist_ok=True)
    deck_fps, size = deck["fps"], (deck["width"], deck["height"])
    pad = config["render"].get("hold_pad_seconds", 0)
    threshold = deck.get("still_threshold", 1.0)
    board = yaml.safe_load((BASE / deck.get("storyboard", "scripts/data/storyboard_station.yaml")).read_text(encoding="utf-8"))
    clicks = [p["id"] for s in board["scenes"] for p in s["panels"] if p.get("click")]
    sources = []
    for src in deck["sources"]:
        run_dir = source_dir(src["dir"])   # the final render may lie outside the repository
        check = run_dir / "ride_check.json"
        if not check.exists():
            print(f"Source {src['dir']}: no ride_check.json, skipped")
            continue
        stops = {s["name"]: s for s in json.loads(check.read_text(encoding="utf-8"))["stops"]}
        frames = segment_frames(run_dir / "segments", stops) if src.get("segments") else latest_frames(run_dir)
        print(f"Source {src['dir']}: {len(frames)} images, {len(stops)} stops")
        sources.append(dict(src, stops=stops, frames=frames))
    names = [c for c in clicks if any(c in s["stops"] for s in sources)]
    loop_stop = deck["loop"]["stop"]
    if loop_stop in names:
        names = names[:names.index(loop_stop) + 1]

    def pick(a, b):
        """First run that has the piece a -> b complete; ends at the end of the stop at b when something moves there."""
        for src in sources:
            stops, frames, step = src["stops"], src["frames"], src.get("step", 1)
            if a not in stops or b not in stops:
                continue
            sa, sb = stops[a], stops[b]
            start = near(frames, sa["frame"], step)
            if start is None:   # stop before not rendered: the arrival image is the same image
                start = near(frames, sa["arrive"], step)
            if start is None or not complete(frames, sa["frame"] + 1, sb["arrive"], step):
                continue
            moves = False if b == loop_stop else hold_moves(frames, sb["arrive"], sb["frame"], threshold, step)
            end = near(frames, sb["frame"] if moves else sb["arrive"], step)
            # the start image carries the departure number, so the duration of the piece is right
            items = [(sa["frame"], frames[start])] + [(n, frames[n]) for n in sorted(frames) if sa["frame"] < n <= end]
            return src, items, moves
        return None, None, None

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    rows, manifest = [], []
    first = next((s for s in sources if names[0] in s["stops"]), None)
    still_number = first["stops"][names[0]]["frame"]
    still = out_dir / "still_01.png"
    still_number = near(first["frames"], still_number, first.get("step", 1)) or near(first["frames"], first["stops"][names[0]]["arrive"],
                                                                                    first.get("step", 1))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(first["frames"][still_number]), "-vf", f"scale={size[0]}:{size[1]}",
                    str(still)], check=True)
    blank_slide(prs).shapes.add_picture(str(still), 0, 0, W, H)
    prs.slides[-1].notes_slide.notes_text_frame.text = f"Panel {names[0]} (still, {first['dir']})"
    rows.append(f"| 1 | Still {names[0]} | {first['dir']} | {first['quality']} | |")
    shown_until = fresh_from = None
    for number, (a, b) in enumerate(zip(names, names[1:]), 2):
        src, items, moves = pick(a, b)
        if src is None:
            shown_until = fresh_from = None
            print(f"MISSING piece {a} -> {b}: not complete in any source")
            rows.append(f"| - | {a} to {b} | missing | | |")
            continue
        video, raw = out_dir / f"segment_{number:02d}.mp4", out_dir / f"segment_{number:02d}_roh.mp4"
        encode_pieces(items, src["fps"], deck_fps, size, raw, pad)
        # Credits for third-party works as a layer over the clip, times from the run's ride_check.json; the clip without
        # credits stays next to it as _roh, check_deck_cuts.py checks the cuts against it
        offset, length = (items[0][0] - 1) / src["fps"], (items[-1][0] + 1 - items[0][0]) / src["fps"]
        credited = deck.get("credits") and credit_ride.burn(
            raw, credit_ride.chat_spans(list(src["stops"].values()), src["fps"],
                                        deck.get("credit_frames") and BASE / deck["credit_frames"]), size, out_dir / "credit_layers" / f"{number:02d}",
            video, offset=offset, length=length, shown_until=shown_until, fresh_from=fresh_from, frame=src.get("step", 1) / src["fps"])
        # what was shown at the end of this clip is there at once in the next one; seconds per source (runs shift)
        shown_until, fresh_from = offset + length + 0.01, offset + length - 1.5 * src.get("step", 1) / src["fps"]
        if not credited:
            shutil.copyfile(raw, video)
        poster = out_dir / f"poster_{number:02d}.png"   # first image of the finished clip, so with credits
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-frames:v", "1", str(poster)], check=True)
        add_video_slide(prs, video, poster)
        hold = {True: "stop with movement until departure", False: "still stop, ends on the arrival image",
                None: "stop not rendered, ends on the arrival image"}[moves]
        mark = "" if src["quality"] == "final" else f"PREVIEW ({src['dir']}), "
        prs.slides[-1].notes_slide.notes_text_frame.text = f"Click: {a} to {b}. {mark}{hold}"
        rows.append(f"| {len(prs.slides)} | {a} to {b} | {src['dir']} | {src['quality']} | {hold} |")
        manifest.append({"clip": video.name, "raw": raw.name, "credited": bool(credited), "from": a, "to": b, "source": src["dir"],
                         "quality": src["quality"],
                         "source_fps": src["fps"], "first": shown_path(items[0][1]),
                         "last": shown_path(items[-1][1]),
                         "duration_s": (items[-1][0] + 1 - items[0][0]) / src["fps"], "hold": hold})
    # final stop as a loop (the globe keeps turning, the closing slide on top)
    loop = deck["loop"]
    src = next((s for s in sources if loop_stop in s["stops"]
                and complete(s["frames"], s["stops"][loop_stop]["arrive"], s["stops"][loop_stop]["arrive"] + s.get("step", 1), s.get("step", 1))),
               None)
    if src is not None:
        stop = src["stops"][loop_stop]
        last = min(stop["arrive"] + round(loop["seconds"] * src["fps"]) - 1, stop["frame"])
        items = [(n, src["frames"][n]) for n in sorted(src["frames"]) if stop["arrive"] <= n <= last]
        video = out_dir / "schluss_schleife.mp4"
        encode_pieces(items, src["fps"], deck_fps, size, video, 0)
        poster = out_dir / "poster_schluss.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(items[0][1]), "-vf", f"scale={size[0]}:{size[1]}", str(poster)],
                       check=True)
        slide = add_video_slide(prs, video, poster)
        loop_video(slide)
        add_closing_overlay(slide, deck["closing_overlay"])
        seamless = "seamless" if loop.get("seamless") else "NOT seamless (test: part of the stop, not a full turn)"
        mark = "" if src["quality"] == "final" else f"PREVIEW ({src['dir']}), "
        slide.notes_slide.notes_text_frame.text = f"Click: closing overlay. {mark}loop of {len(items)} images from {loop_stop}, {seamless}"
        rows.append(f"| {len(prs.slides)} | Loop {loop_stop} with closing overlay | {src['dir']} | {src['quality']} | {seamless} |")
        manifest.append({"clip": video.name, "from": loop_stop, "to": loop_stop, "source": src["dir"], "quality": src["quality"],
                         "source_fps": src["fps"], "first": shown_path(items[0][1]),
                         "last": shown_path(items[-1][1]), "duration_s": (items[-1][0] + 1 - items[0][0]) / src["fps"],
                         "hold": "loop", "loop": True})
    target = out_dir / deck["pptx"]
    prs.save(target)
    (out_dir / "pieces.json").write_text(json.dumps({"deck_fps": deck_fps, "hold_pad_seconds": pad, "clips": manifest},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
    preview = [r for r in rows if "| preview |" in r or "| missing |" in r]
    (out_dir / "pieces.md").write_text(
        "# Pieces of the deck and their source\n\nWritten by `tools/build_pptx.py`. Source \"preview\" means: the piece "
        "is not yet there in final quality and comes from the preview.\n\n| Slide | Piece | Source | Quality | Stop |\n|---|---|---|---|---|\n"
        + "\n".join(rows) + f"\n\nStill from the preview or missing: {len(preview)} of {len(rows)}.\n", encoding="utf-8")
    print(f"{target}: {len(prs.slides)} slides, {len(preview)} of them from the preview or missing; list {out_dir / 'pieces.md'}")


def main():
    config = yaml.safe_load((DATA / "config.yaml").read_text(encoding="utf-8"))
    deck = config[sys.argv[1] if len(sys.argv) > 1 else "probe_deck"]
    if deck["segments"] == "from_pieces":
        pieces_deck(config, deck)
        return
    frames_dir = BASE / deck["frames"]
    out_dir = BASE / deck["output"]
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = deck.get("fps", config["render"]["fps"])   # the preview of the station ride runs at 24 fps

    segments = deck["segments"]
    if segments == "from_ride":
        # Ride through the station (station_scene.py --ride): cuts only at panels with a click, where the camera rests
        # (BW-2); waypoints and panels without a click lie inside a clip
        ride = json.loads((frames_dir / "ride_check.json").read_text(encoding="utf-8"))
        board = yaml.safe_load((BASE / deck.get("storyboard", "scripts/data/storyboard_station.yaml")).read_text(encoding="utf-8"))
        clicks = {p["id"] for s in board["scenes"] for p in s["panels"] if p.get("click")}
        stops = [s for k, s in enumerate(ride["stops"]) if k == 0 or s["name"] in clicks]
        segments = [{"still": stops[0]["frame"], "note": f"Panel {stops[0]['name']} (still)"}]
        segments += [{"start": a["frame"], "end": b["frame"], "note": f"Click: ride from {a['name']} to {b['name']}"}
                     for a, b in zip(stops, stops[1:])]
    if segments == "from_clips":
        # one finished clip per ride (clips.yaml in the frames folder); first slide: first image of the first clip
        clips = yaml.safe_load((frames_dir / "clips.yaml").read_text(encoding="utf-8"))
        first = out_dir / "still_first.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(frames_dir / clips[0]["file"]),
                        "-frames:v", "1", str(first)], check=True)
        prs = Presentation()
        prs.slide_width, prs.slide_height = W, H
        blank_slide(prs).shapes.add_picture(str(first), 0, 0, W, H)
        prs.slides[-1].notes_slide.notes_text_frame.text = f"Stop {clips[0]['from']}"
        for number, clip in enumerate(clips, 2):
            video = out_dir / f"segment_{number:02d}.mp4"
            pad = config["render"].get("hold_pad_seconds", 0)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(frames_dir / clip["file"]),
                            *(["-vf", f"tpad=stop_mode=clone:stop_duration={pad}"] if pad else []),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-movflags", "+faststart",
                            str(video)], check=True)
            poster = out_dir / f"poster_{number:02d}.png"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(frames_dir / clip["file"]),
                            "-frames:v", "1", str(poster)], check=True)
            add_video_slide(prs, video, poster)
            prs.slides[-1].notes_slide.notes_text_frame.text = f"Click: ride from {clip['from']} to {clip['to']}"
        target = out_dir / deck["pptx"]
        prs.save(target)
        print(f"{target}: {len(prs.slides)} slides")
        return
    if segments == "from_stops":
        # cuts exactly at the scene's stops, where the camera rests (BW-2)
        stops = yaml.safe_load((frames_dir / "stops.yaml").read_text(encoding="utf-8"))
        segments = [{"still": stops[0]["frame"], "note": f"Stop {stops[0]['name']} (still)"}]
        segments += [{"start": a["frame"], "end": b["frame"], "note": f"Click: ride from {a['name']} to {b['name']}"}
                     for a, b in zip(stops, stops[1:])]

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    for number, segment in enumerate(segments, 1):
        if "still" in segment:
            slide = blank_slide(prs)
            slide.shapes.add_picture(str(frame_path(frames_dir, segment["still"], out_dir)), 0, 0, W, H)
        else:
            video = out_dir / f"segment_{number:02d}.mp4"
            encode(frames_dir, segment["start"], segment["end"], fps, video, config["render"].get("hold_pad_seconds", 0))
            add_video_slide(prs, video, frame_path(frames_dir, segment["start"], out_dir))
        if segment.get("note"):
            slide = prs.slides[-1]
            slide.notes_slide.notes_text_frame.text = segment["note"]
    target = out_dir / deck["pptx"]
    prs.save(target)
    print(f"{target}: {len(prs.slides)} slides")


if __name__ == "__main__":
    main()
