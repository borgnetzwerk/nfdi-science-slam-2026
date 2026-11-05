"""Camera motion like a person strolling through a museum. Runs inside Blender (mathutils).

The camera moves at a constant walking speed and only slows down or speeds up when there is a reason (a stop), its gaze
behaves like a human head, and a gentle walking sway shifts from one foot to the other.

Model:
- Stops (boards) and waypoints (via, passage). Between two stops the camera moves at constant walking speed through the
  waypoints, with rounded corners; it only brakes before a stop and only accelerates after one (ease_seconds), never at
  waypoints.
- The gaze is a separate track: on the way the camera looks in the walking direction, before a stop it turns towards the
  target before the body arrives (look_lead_seconds), and after the stop it lets go again (look_release_seconds);
  waypoints with their own gaze briefly pull the view towards them. The turn rate is limited (pan_seconds_per_frame_width);
  at a stop the camera matches the board's camera exactly.
- Walking profile: small lateral motion (one cycle per double step) and vertical motion (one cycle per step), only while
  walking, with an amplitude that follows the speed; values in config.yaml walk_profile.
All numbers come from profile (walk_profile) and rules (motion_rules); nothing is hard-coded here.
"""
import math

from mathutils import Matrix, Quaternion, Vector


def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def forward_of(rotation):
    return (rotation.to_quaternion() if hasattr(rotation, "to_quaternion") else Quaternion(rotation)) @ Vector((0, 0, -1))


def rounded_polyline(points, radius, step):
    """Dense sequence of points along the given points, corners rounded with radius (quadratic Bezier curve), spacing about
    step. Returns the points and, per input point, the index of the closest output point (waypoint passages)."""
    pts = [Vector(p) for p in points]
    pts = [p for k, p in enumerate(pts) if k == 0 or (p - pts[k - 1]).length > 1e-6]
    if len(pts) == 1:
        return pts, [0] * len(points)
    out, marks = [pts[0]], [0]
    for k in range(1, len(pts)):
        a, b = pts[k - 1], pts[k]
        if k < len(pts) - 1:
            c = pts[k + 1]
            r = min(radius, 0.45 * (b - a).length, 0.45 * (c - b).length)
            p_in, p_out = b - (b - a).normalized() * r, b + (c - b).normalized() * r
            out += _line(out[-1], p_in, step)
            marks.append(len(out) - 1 if r < 1e-6 else len(out) + max(1, int(r / step)) - 1)
            out += _bezier(p_in, b, p_out, step)
        else:
            out += _line(out[-1], b, step)
            marks.append(len(out) - 1)
    return out, marks


def _line(a, b, step):
    n = max(1, int((b - a).length / step))
    return [a + (b - a) * (i / n) for i in range(1, n + 1)]


def _bezier(a, b, c, step):
    n = max(2, int(((b - a).length + (c - b).length) / step))
    return [(1 - t) ** 2 * a + 2 * (1 - t) * t * b + t ** 2 * c for t in (i / n for i in range(1, n + 1))]


def arc_lengths(points):
    s, total = [0.0], 0.0
    for k in range(1, len(points)):
        total += (points[k] - points[k - 1]).length
        s.append(total)
    return s


def at_length(points, lengths, s):
    """Point and tangent at arc length s."""
    if s <= 0:
        p, q = points[0], points[min(1, len(points) - 1)]
        return points[0].copy(), (q - p).normalized() if (q - p).length else Vector((1, 0, 0))
    if s >= lengths[-1]:
        p, q = points[-2] if len(points) > 1 else points[-1], points[-1]
        return points[-1].copy(), (q - p).normalized() if (q - p).length else Vector((1, 0, 0))
    lo, hi = 0, len(lengths) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if lengths[mid] <= s:
            lo = mid
        else:
            hi = mid
    seg = lengths[hi] - lengths[lo]
    t = (s - lengths[lo]) / seg if seg else 0.0
    tangent = (points[hi] - points[lo]).normalized() if seg else Vector((1, 0, 0))
    return points[lo] + (points[hi] - points[lo]) * t, tangent


def rotate_towards(current, target, max_angle):
    """Rotate the unit vector current towards target by at most max_angle (rad)."""
    angle = current.angle(target, 0.0)
    if angle <= max_angle or angle < 1e-6:
        return target.normalized()
    axis = current.cross(target)
    if axis.length < 1e-6:
        axis = current.orthogonal()
    return (Quaternion(axis.normalized(), max_angle) @ current).normalized()


def blend_dir(a, b, t, up=None):
    """Direction between a and b on the sphere (fraction t from a to b). A linear mix shrinks to zero for nearly opposite
    directions: the head would not turn and the camera would snap round by about 160 degrees on arrival."""
    a, b = a.normalized(), b.normalized()
    angle = a.angle(b, 0.0)
    if t <= 0 or angle < 1e-6:
        return a if t <= 0 else b
    axis = a.cross(b)
    if axis.length < 1e-6:   # exactly opposite: turn about the up axis (like a person turning round)
        axis = Vector(up) if up not in (None, False) else a.orthogonal()
    return (Quaternion(axis.normalized(), angle * min(1.0, t)) @ a).normalized()


