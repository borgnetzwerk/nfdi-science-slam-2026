"""Credits for third-party works as a chat message in the bottom left corner.

Usage (from the repository root):
    python tools/credit_overlay.py            # overlay on all panels with a third-party work, contact sheet of the results
    python tools/credit_overlay.py --panels 03.2,05.8

Works and design are in credits.yaml; which works a panel shows is written by station_scene.py to
_scratch/storyboard/render_log.json (field credits, from visible_in). The messages are made as a separate layer with
transparency (chat_layer), so the same layer can later be laid over the clip frame by frame (alpha_at gives the
opacity per point in time). The rendering itself stays unchanged; the result goes to _scratch/storyboard/credits/.
"""
import json
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

SCRIPTS = Path(__file__).resolve().parent
BASE = SCRIPTS.parent   # repository root
DATA = BASE / "scripts" / "data"
sys.path.insert(0, str(BASE / "scripts" / "scene"))
from wkw_palette import WKW_HEX  # noqa: E402

CONFIG = yaml.safe_load((DATA / "credits.yaml").read_text(encoding="utf-8"))
STYLE = CONFIG["style"]
FONT_FILE = BASE / "fonts" / "OpenSans[wdth,wght].ttf"   # variable Open Sans font; not part of this repository
OUT = BASE / "_scratch" / "storyboard" / "credits"


def font(size, weight):
    """Open Sans from the variable font, weight 400 to 800."""
    try:
        f = ImageFont.truetype(str(FONT_FILE), size)
        f.set_variation_by_axes([weight, 100])   # axes of the font: [weight, width] (swapped before: everything in the light cut)
        return f
    except (OSError, ValueError):
        return ImageFont.truetype("arial.ttf", size)


def works():
    """Per work: date (ISO or year), creator and title; videos from videos.yaml (cited)."""
    videos = {v["id"]: v for v in yaml.safe_load((DATA / "videos.yaml").read_text(encoding="utf-8"))["cited"]}
    result = {}
    for work_id, spec in CONFIG["works"].items():
        if spec.get("own"):   # the speaker's own talks need no credit
            continue
        video = videos.get(spec.get("video"), {})
        date = spec.get("published") or video.get("published") or video.get("year")
        result[work_id] = {"date": str(date) if date else "date?", "creator": spec.get("creator") or video.get("creator", "?"),
                           "title": spec.get("title") or video.get("title", "?")}
    return result


def wrap(draw, text, fnt, width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=fnt) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line] if line else lines


def chat_lines(draw, parts, width):
    """One chat line as in a stream chat: parts (text, font, colour) one after the other, wrapped at word boundaries; follow-up
    lines start at the left (like Twitch). Result: list of lines, each a list of (x, text, font, colour)."""
    lines, line, x = [], [], 0
    for text, fnt, colour in parts:
        for k, word in enumerate(text.split(" ")):
            token = word if k == 0 else " " + word
            size = draw.textlength(token, font=fnt)
            if x + size > width and line:
                lines.append(line)
                line, x, token = [], 0, word
                size = draw.textlength(token, font=fnt)
            line.append((x, token, fnt, colour))
            x += size
    return lines + [line] if line else lines


