"""Check the camera move of a Blender scene against a small set of motion rules.

As a standalone script:   run it with Blender in background mode on a .blend file and pass a JSON configuration
                          after Blender's argument separator, either {"motion_rules": {...}} or, for a long
                          configuration, {"config_file": "rules.json"}
From a scene script:      from check_motion import check_scene; check_scene(scene, rules)

The active camera is sampled frame by frame:
  rest       at every marker (and at the first and last frame) the camera is at rest
  speed      the peak speed is at most max_speed
  turn       the turn rate is at most the horizontal field of view / pan_seconds_per_frame_width
  horizon    the roll angle is zero; the height varies by at most max_height_drift (a hint only)
"""
import json
import math
import sys

import bpy


def sample(scene, camera):
    rows = []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        matrix = camera.matrix_world.copy()
        rows.append((frame, matrix.to_translation(), matrix.to_quaternion()))
    return rows


def roll_degrees(quaternion, up=None):
    """Angle of the image horizontal (the camera's local x axis) against the horizon; up is the local up direction
    (inside the rotating ring of the station it points towards the axis), otherwise the world z axis."""
    from mathutils import Vector
    x_axis = quaternion @ Vector((1, 0, 0))
    return math.degrees(math.asin(max(-1.0, min(1.0, x_axis.dot(up or Vector((0, 0, 1)))))))


def turn_angle(q0, q1):
    """Rotation angle between two orientations. q and -q are the same orientation, but rotation_difference can then
    return almost 360 degrees, which showed up as a false alarm of thousands of degrees per second."""
    angle = q0.rotation_difference(q1).angle
    return min(angle, 2 * math.pi - angle)


def check_scene(scene, rules, up_at=None):
    camera = scene.camera
    fps = scene.render.fps
    rows = sample(scene, camera)
    hfov = 2 * math.atan(camera.data.sensor_width / (2 * camera.data.lens))
    max_turn = math.degrees(hfov) / rules["pan_seconds_per_frame_width"]
    speeds, turns = {}, {}
    for (f0, p0, q0), (f1, p1, q1) in zip(rows, rows[1:]):
        speeds[f0] = (p1 - p0).length * fps
        turns[f0] = math.degrees(turn_angle(q0, q1)) * fps

    def pose(frame, offset):
        # Subframe sampling: frame_set takes the fractional part separately (0 up to below 1)
        whole = math.floor(frame + offset)
        scene.frame_set(whole, subframe=frame + offset - whole)
        matrix = camera.matrix_world.copy()
        return matrix.to_translation(), matrix.to_quaternion()

    def motion_at(frame, step=0.1):
        # Motion at a stop measured over a tenth of a frame; a whole frame step would already measure the
        # start of the next move (one-sided at the first and last frame)
        before = pose(frame, -step) if frame > scene.frame_start else pose(frame, 0)
        after = pose(frame, step) if frame < scene.frame_end else pose(frame, 0)
        span = step * (2 if scene.frame_start < frame < scene.frame_end else 1) / fps
        speed = (after[0] - before[0]).length / span
        turn = math.degrees(turn_angle(before[1], after[1])) / span
        return speed, turn

    findings = []
    # Justified exceptions per move (camera_moves.build_path, field max_speed with max_speed_reason). A cut is an
    # exception of at least 1e9 m/s over one frame (station_scene.py --ride): there is no motion to check, only a change of shot
    overrides = json.loads(scene.get("speed_overrides", "[]"))
    cuts = {o["start"] for o in overrides if o["max_speed"] >= 1e9}
    for f in cuts:
        speeds.pop(f, None)
        turns.pop(f, None)
    stops = sorted({scene.frame_start, scene.frame_end, *[m.frame for m in scene.timeline_markers]})
    for frame in stops:
        if frame in cuts:   # last stop before a cut: measuring across the frame would see the jump
            continue
        speed, turn = motion_at(frame)
        if speed > rules["stop_speed"] or turn > rules["stop_turn"]:
            findings.append({"rule": "BW-1/BW-2", "frame": frame,
                             "text": f"Kamera ruht am Haltepunkt nicht: {speed:.2f} m/s, {turn:.1f} Grad/s"})

    def allowed_speed(frame):
        for override in overrides:
            if override["start"] <= frame < override["end"]:
                return override["max_speed"]
        return rules["max_speed"]

    peak_frame = max(speeds, key=speeds.get)
    too_fast = [f for f in speeds if speeds[f] > allowed_speed(f) * 1.005]   # tolerance for rounding (120.00 measured against an allowed 120)
    if too_fast:
        worst = max(too_fast, key=lambda f: speeds[f] - allowed_speed(f))
        findings.append({"rule": "BW-3", "frame": worst,
                         "text": f"zu schnell: {speeds[worst]:.2f} m/s, erlaubt {allowed_speed(worst)} m/s"})
    for override in overrides:
        findings.append({"rule": "BW-3", "frame": override["start"], "hint": True,
                         "text": f"Ausnahme bis {override['max_speed']} m/s bis Bild {override['end']}: {override['reason']}"})
    turn_frame = max(turns, key=turns.get)
    if turns[turn_frame] > max_turn:
        findings.append({"rule": "BW-4", "frame": turn_frame,
                         "text": f"Drehung zu schnell: {turns[turn_frame]:.1f} Grad/s, erlaubt {max_turn:.1f} Grad/s"})
    def roll(row):
        up = up_at(row[1]) if up_at else None
        if up is False:   # no horizon at this place (exterior shot in space, station_scene.py), no check
            return 0.0
        if up is not None:   # steep view up or down (book on the desk): hardly any horizon in frame, no check
            from mathutils import Vector
            if abs((row[2] @ Vector((0, 0, -1))).dot(up)) > 0.85:
                return 0.0
        return roll_degrees(row[2], up)

    worst_roll = max(rows, key=lambda r: abs(roll(r)))
    if abs(roll(worst_roll)) > rules["max_roll_degrees"]:
        findings.append({"rule": "BW-6", "frame": worst_roll[0],
                         "text": f"Horizont schief: {roll(worst_roll):.1f} Grad"})
    heights = [p.z for _, p, _ in rows]
    if max(heights) - min(heights) > rules["max_height_drift"]:
        findings.append({"rule": "BW-6", "frame": None, "hint": True,
                         "text": f"Augenhöhe schwankt um {max(heights) - min(heights):.2f} m (Hinweis)"})

    print(f"Bewegtbild-Prüfung: {len(rows)} Bilder, {len(stops)} Haltepunkte, "
          f"Spitze {speeds[peak_frame]:.2f} m/s, Drehung bis {turns[turn_frame]:.1f} Grad/s (erlaubt {max_turn:.1f})")
    for finding in findings:
        where = f"Bild {finding['frame']}" if finding["frame"] else "gesamt"
        print(f"  {finding['rule']} ({where}): {finding['text']}")
    if not [f for f in findings if not f.get("hint")]:
        print("  keine Verstöße")
    return findings


if __name__ == "__main__":
    config = json.loads(sys.argv[sys.argv.index("--") + 1])
    if "config_file" in config:   # long configuration passed as a file
        with open(config["config_file"], encoding="utf-8") as handle:
            config = json.load(handle)
    findings = check_scene(bpy.context.scene, config["motion_rules"])
    sys.exit(1 if [f for f in findings if not f.get("hint")] else 0)