def turn_like_head(current, target, max_angle, up):
    """Turn the gaze like a head: yaw about the up axis and pitch, both at once, together at most max_angle (rad).
    For targets almost straight up or down the shortest arc (rotate_towards) passes over the pole and leaves the camera
    upside down (a roll of about 170 degrees was measured); a person never leans back over their head, they turn round and
    nod. Without an up axis (up False, in space) the shortest arc is used."""
    if up is False:
        return rotate_towards(current, target, max_angle)
    up = Vector(up).normalized()
    pitch_c = math.asin(max(-1.0, min(1.0, current.dot(up))))
    pitch_t = math.asin(max(-1.0, min(1.0, target.dot(up))))
    flat_c, flat_t = current - up * current.dot(up), target - up * target.dot(up)
    if flat_c.length < 1e-4 and flat_t.length < 1e-4:
        return rotate_towards(current, target, max_angle)
    if flat_c.length < 1e-4:   # exactly at the pole: take over the yaw direction of the target
        flat_c = flat_t
    if flat_t.length < 1e-4:
        flat_t = flat_c
    e1 = flat_c.normalized()
    e2 = up.cross(e1)
    yaw_t = math.atan2(flat_t.dot(e2), flat_t.dot(e1))   # yaw of the target relative to the current one, between -pi and pi
    d_pitch = pitch_t - pitch_c
    dist = math.hypot(yaw_t, d_pitch)
    if dist <= max_angle or dist < 1e-6:
        return target.normalized()
    k = max_angle / dist
    yaw, pitch = yaw_t * k, pitch_c + d_pitch * k
    flat = e1 * math.cos(yaw) + e2 * math.sin(yaw)
    return (flat * math.cos(pitch) + up * math.sin(pitch)).normalized()


def pose_from(forward, up, fallback, max_level=math.pi):
    """Quaternion looking along forward: start from the previous orientation fallback and rotate it by the smallest rotation
    onto forward (continuous, no roll); with a usable up the horizon is then levelled, partly or not at all for a steep view
    (almost parallel to up), because otherwise the orientation flipped by 180 degrees. Levelling turns by at most max_level
    (rad) per call: after a tilted stop (looking down at a book) and when the up axis changes from the ring to a spoke, the
    orientation would otherwise jump by about 40 degrees in a single frame."""
    prev_fwd = (fallback @ Vector((0, 0, -1))).normalized()
    if up is not False:   # first yaw about the up axis, then pitch (as in turn_like_head): a level orientation stays level,
        flat_p, flat_f = prev_fwd - up * prev_fwd.dot(up), forward - up * forward.dot(up)   # even close to the pole
        if flat_p.length > 0.2 and flat_f.length > 0.2:   # close to the pole the in-plane direction is undefined and the yaw
            # jumped by almost 170 degrees in one frame; there only the smallest rotation is used
            flat_p, flat_f = flat_p.normalized(), flat_f.normalized()
            yaw = math.atan2(up.dot(flat_p.cross(flat_f)), flat_p.dot(flat_f))
            fallback = Quaternion(Vector(up).normalized(), yaw) @ fallback
            prev_fwd = (fallback @ Vector((0, 0, -1))).normalized()
    turned = prev_fwd.rotation_difference(forward) @ fallback
    if up is False:
        return turned
    steep = abs(forward.dot(up))
    if steep > 0.98:
        return turned
    right = forward.cross(up).normalized()
    level = Matrix((right, right.cross(forward).normalized(), -forward)).transposed().to_quaternion()
    if level.dot(turned) < 0:
        level.negate()
    target = turned.slerp(level, min(1.0, max(0.0, (0.98 - steep) / 0.13)))
    angle = turned.rotation_difference(target).angle
    if angle > max_level and angle > 1e-6:
        target = turned.slerp(target, max_level / angle)
    return target


def smootherstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * x * (x * (6 * x - 15) + 10)


def _move_profile(total, v_max, accel):
    """Distance over time, symmetric: starting and braking each as an S-curve (speed follows smoothstep, peak acceleration
    accel), constant in between. Returns (duration, s(t), v(t)); short distances never reach v_max."""
    v = min(v_max, math.sqrt(total * accel / 1.5))
    ta = 1.5 * v / accel
    d_ramp = 0.75 * v * v / accel
    cruise = max(0.0, (total - 2 * d_ramp) / v)
    duration = 2 * ta + cruise

    def s_at(t):
        if t <= 0:
            return 0.0
        if t < ta:
            x = t / ta
            return v * ta * (x ** 3 - x ** 4 / 2)
        if t < ta + cruise:
            return d_ramp + v * (t - ta)
        if t < duration:
            x = (duration - t) / ta
            return total - v * ta * (x ** 3 - x ** 4 / 2)
        return total

    def v_at(t):
        if t <= 0 or t >= duration:
            return 0.0
        return v * smoothstep(min(t / ta, (duration - t) / ta, 1.0))

    return duration, s_at, v_at


def _monotone(times, values):
    """Monotone cubic interpolation (Fritsch and Carlson): no overshoot beyond a gaze point."""
    n = len(times)
    if n == 1:
        return lambda t: values[0]
    d = [(values[k + 1] - values[k]) / max(1e-9, times[k + 1] - times[k]) for k in range(n - 1)]
    m = [d[0]] + [0.0 if d[k - 1] * d[k] <= 0 else 2 / (1 / d[k - 1] + 1 / d[k]) for k in range(1, n - 1)] + [d[-1]]

    def f(t):
        k = 0
        while k < n - 2 and t > times[k + 1]:
            k += 1
        h = max(1e-9, times[k + 1] - times[k])
        x = min(1.0, max(0.0, (t - times[k]) / h))
        h00, h10, h01, h11 = 2 * x ** 3 - 3 * x ** 2 + 1, x ** 3 - 2 * x ** 2 + x, -2 * x ** 3 + 3 * x ** 2, x ** 3 - x ** 2
        return h00 * values[k] + h10 * h * m[k] + h01 * values[k + 1] + h11 * h * m[k + 1]
    return f