def chat_layer(size, messages, corner="left", part="all", bg_alpha=None):
    """RGBA layer in image size: messages is a list of (work, opacity 0 to 1), oldest first; newest at the bottom as in a chat.
    Per message one chat line "year  name: title" (year and name bold, year grey, name in colour with a colon, title white),
    older ones move up, at most max_messages. Box flush with the bottom left without margin (style flush), square except for
    the top right corner (rounded_corners). part: all, background (only the box, opacity bg_alpha or background_alpha) or text
    (only the text), so the clip can fade box and text separately. Without a message the layer is fully transparent."""
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    messages = [(m, a) for m, a in messages if a > 0][-STYLE["max_messages"]:]
    if not messages:
        return layer
    draw = ImageDraw.Draw(layer)
    flush = STYLE.get("flush", False)
    margin = 0 if flush else int(STYLE["safe_margin"] * h)
    box_w = int(STYLE["width"] * w)
    pad = int(0.016 * h)
    size_px = int(STYLE["text_size"] * h)
    year_only = STYLE.get("date_format", "full") == "year"
    f_date = font(size_px, 700) if year_only else font(int(size_px * 0.78), 400)
    f_name, f_text = font(size_px, 700), font(size_px, 400)
    line_h, msg_gap = int(size_px * 1.25), int(size_px * 0.45)
    name_rgb = tuple(int(WKW_HEX[STYLE["name_color"]][i:i + 2], 16) for i in (0, 2, 4))
    if STYLE.get("newest_top"):   # a new message joins on top, the block grows upwards, older ones stay in place
        messages = messages[::-1]
    blocks = []
    for work, alpha in messages:
        a = int(255 * alpha)
        date = work["date"][:4] if year_only else work["date"]
        parts = [(date + "  ", f_date, (*STYLE["date_color"], a)), (work["creator"] + ":", f_name, (*name_rgb, a)),
                 (" " + work["title"], f_text, (*STYLE["text_color"], a))]
        blocks.append(chat_lines(draw, parts, box_w - 2 * pad))
    total = sum(len(b) for b in blocks) * line_h + msg_gap * (len(blocks) - 1) + 2 * pad
    left, bottom = (0 if flush else int(STYLE["safe_margin"] * w)), h - margin
    if corner == "right":   # bottom right (comparison; bottom left was chosen)
        left = w - (0 if flush else int(STYLE["safe_margin"] * w)) - box_w
    top = bottom - total
    if part in ("all", "background"):
        alpha = STYLE["background_alpha"] if bg_alpha is None else bg_alpha
        alpha *= max(a for _, a in messages)   # background follows the brightest message and fades with it
        corners = tuple(STYLE.get("rounded_corners", [True, True, True, True]))
        if corner == "right":
            corners = (corners[1], corners[0], corners[3], corners[2])
        # draw the box four times as large as a mask and scale it down: smooth rounding (rounded_rectangle alone draws
        # without anti-aliasing)
        k = 4
        mask = Image.new("L", (box_w * k, (bottom - top) * k), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, box_w * k - 1, (bottom - top) * k - 1), radius=pad * k, fill=255, corners=corners)
        mask = mask.resize((box_w, bottom - top), Image.LANCZOS).point(lambda v: int(v * alpha))
        layer.paste(Image.new("RGBA", mask.size, (*STYLE["background"], 255)), (left, top), mask)
    if part in ("all", "text"):
        y = top + pad
        for block in blocks:
            for line in block:
                for x, token, fnt, colour in line:   # common baseline, so a smaller date does not slide upwards
                    draw.text((left + pad + x, y + line_h * 0.8), token, font=fnt, fill=colour, anchor="ls")
                y += line_h
            y += msg_gap
    return layer


def alpha_at(t, shown):
    """Opacity of a message at time t (seconds in the clip); shown = (start, end) of the work's visibility.
    Fade in over fade_in_seconds, visible until at least min_seconds after start and linger_seconds after end, then fade out."""
    start, end = shown
    hold_until = max(start + STYLE["min_seconds"], end + STYLE["linger_seconds"])
    if t < start:
        return 0.0
    if t < start + STYLE["fade_in_seconds"]:
        return (t - start) / STYLE["fade_in_seconds"]
    if t <= hold_until:
        return 1.0
    return max(0.0, 1.0 - (t - hold_until) / STYLE["fade_out_seconds"])


def apply(image_path, credit_ids, target, corner="left"):
    """Lays the messages of the works credit_ids (oldest first) over the image and saves it as target."""
    known = works()
    img = Image.open(image_path).convert("RGBA")
    layer = chat_layer(img.size, [(known[c], 1.0) for c in credit_ids if c in known], corner)
    Image.alpha_composite(img, layer).convert("RGB").save(target)
    return target


def panel_credits():
    """Panel -> visible third-party works, from the last run of station_scene.py."""
    log = json.loads((BASE / "_scratch" / "storyboard" / "render_log.json").read_text(encoding="utf-8"))
    return {e["panel"]: e.get("credits", []) for e in log}


def chat_history(board=None):
    """Panel -> chat history (oldest first) in storyboard order: a work that is in the picture for the first time joins at
    the bottom; the history stays as long as a third-party work is visible in every panel (as in a stream chat, older ones
    move up). A panel without a third-party work fades the chat out and empties it; a panel shows the stop, so after the fade
    nothing is left."""
    board = board or yaml.safe_load((DATA / "storyboard_station.yaml").read_text(encoding="utf-8"))
    known = works()   # without the speaker's own talks (own: true)
    visible = {panel: [i for i in ids if i in known] for panel, ids in panel_credits().items()}
    history, result = [], {}
    for scene in board["scenes"]:
        history = []   # between two rooms lies the passage without a third-party work: the chat fades out there (the
        # storyboard has no panel for it; otherwise the history of room 2 would still hang over room 3)
        for panel in scene["panels"]:
            ids = visible.get(panel["id"], [])
            if not ids:
                history = []
            for work_id in ids:
                if work_id not in history:
                    history.append(work_id)
            result[panel["id"]] = list(history)
    return result


def main():
    only = sys.argv[sys.argv.index("--panels") + 1].split(",") if "--panels" in sys.argv else None
    OUT.mkdir(parents=True, exist_ok=True)
    done = []
    for panel, ids in chat_history().items():
        if only and panel not in only or not ids:
            continue
        source = BASE / "_scratch" / "storyboard" / ("SB_" + panel.replace(".", "_") + ".png")
        if source.exists():
            done.append(apply(source, ids, OUT / source.name))
            print(f"Panel {panel}: {', '.join(ids)}")
    print(f"{len(done)} panels with credits in {OUT}")


if __name__ == "__main__":
    main()
