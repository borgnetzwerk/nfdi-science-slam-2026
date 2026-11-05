"""Camera moves for Blender, following a small set of motion rules (runs inside Blender).

A stop is a timeline marker plus a keyframe with flat tangents, so the camera comes to rest there instead of
drifting through it. The duration of a move follows from its distance and the allowed peak speed, and from the
allowed turn rate; whichever needs longer wins.

Optional per stop:
  dwell_seconds   the camera holds still this long before the stop counts as reached (a video in the frame keeps
                  playing); the marker, and therefore the cut, sits at the end of the dwell
  max_speed, max_speed_reason
                  a justified exception to the speed limit for the move into this stop (a rule may only be broken
                  with a stated reason); it is recorded in the scene so that check_motion.py knows about it
"""
import json
import math

import bpy
from mathutils import Euler, Vector

# Peak speed of a move with flat Bezier tangents relative to its mean speed.
# Measured on a test move with check_motion.py: about 1.5; 1.6 leaves some margin.
PEAK_TO_MEAN = 1.6


def horizontal_fov(camera):
    return 2 * math.atan(camera.data.sensor_width / (2 * camera.data.lens))


def travel_frames(start, end, camera, rules, fps):
    """Minimum number of frames a move from start to end needs (for both distance and rotation)."""
    distance = (Vector(end["location"]) - Vector(start["location"])).length
    turn = Euler(start["rotation"]).to_quaternion().rotation_difference(
        Euler(end["rotation"]).to_quaternion()).angle
    max_speed = end.get("max_speed", rules["max_speed"])
    seconds_move = distance * PEAK_TO_MEAN / max_speed
    max_turn_rate = horizontal_fov(camera) / rules["pan_seconds_per_frame_width"]
    seconds_turn = turn * PEAK_TO_MEAN / max_turn_rate
    seconds = max(seconds_move, seconds_turn, rules["min_travel_seconds"])
    return max(2, math.ceil(seconds * fps))


def key_pose(camera, frame, location, rotation):
    camera.location = location
    camera.rotation_euler = rotation
    camera.keyframe_insert("location", frame=frame)
    camera.keyframe_insert("rotation_euler", frame=frame)


def key_stop(camera, frame, location, rotation, name):
    """Stop: a keyframe with flat tangents (zero velocity) plus a timeline marker."""
    key_pose(camera, frame, location, rotation)
    bpy.context.scene.timeline_markers.new(name, frame=frame)


def fcurves_of(obj):
    """F-curves of an object; since Blender 5 they live in the channelbag of the action slot."""
    animation = obj.animation_data
    if hasattr(animation.action, "fcurves"):
        return animation.action.fcurves
    from bpy_extras import anim_utils
    return anim_utils.action_get_channelbag_for_slot(animation.action, animation.action_slot).fcurves


def flatten_stops(obj):
    """Give every keyframe of the object horizontal tangents, so the object rests at each keyframe."""
    for fcurve in fcurves_of(obj):
        points = fcurve.keyframe_points
        for i, point in enumerate(points):
            point.interpolation = "BEZIER"
            point.handle_left_type = point.handle_right_type = "FREE"
            # A handle length of one third of the distance to the neighbour gives the usual smooth curve.
            left = (point.co.x - points[i - 1].co.x) / 3 if i > 0 else 1.0
            right = (points[i + 1].co.x - point.co.x) / 3 if i < len(points) - 1 else 1.0
            point.handle_left = (point.co.x - left, point.co.y)
            point.handle_right = (point.co.x + right, point.co.y)
        fcurve.update()


def build_path(camera, stops, rules, fps, first_frame=1):
    """Animate the camera through all stops.

    Returns one dictionary per stop: arrive (frame the camera arrives) and frame (the marker, end of the dwell).
    """
    scene = bpy.context.scene
    timeline, overrides, frame = [], [], first_frame
    for index, stop in enumerate(stops):
        if index:
            start = frame
            frame += travel_frames(stops[index - 1], stop, camera, rules, fps)
            if "max_speed" in stop:
                overrides.append({"start": start, "end": frame, "max_speed": stop["max_speed"],
                                  "reason": stop.get("max_speed_reason", "")})
        arrive = frame
        key_pose(camera, arrive, stop["location"], stop["rotation"])
        dwell = round(stop.get("dwell_seconds", 0) * fps)
        if dwell:
            frame += dwell
            key_pose(camera, frame, stop["location"], stop["rotation"])
        scene.timeline_markers.new(stop["name"], frame=frame)
        timeline.append({"name": stop["name"], "arrive": arrive, "frame": frame})
    flatten_stops(camera)
    # Record the justified speed exceptions in the scene for check_motion.py
    scene["speed_overrides"] = json.dumps(overrides)
    return timeline