def morph_leg(leg, fps, profile, rules, hfov, up_at, q_start, walked):
    """One leg from stop to stop, like a PowerPoint Morph transition: position and gaze move over the same time from one
    board to the next, both with a soft start and end, without stopping in between, so the camera glides naturally.
    The gaze is a continuous curve in yaw and pitch through the view directions of the waypoints (passage, board without a
    click) at the time they are passed. A damped head that brakes at every target and snaps into place makes the motion look
    jerky, and snapping onto the target camera during the last metres while still gliding sideways looks like stepping
    back; this approach avoids both. If the path at the start points against the gaze, the gaze first turns into the
    walking direction and then the walk begins.
    Returns (frames, passage times of the waypoints in frames from the start, walked), or None if the leg is too short."""
    speed = float(profile["speed"])
    start, goal = leg[0], leg[-1]
    v_max = max([float(goal.get("max_speed", speed))] + [float(s.get("max_speed", 0)) for s in leg[1:-1]])
    accel = float(profile.get("accel", 2.5))
    dt = 1.0 / fps
    points, marks = rounded_polyline([s["location"] for s in leg], float(profile["corner_radius"]), max(0.02, v_max * dt / 2))
    lengths = arc_lengths(points)
    total = lengths[-1]
    q_goal = goal["rotation"].to_quaternion() if hasattr(goal["rotation"], "to_quaternion") else Quaternion(goal["rotation"])
    fwd_start, fwd_goal = (q_start @ Vector((0, 0, -1))).normalized(), (q_goal @ Vector((0, 0, -1))).normalized()
    if not accel or (total < 0.05 and fwd_start.angle(fwd_goal, 0.0) < 0.02):   # same pose (turning book pages): nothing to morph
        return None
    if total < 0.05:   # turning on the spot: look at something, nod, then walk off
        points, lengths, total = [Vector(start["location"]), Vector(goal["location"])], [0.0, max(1e-4, total)], max(1e-4, total)
    u0 = up_at(Vector(start["location"]))
    u0 = Vector(u0).normalized()
    e1 = fwd_start - u0 * fwd_start.dot(u0)
    e1 = e1.normalized() if e1.length > 1e-3 else u0.orthogonal().normalized()
    e2 = u0.cross(e1)

    def to_ref(direction, loc):   # transfer a direction into the frame at the start (up u0): the ring curves underneath the path
        up = Vector(up_at(loc)).normalized()
        return up.rotation_difference(u0) @ direction

    def from_ref(direction, loc):
        up = Vector(up_at(loc)).normalized()
        return u0.rotation_difference(up) @ direction

    def yaw_pitch(direction):
        pitch = math.asin(max(-1.0, min(1.0, direction.dot(u0))))
        flat = direction - u0 * direction.dot(u0)
        return (math.atan2(flat.dot(e2), flat.dot(e1)) if flat.length > 0.17 else None), pitch   # within 10 degrees of the pole: yaw undefined

    duration, s_at, v_at = _move_profile(total, v_max, accel)
    backward_ok = bool(goal.get("backward_ok"))
    tangent0 = at_length(points, lengths, min(total, 1.0))[0] - Vector(start["location"])
    tangent0 = tangent0.normalized() if tangent0.length > 1e-3 else fwd_goal
    turn_limit = math.radians(float(profile.get("morph_turn_dps", 70.0)))
    # Gaze keys: (time, direction in the frame at the start); waypoints with a gaze at the time they are passed
    keys = [(0.0, fwd_start)]
    delay = 0.0
    # Look into the walking direction first only on longer legs: on a short leg (about 2 m) the gaze would otherwise
    # overshoot sideways into the walking direction before turning to the target
    back = fwd_start.dot(tangent0) < -0.2 and not backward_ok and total > 3.0
    if back:   # look into the walking direction first, then walk: a key when setting off, halfway between walking direction and target
        aim = blend_dir(tangent0, fwd_goal, 0.35, u0)
        delay = max(float(profile.get("look_first_max", 1.5)), fwd_start.angle(aim, 0.0) * 1.6 / turn_limit)
        keys.append((delay + 0.15 * duration, to_ref(aim, Vector(start["location"]))))
    else:
        delay = min(float(profile.get("look_first_max", 1.5)) * 0.5, fwd_start.angle(fwd_goal, 0.0) / turn_limit * 0.5)

    def time_at_length(target):
        lo, hi = 0.0, duration
        for _ in range(40):
            mid = (lo + hi) / 2
            if s_at(mid) < target:
                lo = mid
            else:
                hi = mid
        return hi
    passages = []
    for stop, mark in zip(leg[1:-1], marks[1:-1]):
        t_pass = delay + time_at_length(lengths[min(mark, len(lengths) - 1)])
        passages.append(t_pass)
        # A gaze point shortly before the target (less than 1.5 s) gets no key of its own, otherwise the turn rate jumps
        # there (from about 37 to 56 degrees per second in one frame) and the approach looks rough
        if stop.get("look_weight", 0) > 0 and delay + duration - t_pass > 1.5:
            gaze = forward_of(stop["rotation"]).normalized()
            _, tangent_k = at_length(points, lengths, lengths[min(mark, len(lengths) - 1)])
            if not backward_ok and gaze.dot(tangent_k) < -0.2:   # gaze point behind us (would mean walking backwards):
                gaze = blend_dir(tangent_k, gaze, 0.45, u0)   # glance sideways in passing, about 80 degrees off the walking direction
            keys.append((t_pass, to_ref(gaze, Vector(stop["location"]))))
    # Path in the middle points against both gazes (would mean several metres backwards): look into the walking direction on the way
    if not backward_ok and len(keys) <= (2 if back else 1):
        loc_m, tangent_m = at_length(points, lengths, total / 2)
        if total > 2.0 and fwd_start.dot(tangent_m) < -0.2 and fwd_goal.dot(tangent_m) < -0.2:
            keys.append((delay + duration / 2, to_ref(tangent_m, loc_m)))
    # Walk up while looking at the target (approach_look, for example a book on a desk): at 60 % of the leg a gaze key on the
    # board's look-at point; the morph's turn limit still applies (blending per frame instead turned at almost 180 degrees per
    # second close to the target)
    if goal.get("approach_look") and goal.get("look_at") is not None and total > 1.0:
        loc_a = at_length(points, lengths, s_at(0.6 * duration))[0]
        to_target = Vector(goal["look_at"]) - loc_a
        if to_target.length > 0.5:
            keys = [k for k in keys if not (delay + 0.45 * duration < k[0] < delay + duration)]   # waypoint gazes in between give way
            keys.append((delay + 0.6 * duration, to_ref(to_target.normalized(), loc_a)))
    keys.append((delay + duration, to_ref(fwd_goal, Vector(goal["location"]))))
    keys.sort(key=lambda k: k[0])
    # Unwrap yaw continuously (shortest way per step); at the pole take the yaw from the neighbour
    yaws, pitches = [], []
    for _, d in keys:
        y, p = yaw_pitch(d)
        yaws.append(y)
        pitches.append(p)
    known = [y for y in yaws if y is not None]
    if not known:
        return None
    for k in range(len(yaws)):
        if yaws[k] is None:
            yaws[k] = next((yaws[j] for j in range(k - 1, -1, -1) if yaws[j] is not None), known[0])
    for k in range(1, len(yaws)):
        delta = (yaws[k] - yaws[k - 1] + math.pi) % (2 * math.pi) - math.pi
        # Turn direction: for a large angle pick the side on which the gaze at mid-leg is close to the walking direction; for
        # a turn of almost 180 degrees the shortest way went over the shoulder and the camera walked several metres backwards
        if abs(delta) > math.radians(100) and not backward_ok:
            t_mid = (keys[k - 1][0] + keys[k][0]) / 2
            loc_m, tangent_m = at_length(points, lengths, s_at(t_mid - delay))
            y_walk, _ = yaw_pitch(to_ref(tangent_m, loc_m))
            if y_walk is not None:
                other = delta - math.copysign(2 * math.pi, delta)
                off = lambda d: abs((yaws[k - 1] + d / 2 - y_walk + math.pi) % (2 * math.pi) - math.pi)
                if off(other) < off(delta):
                    delta = other
        yaws[k] = yaws[k - 1] + delta
    total_time = max(0.5, delay + duration)
    # Fixed duration of the leg (travel_seconds at the target), for example a slow glide along a timeline; path and gaze are
    # stretched together
    wanted = float(goal.get("travel_seconds", 0) or 0)
    if wanted > total_time:
        k = wanted / total_time
        keys = [(t * k, d) for t, d in keys]
        passages = [t * k for t in passages]
        delay, duration, total_time = delay * k, duration * k, wanted
        s_at = (lambda f, g: (lambda t: f(t / g)))(s_at, k)
        v_at = (lambda f, g: (lambda t: f(t / g) / g))(v_at, k)
    # Limit the turn rate: if the gaze is too fast, the whole leg takes longer (position and gaze together, like a morph)
    for _ in range(4):
        # Keys in gaze time: the curve runs over tau = T smootherstep(t / T), and a waypoint should be reached when it is
        # passed (real time t)
        tk = [total_time * smootherstep(k[0] / total_time) for k in keys]
        for k in range(1, len(tk)):
            tk[k] = max(tk[k], tk[k - 1] + 1e-3)
        yaw_f, pitch_f = _monotone(tk, yaws), _monotone(tk, pitches)
        n = max(2, math.ceil(total_time * fps))
        peak = 0.0
        prev = None
        for i in range(n + 1):
            tau = total_time * smootherstep(i / n)
            y, p = yaw_f(tau), pitch_f(tau)
            d = (e1 * math.cos(y) + e2 * math.sin(y)) * math.cos(p) + u0 * math.sin(p)
            if prev is not None:
                peak = max(peak, prev.angle(d, 0.0) * n / total_time)
            prev = d
        if peak <= turn_limit * 1.02:
            break
        stretch = peak / turn_limit
        keys = [(k[0] * stretch, k[1]) for k in keys]
        passages = [t * stretch for t in passages]
        delay *= stretch
        total_time *= stretch
        duration *= stretch
        s_prev, v_prev, factor = s_at, v_at, stretch
        s_at = (lambda f, g: (lambda t: f(t / g)))(s_prev, factor)
        v_at = (lambda f, g: (lambda t: f(t / g) / g))(v_prev, factor)
    n = max(2, math.ceil(total_time * fps))
    frames = []
    q_prev = q_start.copy()
    v_peak = max(1e-6, max(v_at(duration * x / 20) for x in range(21)))
    stride = float(profile.get("stride", speed / float(profile["step_hz"])))
    last_s = 0.0
    for i in range(1, n + 1):
        u = i / n
        tau = total_time * smootherstep(u)   # gaze time, soft at start and end (camera at rest at the stop)
        t = u * total_time   # time of the legs (walking)
        s = s_at(t - delay)
        loc, _ = at_length(points, lengths, s)
        y, p = yaw_f(tau), pitch_f(tau)
        fwd = from_ref((e1 * math.cos(y) + e2 * math.sin(y)) * math.cos(p) + u0 * math.sin(p), loc).normalized()
        up = up_at(loc)
        q = pose_from(fwd, up, q_prev)
        # Roll and pitch of the boards (book, tilted stops): ease out of the start pose at the beginning, into the target pose at the end
        w_in, w_out = 1 - smootherstep(u / 0.25), smootherstep((u - 0.75) / 0.25)
        for qq, w in ((q_start, w_in), (q_goal, w_out)):
            if w > 0:
                qq = qq.copy()
                if qq.dot(q) < 0:
                    qq.negate()
                q = q.slerp(qq, w)
        if i == n:
            loc, q = Vector(goal["location"]), q_goal.copy()
        if q.dot(q_prev) < 0:
            q.negate()
        walked += s - last_s
        last_s = s
        # Walking sway only at travel speed (swaying while starting off looks like a camera being taken out of a cupboard),
        # almost still while looking at the target at the end. No walking sway in zero g (zero_g at the target): one pulls
        # oneself along the handrail and floats evenly, without steps
        if up is not False and v_max <= 1.5 * speed and i < n and not goal.get("zero_g"):
            v = v_at(t - delay)
            scale = smoothstep((v / v_peak - 0.75) / 0.25) * (float(profile.get("sway_focus", 1.0)) if u > 0.7 else 1.0)
            if scale > 0:
                phase = 2 * math.pi * walked / (2 * stride)
                right = fwd.cross(Vector(up)).normalized()
                loc = loc + right * (float(profile["sway_lateral"]) * math.sin(phase) * scale) \
                    + Vector(up) * (float(profile["sway_vertical"]) * math.sin(2 * phase + math.pi / 2) * scale)
        frames.append((loc, q))
        q_prev = q
    return frames, [round(t * fps) for t in passages], walked


