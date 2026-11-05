"""Inside Blender: render a preview image for every module folder (Workbench, quick, no textures needed).

Usage: run Blender in background with this script, then Blender's argument separator, then <station folder> [module ...]
(the full command line is in tools/README.md). Writes <station folder>/<module>/preview.png.

Each preview frames the module's main objects (FOCUS), may show neighbouring modules for context (CONTEXT, linked from their
files) and cuts away everything between camera and target, like a doll's house, so interiors are visible.
"""
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

args = sys.argv[sys.argv.index("--") + 1:]
root = Path(args[0])
only = set(args[1:])
SKIP = re.compile(r"^(Stern|Kabel|Faden|Fäden|Withheld|PolyHaven)")   # long cables and markers would blow up the frame
FOCUS = {"elevator": r"^Aufzug(sturm|shalle|skabine|srahmen)", "hub_map_room": r"^(Kartenraum|Kugel im Kartenraum)",
         "knowledge_globe": r"^(Wissenskugel|DB2|Kugelsäule)", "station_structure": r"^(Ring|Kollektor|Speiche|Achsrohr)",
         "environment": r"^Stern", "polyhaven_placements": r"^PolyHaven"}
ROOMS = [f"museum_room_{n}" for n in range(1, 8)]
CONTEXT = {**{r: ["museum_building"] for r in ROOMS}, "polyhaven_placements": ["museum_building"], "knowledge_globe": ["museum_building"]}
INSIDE = set(ROOMS) | {"hub_lobby", "polyhaven_placements", "knowledge_globe", "museum_building", "hub_map_room"}
WALK_IN = set(ROOMS) | {"knowledge_globe"}   # camera stands in the room at eye height and looks along the ring
NEAR = {"knowledge_globe": ("Kugelsäule", 30.0)}
# seen from above (from the axis side in the ring, from the shadow side in the hub) with everything above the cut removed:
# (cut height above the centre of the module in metres)
TOP_CUT = {"museum_room_2": 2.5, "museum_room_4": 2.5, "museum_building": 1.5, "hub_lobby": 0.5}
SIDE_CUT = {"hub_map_room"}   # front half cut away to show the funnel inside
WALK_IN -= set(TOP_CUT)
BACKGROUND = (0.11, 0.12, 0.13)   # the same opaque dark grey behind every preview


def bounds(objects):
    low, high = Vector((1e9, 1e9, 1e9)), Vector((-1e9, -1e9, -1e9))
    for obj in objects:
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box] if obj.type == "MESH" else [obj.matrix_world.translation]
        for p in corners:
            low, high = Vector(map(min, low, p)), Vector(map(max, high, p))
    return low, high


def place(cam, eye, look, up):
    """Put the camera at eye, looking at look, with the place's "up" up in the picture; wide lens for interiors."""
    forward = (look - eye).normalized()
    right = forward.cross(up).normalized()
    cam.matrix_world = Matrix((right.to_4d(), right.cross(forward).to_4d(), (-forward).to_4d(), (0, 0, 0, 1))).transposed()
    cam.matrix_world.translation = eye
    cam.data.lens, cam.data.clip_start, cam.data.clip_end = 14, 0.05, 2000