def walk_segment(stops, fps, profile, rules, hfov, up_at, first_frame):
    """One segment between two cuts. stops: list of dict(name, location, rotation, dwell_seconds, pass (waypoint),
    max_speed, max_speed_reason, look_weight). Returns (frames, timeline, overrides): frames is a list of (location,
    quaternion) from first_frame on, timeline has one entry per stop (name, arrive, frame), overrides are for check_motion.py."""
    speed = float(profile["speed"])
    turn_rate = hfov / float(rules["pan_seconds_per_frame_width"])
    dt = 1.0 / fps
    frames, timeline, overrides = [], [], []
    # Legs: from stop to stop via the waypoints in between
    legs, current = [], [stops[0]]
    for stop in stops[1:]:
        current.append(stop)
        if not stop.get("pass"):
            legs.append(current)
            current = [stop]
    if len(current) > 1:
        legs.append(current)
    frame = first_frame
    q_prev = stops[0]["rotation"].to_quaternion() if hasattr(stops[0]["rotation"], "to_quaternion") else Quaternion(stops[0]["rotation"])
    fwd_prev = q_prev @ Vector((0, 0, -1))
    start_fwd = fwd_prev.copy()   # gaze at the stop most recently left
    walked = 0.0   # distance since the start, phase of the walking profile
    hold = round(float(stops[0].get("dwell_seconds", 0)) * fps)
    for _ in range(hold + 1):
        frames.append((Vector(stops[0]["location"]), q_prev.copy()))
    timeline.append({"name": stops[0]["name"], "arrive": frame, "frame": frame + hold})
    frame += hold + 1
    for leg in legs:
        start, goal = leg[0], leg[-1]
        v_max = float(goal.get("max_speed", speed))
        for stop in leg[1:-1]:
            v_max = max(v_max, float(stop.get("max_speed", 0)))
        if goal.get("locked"):   # inside the cabin: fixed orientation, only the path (S-curve), no turning, no levelling
            points, marks = rounded_polyline([s["location"] for s in leg], float(profile["corner_radius"]), max(0.02, v_max * dt / 2))
            lengths = arc_lengths(points)
            leg_start_frame = frame
            duration, s_at, _ = _move_profile(max(1e-4, lengths[-1]), v_max, float(profile.get("accel", 2.5)) * max(1.0, v_max / speed))
            n = max(1, math.ceil(duration * fps))
            for i in range(1, n + 1):
                frames.append((at_length(points, lengths, s_at(duration * i / n))[0], q_prev.copy()))
            frame += n
            arrive = frame - 1
            hold = round(float(goal.get("dwell_seconds", 0)) * fps)
            for _ in range(hold):
                frames.append((Vector(goal["location"]), q_prev.copy()))
            frame += hold
            for stop, mark in zip(leg[1:-1], marks[1:-1]):
                s_mark = lengths[min(mark, len(lengths) - 1)]
                passed = leg_start_frame + next((i for i in range(1, n + 1) if s_at(duration * i / n) >= s_mark), n)
                timeline.append({"name": stop["name"], "arrive": min(passed, arrive), "frame": min(passed, arrive)})
            timeline.append({"name": goal["name"], "arrive": arrive, "frame": frame - 1})
            if v_max > speed:
                overrides.append({"start": leg_start_frame, "end": arrive, "max_speed": v_max,
                                  "reason": goal.get("max_speed_reason", "") or "Wegpunkt mit max_speed"})
            fwd_prev = (q_prev @ Vector((0, 0, -1))).normalized()
            start_fwd = fwd_prev
            continue
        # on foot in the museum: morph; elevator, hub and exterior flight keep the model below
        morph = None
        if (profile.get("morph", True) and v_max <= 1.5 * speed and up_at(Vector(start["location"])) is not False
                and up_at(Vector(goal["location"])) is not False):
            morph = morph_leg(leg, fps, profile, rules, hfov, up_at, q_prev, walked)
        if morph is not None:
            leg_frames, passed, walked = morph
            leg_start_frame = frame
            frames += leg_frames
            frame += len(leg_frames)
            arrive = frame - 1
            q_goal = goal["rotation"].to_quaternion() if hasattr(goal["rotation"], "to_quaternion") else Quaternion(goal["rotation"])
            hold = round(float(goal.get("dwell_seconds", 0)) * fps)
            for _ in range(hold):
                frames.append((Vector(goal["location"]), q_goal.copy()))
            frame += hold
            for stop, offset in zip(leg[1:-1], passed):
                timeline.append({"name": stop["name"], "arrive": min(leg_start_frame + offset, arrive), "frame": min(leg_start_frame + offset, arrive)})
            timeline.append({"name": goal["name"], "arrive": arrive, "frame": frame - 1})
            q_prev, fwd_prev = q_goal.copy(), (q_goal @ Vector((0, 0, -1))).normalized()
            start_fwd = fwd_prev
            continue
        points, marks = rounded_polyline([s["location"] for s in leg], float(profile["corner_radius"]), max(0.02, v_max * dt / 2))
        lengths = arc_lengths(points)
        total = lengths[-1]
        ease_d = max(0.05, v_max * float(profile["ease_seconds"]) / 2)
        if total < 2 * ease_d:
            ease_d = total / 2
        q_goal = goal["rotation"].to_quaternion() if hasattr(goal["rotation"], "to_quaternion") else Quaternion(goal["rotation"])
        fwd_goal = q_goal @ Vector((0, 0, -1))
        # Gaze targets of waypoints with their own gaze (via with look): arc length and direction
        gazes = []
        for stop, mark in zip(leg[1:-1], marks[1:-1]):
            if stop.get("look_weight", 0) > 0:
                gazes.append((lengths[min(mark, len(lengths) - 1)], forward_of(stop["rotation"]), float(stop["look_weight"])))
        # Gaze points on the way (a person may look to one side while walking in another direction, and looks up at what is
        # high): up to a passage or waypoint with a gaze, a point 5 m beyond it in its view direction (into the next room),
        # after that the look-at point of the target board (look_at, with height); without look_at the direction of the target camera
        look_points = [(g_s, Vector(stop["location"]) + g_fwd * 5.0)
                       for (g_s, g_fwd, _), stop in zip(gazes, [s for s in leg[1:-1] if s.get("look_weight", 0) > 0])]
        goal_point = Vector(goal["look_at"]) if goal.get("look_at") is not None else None
        side_cos = math.cos(math.radians(float(profile.get("side_look_degrees", 110))))
        omega = float(profile.get("head_omega", 6.0))
        head_speed = 0.0   # angular speed of the head (rad/s), critically damped: speeds up and slows down
        accel = float(profile.get("accel", 0.0)) * max(1.0, v_max / speed)   # elevator and exterior flight accelerate proportionally harder
        # Gaze lead: enough time to complete the turn towards the target at the limited rate
        approach_angle = fwd_prev.angle(fwd_goal, 0.0)
        lead = max(float(profile["look_lead_seconds"]), approach_angle / turn_rate * 1.3 + 0.3)
        release = float(profile["look_release_seconds"])
        # Gaze pinned to the wall, like eyes fixed on a timeline while sliding along it: if start and target look in almost
        # the same direction at nearby points, the look-at point glides from board to board, without panning and without a
        # sideways glance (moving sideways does not require panning sideways)
        start_point = Vector(start["look_at"]) if start.get("look_at") is not None else None
        track = (start_point is not None and goal_point is not None and not look_points
                 and (goal_point - start_point).length < float(profile.get("track_max_m", 25))
                 and start_fwd.angle(fwd_goal, 0.0) < math.radians(float(profile.get("track_max_degrees", 35))))
        backward_ok = bool(goal.get("backward_ok"))
        # Look first, then walk (look up at the next banner, then set off slowly while accelerating): if the target lies far
        # off the current gaze, the head turns first
        aim0 = (goal_point - Vector(start["location"])).normalized() if goal_point is not None and (goal_point - Vector(start["location"])).length > 0.5 else fwd_goal
        look_first = 0.0 if track else min(float(profile.get("look_first_max", 1.5)), start_fwd.angle(aim0, 0.0) / turn_rate * 0.8)
        # Inertia (mass does not start instantly): starting as an S-curve (smooth, the acceleration builds up softly and
        # fades out softly), peak acceleration accel; time to reach v_max is 1.5 v_max / accel
        t_acc = 1.5 * v_max / accel if accel else 0.0
        leg_start_frame = frame
        s, t_leg = 0.0, 0.0
        ease_t = float(profile["ease_seconds"])
        while s < total - 1e-6:
            # Speed: starting over time (first frame close to zero), braking over the distance before the stop
            t_leg += dt
            # first frame after the stop without movement (camera at rest at the marker), then a soft start; brake over the distance before the stop
            if accel:   # fixed acceleration: short legs between nearby boards never reach full speed and
                # stay unhurried
                t_move = t_leg - dt - look_first
                v = min(v_max * smoothstep(t_move / t_acc), math.sqrt(1.6 * accel * max(0.0, total - s)))
                v = 0.0 if t_move <= dt * 0.5 else max(v, 0.05)
            else:
                ease = min(smoothstep((t_leg - dt) / ease_t) if ease_t else 1.0, smoothstep((total - s) / ease_d) if ease_d else 1.0)
                v = v_max * max(0.0 if t_leg <= dt * 1.5 else 0.03, ease)
            s = min(total, s + v * dt)
            walked += v * dt
            loc, tangent = at_length(points, lengths, s)
            remaining = (total - s) / v_max
            # Desired gaze: walking direction, before that the target, after that briefly the old stop; waypoints pull briefly
            # Update the lead continuously: the gaze follows the path on the way, so the remaining angle to the target can be
            # larger than estimated when setting off (otherwise a few degrees were left over and done in a single frame on arrival)
            lead = max(lead, fwd_prev.angle(fwd_goal, 0.0) / turn_rate * 1.3 + 0.3,
                       q_prev.rotation_difference(q_goal).angle % (2 * math.pi) / turn_rate * 1.3 + 0.3 if q_prev.dot(q_goal) >= 0
                       else q_prev.rotation_difference(-q_goal).angle / turn_rate * 1.3 + 0.3)   # also roll and pitch of the target
            w_goal = smoothstep(1 - remaining / lead) if lead else 0.0
            w_hold = 1 - smoothstep(t_leg / release) if release else 0.0
            # Walking backwards (the subject stays in front of us, we never turn round): if the path points away from both
            # gazes, the gaze glides from the old to the new target instead of turning round to follow the path
            heading = tangent
            view_ref = start_fwd.lerp(fwd_goal, smoothstep(s / total))
            if view_ref.length > 1e-3 and tangent.dot(view_ref) < 0:
                heading = view_ref.normalized()
                if not backward_ok:   # backwards only where the board asks for it (dolly out); otherwise look at the target,
                    heading = (goal_point - loc).normalized() if goal_point is not None and (goal_point - loc).length > 0.5 else fwd_goal   # since unmotivated backward walking looks odd
            # Moving vertically (cabin in the axis tube): in an elevator one looks horizontally, not up the shaft
            up_here = up_at(loc)
            if up_here is not False and abs(tangent.dot(up_here)) > 0.7 and view_ref.length > 1e-3:
                heading = view_ref.normalized()
                flat = view_ref - Vector(up_here) * view_ref.dot(up_here)
                # only in the axis tube (up is the world axis); at the foot of a spoke up still points to the axis, and there the
                # gaze tilted towards a direction that turned during the cross-fade (the horizon tilted by almost 80 degrees)
                if tangent.dot(up_here) > 0 and flat.length > 1e-3 and abs(Vector(up_here).z) > 0.95:   # going up (towards the sun) tilted forward:
                    tilt = math.radians(float(profile.get("lift_look_degrees", 55)))   # we simply look ahead and watch the modules
                    heading = (flat.normalized() * math.cos(tilt) + Vector(up_here) * math.sin(tilt)).normalized()   # come closer;
                    # azimuth from view_ref, no tilting past the vertical; going down the view stays horizontal
            # Look at what comes next: passage, then exhibit; if it lies more than side_look_degrees off the walking direction
            # (behind us), keep the walking direction; vertical travel and walking backwards keep heading
            focus = False
            point = next((p for g_s, p in look_points if g_s > s + 0.3), goal_point)
            if track:
                glide = start_point.lerp(goal_point, smoothstep(s / total))
                if (glide - loc).length > 0.5:
                    heading, focus = (glide - loc).normalized(), True
                    w_hold = 0.0   # no lingering on the old stop, and the target camera only over the last 15 % of the leg
                    w_goal = min(w_goal, smoothstep(1 - (total - s) / max(0.5, total * 0.15)))
            elif point is not None and heading is tangent and (point - loc).length > 0.5:
                to_point = (point - loc).normalized()
                if to_point.dot(tangent) > side_cos:
                    heading, focus = to_point, point is goal_point
            up_now = up_at(loc)
            desired = blend_dir(heading, fwd_goal, w_goal, up_now)
            if w_hold > 0:
                desired = blend_dir(desired, start_fwd, w_hold, up_now)
            if not look_points:   # legacy waypoints without a gaze point (should not occur) pull briefly
                for g_s, g_fwd, g_w in gazes:
                    near = 1 - min(1.0, abs(g_s - s) / max(0.5, v_max * float(profile["look_lead_seconds"])))
                    if near > 0:
                        desired = blend_dir(desired, g_fwd, g_w * smoothstep(near), up_now)
            desired = desired.normalized()
            # The turn rate ramps up softly after the stop (no jolt when starting to turn) and stays limited
            # Turning and levelling, like the movement, only start one frame after the stop (otherwise the camera turns at the marker)
            ramp = 0.0 if t_leg <= dt * 1.5 else (smoothstep((t_leg - dt) / max(0.2, ease_t / 2)) if ease_t else 1.0)
            up = up_at(loc)
            # Critically damped head (pans at a fixed rate look lifeless): the turn accelerates towards the target and brakes
            # before reaching it instead of running at a fixed rate; peak at most turn_rate
            remaining_angle = fwd_prev.angle(desired, 0.0)
            head_speed += (omega * omega * remaining_angle - 2 * omega * head_speed) * dt
            head_speed = max(0.0, min(0.85 * turn_rate, head_speed))   # headroom for levelling below the overall limit
            fwd = turn_like_head(fwd_prev, desired, head_speed * dt * ramp, up)
            if s >= total - 1e-6:
                fwd = fwd_goal
            q = pose_from(fwd, up, q_prev, turn_rate * dt * ramp)
            if s >= total - 1e-6:
                q = q_goal.copy()
            elif w_goal > 0:
                qq = q_goal.copy()
                if qq.dot(q) < 0:
                    qq.negate()
                q = q.slerp(qq, w_goal ** 2)   # roll and pitch of the target (book) only come in at the very end
            if s < total - 1e-6:
                # Limit the total rotation per frame (gaze, levelling and blend to the target camera together): limited one by
                # one they added up to well over the limit; and if the lead is longer than the leg, w_goal is already high when
                # setting off, which produced extreme turn rates
                if q.dot(q_prev) < 0:
                    q.negate()
                step = q_prev.rotation_difference(q).angle
                limit = 0.95 * turn_rate * dt * max(ramp, 0.05)   # turn_rate already is the pan limit (a factor of 1.2 on top was too fast)
                if step > limit and w_goal > 0.5 and s > 0.8 * total:   # (only on the last fifth: earlier it already blended
                    # when setting off and rolled the camera) shortly before the stop the target camera's pose counts (roll and pitch,
                    q = q_prev.slerp(q, limit / step)   # for example a book): head straight for it, otherwise a remainder is left for arrival
                elif step > limit:   # shorten the head step and rebuild the pose: a slerp between two level poses
                    # with yaw and pitch is not level itself (it produced visible roll during a full turn)
                    # the head may take the full allowed step; scaled down proportionally it never turned when the slerp towards
                    # the target camera made the step large (the camera then snapped round on arrival)
                    # Budget: three quarters head, one quarter levelling (equal shares together exceeded the limit); in the
                    # elevator half and half, since up itself rotates there (transition from ring to spoke)
                    level_share = 0.5 if v_max > 1.5 * speed else 0.25
                    fwd_c = turn_like_head(fwd_prev, fwd, (1 - level_share) * limit, up)
                    q = pose_from(fwd_c, up, q_prev, level_share * limit)
                    if q.dot(q_prev) < 0:
                        q.negate()
                    fwd = fwd_c
            if ramp == 0.0:
                q = q_prev.copy()   # first frame after the stop: same pose as at the stop, even on short legs with an early look at the target
            if q.dot(q_prev) < 0:
                q.negate()
            # Walking profile: lateral one cycle per double step, vertical one per step; only when walking, not in zero g (zero_g)
            if up is not False and v_max <= 1.5 * speed and not goal.get("zero_g"):
                stride = float(profile.get("stride", speed / float(profile["step_hz"])))   # fixed stride length, cadence follows the speed
                phase = 2 * math.pi * walked / (2 * stride)
                scale = min(1.0, v / speed) * (float(profile.get("sway_focus", 1.0)) if focus or w_goal > 0.3 else 1.0)
                right = fwd.cross(up).normalized()
                loc = loc + right * (float(profile["sway_lateral"]) * math.sin(phase) * scale) \
                    + Vector(up) * (float(profile["sway_vertical"]) * math.sin(2 * phase + math.pi / 2) * scale)
            frames.append((loc, q))
            # Take the gaze from the final pose: the blend towards the target camera makes q differ from the stored gaze, and
            # the next frame would otherwise catch up the difference all at once
            q_prev, fwd_prev = q, (q @ Vector((0, 0, -1))).normalized()
            frame += 1
            if frame - leg_start_frame > 20 * 60 * fps:
                raise RuntimeError(f"Fahrt zu {goal['name']} läuft nicht an (Strecke {total:.1f} m)")
        # Arrival: exactly the board's camera, then the dwell
        frames[-1] = (Vector(goal["location"]), q_goal.copy())
        arrive = frame - 1
        hold = round(float(goal.get("dwell_seconds", 0)) * fps)
        for _ in range(hold):
            frames.append((Vector(goal["location"]), q_goal.copy()))
        frame += hold
        for stop, mark in zip(leg[1:-1], marks[1:-1]):   # waypoints in the timeline (for reports and checks), at the time they are passed
            passed = leg_start_frame + int(lengths[min(mark, len(lengths) - 1)] / max(v_max * dt, 1e-6))
            timeline.append({"name": stop["name"], "arrive": min(passed, arrive), "frame": min(passed, arrive)})
        timeline.append({"name": goal["name"], "arrive": arrive, "frame": frame - 1})
        if v_max > speed:
            overrides.append({"start": leg_start_frame, "end": arrive, "max_speed": v_max,
                              "reason": goal.get("max_speed_reason", "") or "Wegpunkt mit max_speed"})
        q_prev, fwd_prev = q_goal.copy(), fwd_goal
        start_fwd = fwd_goal
    return frames, timeline, overrides