for folder in sorted(p for p in root.iterdir() if p.is_dir() and (p / f"{p.name}.blend").exists()):
    mid = folder.name
    if only and mid not in only:
        continue
    bpy.ops.wm.open_mainfile(filepath=str(folder / f"{mid}.blend"))
    scene = bpy.context.scene
    scene.frame_set(1)
    focus = re.compile(FOCUS[mid]) if mid in FOCUS else None
    targets = [o for o in scene.objects if (focus.search(o.name) if focus else (o.type == "MESH" and not SKIP.search(o.name)))]
    targets = targets or [o for o in scene.objects if o.type == "MESH"] or list(scene.objects)
    anchor = next((o for o in scene.objects if NEAR.get(mid) and o.name.startswith(NEAR[mid][0])), None)
    if anchor is not None:   # the module holds copies far apart: keep only what is near the anchor
        def middle(o):
            return sum((o.matrix_world @ Vector(c) for c in o.bound_box), Vector()) / 8 if o.type == "MESH" else o.matrix_world.translation
        targets = [o for o in targets if (middle(o) - middle(anchor)).length < NEAR[mid][1]]
    low, high = bounds(targets)
    centre, size = (low + high) / 2, max(max(high - low), 2.0)
    for other in CONTEXT.get(mid, []):   # neighbours for context, linked as collection instances
        with bpy.data.libraries.load(str(root / other / f"{other}.blend"), link=True) as (src, dst):
            dst.collections = [other]
        holder = bpy.data.objects.new(f"context {other}", None)
        holder.instance_type, holder.instance_collection = "COLLECTION", dst.collections[0]
        scene.collection.objects.link(holder)
    radial = Vector((centre.x, centre.y, 0.0))
    if mid in INSIDE and radial.length > 50:   # in the ring: "up" points to the axis, look along the ring
        up = -radial.normalized()
        along = Vector((-centre.y, centre.x, 0.0)).normalized()
        direction = (-along * 1.0 + up * 0.45 + Vector((0, 0, 0.25))).normalized()
    else:
        up = Vector((0, 0, 1))
        direction = Vector((0.6, -1.0, 0.7 if mid not in INSIDE else -0.5)).normalized()
    distance = size * (1.3 if mid not in INSIDE else 1.0)
    cam = bpy.data.objects.new("Preview", bpy.data.cameras.new("Preview"))
    scene.collection.objects.link(cam)
    cam.location = centre + direction * distance
    forward = (centre - cam.location).normalized()
    cam.rotation_euler = forward.to_track_quat("-Z", "Y").to_euler()
    right = forward.cross(up).normalized()   # roll the camera so that "up" of the place is up in the picture
    if right.length > 0:
        cam_up = right.cross(forward)
        cam.matrix_world = Matrix((right.to_4d(), cam_up.to_4d(), (-forward).to_4d(), (0, 0, 0, 1))).transposed()
        cam.matrix_world.translation = centre + direction * distance
    cam.data.lens = 24 if mid in INSIDE else 35
    cam.data.clip_start = max(distance - size * 0.55, 0.05) if mid in INSIDE else max(size / 5000, 0.01)   # doll's house cut
    cam.data.clip_end = distance + size * 20
    if mid in TOP_CUT:
        top_up = up if radial.length > 50 else Vector((0, 0, -1))   # hub: "up" is the shadow side
        side = along if radial.length > 50 else Vector((1, 0, 0))
        height = size * 1.1
        eye = centre + top_up * height + side * height * 0.35
        place(cam, eye, centre, side)
        cam.data.lens = 24
        cam.data.clip_start = max((eye - centre).dot(top_up) - TOP_CUT[mid], 0.05)   # removes roof and ceiling
        cam.data.clip_end = height * 20
    if mid in SIDE_CUT:
        cam.data.clip_start = distance
    candidates = []
    if mid in WALK_IN and radial.length > 50:   # stand inside: candidate places between the centre and the nearest wall
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for d in (along, -along, (along + up * 0.3).normalized(), (-along + up * 0.3).normalized(),
                  (along + Vector((0, 0, 0.5))).normalized(), (-along + Vector((0, 0, -0.5))).normalized()):
            hit, location, *_ = scene.ray_cast(depsgraph, centre, d, distance=size * 1.5)
            free = (location - centre).length if hit else size * 1.5
            for lift in (0.0, 2.0):
                candidates.append((centre + d * max(min(free - 1.0, size * 0.9), 0.5) + up * lift, centre - up * (0.5 if lift else 0.0)))
    scene.camera = cam
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"   # shows the packed panel images
    scene.render.film_transparent = False
    for flag in ("date", "time", "render_time", "frame", "frame_range", "memory", "hostname", "camera", "lens", "scene", "marker",
                 "filename", "sequencer_strip", "note"):   # no metadata in the PNG (it would carry the local path and time)
        setattr(scene.render, f"use_stamp_{flag}", False)
    scene.render.use_stamp = False
    world = scene.world or bpy.data.worlds.new("Preview")
    scene.world = world
    world.color = BACKGROUND
    scene.display.shading.show_cavity = True
    for image in bpy.data.images:   # files that are not in the repository show as plain grey, not as missing-texture pink
        if image.source == "FILE" and not image.packed_file:
            image.source = "GENERATED"
            image.generated_type = "BLANK"
            image.generated_color = (0.55, 0.55, 0.55, 1.0)
    if mid == "polyhaven_placements":   # empties do not render: show each place as a small marker sphere
        mat = bpy.data.materials.new("place")
        mat.diffuse_color = (0.9, 0.45, 0.0, 1.0)
        for obj in [o for o in scene.objects if o.name.startswith("PolyHaven")]:
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.35, location=obj.matrix_world.translation)
            bpy.context.active_object.data.materials.append(mat)
    if candidates:   # render each candidate small and keep the one with the most detail (mean difference of neighbouring pixels)
        probe = Path(__file__).resolve().parent / "_work" / "preview_probe.png"
        probe.parent.mkdir(exist_ok=True)
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 192, 108, 100
        best = None
        for eye, look in candidates:
            place(cam, eye, look, up)
            scene.render.filepath = str(probe)
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(str(probe), check_existing=False)
            w = img.size[0]
            values = list(img.pixels)[0::4]
            bpy.data.images.remove(img)
            detail = sum(abs(values[i] - values[i + 1]) + abs(values[i] - values[i + w])
                         for i in range(len(values) - w - 1) if (i + 1) % w) / len(values)
            if best is None or detail > best[0]:
                best = (detail, eye, look)
        place(cam, best[1], best[2], up)
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1280, 720, 100
    scene.render.filepath = str(folder / "preview.png")
    bpy.ops.render.render(write_still=True)
    print(f"preview {mid}: {round(size)} m", flush=True)
