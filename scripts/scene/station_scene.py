"""Grey-box model of the whole station: a ring of 180 floor plates, six spokes towards the rear (spokes_depth), a standing hub
with a honeycomb collector (edge at the bottom), three outer mirror rings, mirrors in the gaps and six centre mirrors, modules
from the honeycomb plan (hub_layout_cells.yaml) with corridor modules and a tube railway, a distribution mirror at the rear of
the axis tube, a hangar at the rim and a docking module on the axis (highlighted in green); the museum (station.museum), the
bar and the homes at the feet of the spokes. Dimensions come from building.yaml (block station).

Usage (run inside Blender through a launcher that passes the arguments):
        station_scene.py --building --threads 8 [--shots 21,22] [--no-clip] [--realtime]
        Storyboard: ... station_scene.py --building --storyboard storyboard_station.yaml [--panels 01.1,05.3]
        Higher quality: add --team (1920 x 1080, 64 samples, separate output folder)

Scene axes: z points to the sun, the collector lies at z = 0, the ring reaches from z = 0 to z = -rim_depth.
Spoke 0 points to -y (the museum stands there), the others follow at 60° intervals.
"""
import json
import math
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from szene_bausteine import glow, model, pbr, setup_render, solid  # noqa: E402

T0 = time.perf_counter()
CONFIG = json.loads(sys.argv[sys.argv.index("--") + 1])
if "config_file" in CONFIG:   # long configuration passed as a file (the Windows command line has a length limit)
    CONFIG = json.loads(Path(CONFIG["config_file"]).read_text(encoding="utf-8"))
ARGS = sys.argv[sys.argv.index("--") + 2:]
STATION = CONFIG["station"]
BASE = Path(__file__).resolve().parent.parent
REPO = BASE.parents[3]
OUT = REPO / "_Ressourcen" / "3D_Bibliothek" / "Entwürfe" / "2026-10-28_Boden_Skizzen"
OUT.mkdir(parents=True, exist_ok=True)

R = float(STATION["radius"])
RIM = float(STATION["rim_thickness"])
DEPTH = float(STATION["rim_depth"])
PANELS = int(STATION.get("panels", 180))
SPOKE_Z = -float(STATION.get("spokes_depth", 140))
HUB = STATION.get("hub", {})
COLLECTOR = float(HUB.get("collector_radius", 240))
CELL = float(HUB.get("cell_width", 10))
RPM = float(STATION["rpm"])

scene = bpy.context.scene
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)


# ---------------------------------------------------------------- helpers
def mesh_object(name, bm, mat, parent=None):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.data.materials.append(mat)
    if parent:
        obj.parent = parent
    return obj


def prism(bm, points, z_top, z_bottom):
    """Vertical prism from an outline (list of (x, y)) between z_top and z_bottom."""
    top = [bm.verts.new((x, y, z_top)) for x, y in points]
    bottom = [bm.verts.new((x, y, z_bottom)) for x, y in points]
    bm.faces.new(top)
    bm.faces.new(list(reversed(bottom)))
    n = len(points)
    for i in range(n):
        bm.faces.new((top[i], top[(i + 1) % n], bottom[(i + 1) % n], bottom[i]))


def hexagon(cx, cy, circum, rot=90.0):
    return [(cx + circum * math.cos(math.radians(rot + 60 * k)), cy + circum * math.sin(math.radians(rot + 60 * k))) for k in range(6)]


def box_at(bm, centre, tangent_angle, size):
    """Box inside the ring: centre (x, y, z), local axes tangential, radial, axial; size (tangential, radial, axial)."""
    t = Vector((-math.sin(tangent_angle), math.cos(tangent_angle), 0))
    r = Vector((math.cos(tangent_angle), math.sin(tangent_angle), 0))
    z = Vector((0, 0, 1))
    c = Vector(centre)
    corners = []
    for st in (-1, 1):
        for sr in (-1, 1):
            for sz in (-1, 1):
                corners.append(c + t * st * size[0] / 2 + r * sr * size[1] / 2 + z * sz * size[2] / 2)
    v = [bm.verts.new(p) for p in corners]
    for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        bm.faces.new([v[i] for i in face])


def glass(name, color, alpha):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = 0.1
    bsdf.inputs["Alpha"].default_value = alpha
    mat.surface_render_method = "BLENDED"
    return mat


def stars(count=1500, distance=6000.0):
    random.seed(11)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=6.0, location=(0, 0, -distance))
    star = bpy.context.active_object
    star.data.materials.append(glow("Stern", (1.0, 1.0, 1.0), 8.0))
    normal = random.normalvariate
    for _ in range(count):
        v = Vector((normal(0, 1), normal(0, 1), normal(0, 1))).normalized() * distance
        if v.z > distance * 0.6:   # no stars right next to the sun
            continue
        dup = bpy.data.objects.new("Stern", star.data)
        dup.location = v
        scene.collection.objects.link(dup)


def world():
    """The camera sees black, the lighting gets some grey (grey box; otherwise the inside of the ring would be dark)."""
    w = bpy.data.worlds.new("Weltraum")
    scene.world = w
    w.use_nodes = True
    nodes, links = w.node_tree.nodes, w.node_tree.links
    nodes.clear()
    out, mix = nodes.new("ShaderNodeOutputWorld"), nodes.new("ShaderNodeMixShader")
    dark, light = nodes.new("ShaderNodeBackground"), nodes.new("ShaderNodeBackground")
    path = nodes.new("ShaderNodeLightPath")
    dark.inputs["Color"].default_value = (0, 0, 0, 1)
    light.inputs["Color"].default_value = (0.35, 0.37, 0.42, 1)
    light.inputs["Strength"].default_value = 0.6
    links.new(path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    links.new(light.outputs[0], mix.inputs[1])
    links.new(dark.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])


def camera(location, target, lens=24, up=None):
    """Camera with a look-at target; up = the direction that is up in the image (inside the ring: towards the axis), else world y."""
    cam = bpy.data.cameras.new("Kamera")
    cam.lens, cam.clip_start, cam.clip_end = lens, 0.5, 20000
    obj = bpy.data.objects.new("Kamera", cam)
    scene.collection.objects.link(obj)
    obj.location = location
    forward = (Vector(target) - Vector(location)).normalized()
    if up is None:
        obj.rotation_euler = forward.to_track_quat("-Z", "Y").to_euler()
    else:
        right = forward.cross(Vector(up)).normalized()
        true_up = right.cross(forward).normalized()
        obj.rotation_euler = Matrix((right, true_up, -forward)).transposed().to_euler()
    scene.camera = obj
    return obj


def render(name):
    scene.render.filepath = str(OUT / name)
    bpy.ops.render.render(write_still=True)
    print("geschrieben:", OUT / name)


# ---------------------------------------------------------------- materials
m_shell = solid("Ringhülle", (0.55, 0.56, 0.6), roughness=0.6, metallic=0.4)
m_floor = solid("Ringboden", (0.42, 0.5, 0.38), roughness=0.9)
m_ceiling = glass("Ringdecke", (0.7, 0.8, 0.95), 0.12)
m_spoke = glass("Speiche", (0.75, 0.82, 0.95), 0.25)
m_cabin = solid("Aufzug", (0.9, 0.62, 0.0), roughness=0.5)
m_collector = solid("Kollektor", (0.04, 0.08, 0.22), roughness=0.25, metallic=0.6)
m_frame = solid("Kollektorrahmen", (0.3, 0.3, 0.33), roughness=0.5, metallic=0.7)
m_module = solid("Modul", (0.78, 0.78, 0.8), roughness=0.4, metallic=0.5)
m_window = glow("Modulfenster", (1.0, 0.8, 0.55), 2.0)
m_axis = solid("Achsrohr", (0.85, 0.85, 0.88), roughness=0.4, metallic=0.6)
m_bearing = solid("Lager", (0.0, 0.45, 0.7), roughness=0.4, metallic=0.6)
m_mirror = solid("Spiegel", (0.9, 0.9, 0.92), roughness=0.05, metallic=1.0)
m_dish = solid("Verteilspiegel", (0.56, 0.27, 0.68), roughness=0.1, metallic=0.9)   # purple, as in the original sketch
m_hangar = solid("Hangar", (0.0, 0.62, 0.45), roughness=0.5, metallic=0.4)          # proposed addition, set off in colour
m_corridor = glass("Gang", (0.6, 0.85, 1.0), 0.35)
m_museum = solid("Museum", (0.84, 0.37, 0.0), roughness=0.6)
m_hall = glass("Mittelraum", (0.95, 0.7, 0.4), 0.45)
m_house = solid("Haus", (0.93, 0.9, 0.85), roughness=0.8)
m_bar = solid("Bar", (0.8, 0.47, 0.65), roughness=0.6)

setup_render(scene, width=CONFIG.get("probe_width", 640), height=CONFIG.get("probe_height", 360), samples=16, bloom=0.15)
scene.eevee.use_raytracing = False   # ray-traced glass cost about four minutes per frame inside the station
# quality level "team": 1920 x 1080, 64 samples, separate folder;
# ray tracing stays off (glass inside, see above)
TEAM = "--team" in ARGS
if TEAM:
    OUT = REPO / "_Ressourcen" / "3D_Bibliothek" / "Entwürfe" / "2026-10-29_Team_Renders"
    OUT.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.eevee.taa_render_samples = 64
world()
stars()

def hull_material(name, folder, tile=8.0, paint=(0.8, 0.81, 0.84), panels=None):
    """Hull of the modules seen from outside: light painted panels like the hulls of the ISS modules; from Poly Haven (CC0) only
    the seams (normals) and roughness, box-projected on object coordinates, tile size tile m. The colour map stays off: metal_plate
    (checker plate) and metal_plate_02 are rusty brown and made the modules look brownish black. Without the texture files the
    plain grey box is used. panels = (width, height) in m: large panels with seams in cylinder coordinates around the axis (hull
    of the torus)."""
    files = {k: next(iter(folder.glob(f"*_{k}_1k.jpg")), None) for k in ("rough", "nor_gl")}
    if not files["nor_gl"]:
        return m_module
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Metallic"].default_value = 0.15   # painted panels scatter the light of the mirrors instead of the black of space
    coords, mapping = nodes.new("ShaderNodeTexCoord"), nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1 / tile,) * 3
    links.new(coords.outputs["Object"], mapping.inputs["Vector"])

    def image(key, non_color):
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(files[key]), check_existing=True)
        if non_color:
            tex.image.colorspace_settings.name = "Non-Color"
        tex.projection, tex.projection_blend = "BOX", 0.2
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        return tex
    bsdf.inputs["Base Color"].default_value = (*paint, 1.0)
    if files["rough"]:
        links.new(image("rough", True).outputs["Color"], bsdf.inputs["Roughness"])
    normal = None
    if files["nor_gl"]:
        normal = nodes.new("ShaderNodeNormalMap")
        links.new(image("nor_gl", True).outputs["Color"], normal.inputs["Color"])
        links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
    if panels:   # large panels with seams, so the hull reads as many plates bolted together
        # cylinder coordinates around the axis: u = angle times radius (arc length), v = z + radius; this puts the grid in metres
        # on the outer hull (fixed radius) as well as on the end walls (fixed z) and the roof
        sep, length = nodes.new("ShaderNodeSeparateXYZ"), nodes.new("ShaderNodeVectorMath")
        links.new(coords.outputs["Object"], sep.inputs["Vector"])
        length.operation = "LENGTH"
        flat = nodes.new("ShaderNodeCombineXYZ")
        links.new(sep.outputs["X"], flat.inputs["X"])
        links.new(sep.outputs["Y"], flat.inputs["Y"])
        links.new(flat.outputs["Vector"], length.inputs[0])
        angle, arc, v = nodes.new("ShaderNodeMath"), nodes.new("ShaderNodeMath"), nodes.new("ShaderNodeMath")
        angle.operation, arc.operation, v.operation = "ARCTAN2", "MULTIPLY", "ADD"
        links.new(sep.outputs["Y"], angle.inputs[0])
        links.new(sep.outputs["X"], angle.inputs[1])
        links.new(angle.outputs[0], arc.inputs[0])
        arc.inputs[1].default_value = R
        links.new(sep.outputs["Z"], v.inputs[0])
        links.new(length.outputs["Value"], v.inputs[1])
        uv = nodes.new("ShaderNodeCombineXYZ")
        links.new(arc.outputs[0], uv.inputs["X"])
        links.new(v.outputs[0], uv.inputs["Y"])
        brick = nodes.new("ShaderNodeTexBrick")
        links.new(uv.outputs["Vector"], brick.inputs["Vector"])
        brick.inputs["Scale"].default_value = 1.0
        brick.inputs["Brick Width"].default_value, brick.inputs["Row Height"].default_value = panels
        brick.inputs["Mortar Size"].default_value = 0.12
        brick.inputs["Color1"].default_value = (*paint, 1.0)
        brick.inputs["Color2"].default_value = (*(c * 0.88 for c in paint), 1.0)   # panels tinted slightly differently
        brick.inputs["Mortar"].default_value = (0.18, 0.19, 0.21, 1.0)
        links.new(brick.outputs["Color"], bsdf.inputs["Base Color"])
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.6
        links.new(brick.outputs["Fac"], bump.inputs["Height"])
        if normal is not None:
            links.new(normal.outputs["Normal"], bump.inputs["Normal"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


m_shell = hull_material("Ringhülle Platten (Poly Haven metal_plate_02)", BASE / "media" / "polyhaven" / "metal_plate_02",
                         paint=(0.62, 0.63, 0.67), panels=(14.0, 6.0))   # panels with seams instead of a smooth surface


# ---------------------------------------------------------------- ring (rotates): floor of 180 plates, glass roof, end walls
rotor = bpy.data.objects.new("Rotor", None)
scene.collection.objects.link(rotor)
angles = [2 * math.pi * k / PANELS for k in range(PANELS)]
outer = [(R * math.cos(a), R * math.sin(a)) for a in angles]
inner = [((R - RIM) * math.cos(a), (R - RIM) * math.sin(a)) for a in angles]
# Hull with thickness and rounded outer edges: the cross-section (r, z) is a closed outline swept around the axis; the cavity
# inside stays as before (floor at R, end walls at z = 0 and -DEPTH), the thickness grows outwards
HULL_T, HULL_FILLET = float(STATION.get("hull_thickness", 3.0)), float(STATION.get("hull_fillet", 8.0))


def fillet(cr, cz, start_deg, end_deg, radius, steps=6):
    return [(cr + radius * math.cos(math.radians(start_deg + (end_deg - start_deg) * s / steps)),
             cz + radius * math.sin(math.radians(start_deg + (end_deg - start_deg) * s / steps))) for s in range(steps + 1)]


ro, fr = R + HULL_T, HULL_FILLET
profile = ([(R - RIM, 0.0), (R, 0.0), (R, -DEPTH), (R - RIM, -DEPTH), (R - RIM, -DEPTH - HULL_T)]      # inside, then edge on the shadow side
           + fillet(ro - fr, -DEPTH - HULL_T + fr, 270, 360, fr)                                      # outer edge, shadow side
           + fillet(ro - fr, HULL_T - fr, 0, 90, fr)                                                  # outer edge, sun side
           + [(R - RIM, HULL_T)])                                                                      # edge, sun side
bm = bmesh.new()
rings = [[bm.verts.new((r * math.cos(a), r * math.sin(a), z)) for r, z in profile] for a in angles]
for i in range(PANELS):
    j = (i + 1) % PANELS
    for k in range(len(profile)):
        m = (k + 1) % len(profile)
        bm.faces.new((rings[i][k], rings[i][m], rings[j][m], rings[j][k]))
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
mesh_object("Ring", bm, m_shell, rotor)
bm = bmesh.new()
for i in range(PANELS):   # floor as a separate green surface just inside the hull
    j = (i + 1) % PANELS
    rr = R - 0.5
    bm.faces.new([bm.verts.new((rr * math.cos(angles[i]), rr * math.sin(angles[i]), -1)),
                  bm.verts.new((rr * math.cos(angles[j]), rr * math.sin(angles[j]), -1)),
                  bm.verts.new((rr * math.cos(angles[j]), rr * math.sin(angles[j]), -DEPTH + 1)),
                  bm.verts.new((rr * math.cos(angles[i]), rr * math.sin(angles[i]), -DEPTH + 1))])
mesh_object("Ringboden", bm, m_floor, rotor)
# Roof over the city as an arch: glass vault between the end walls, ROOF_ARCH m closer to the axis in the middle, with no
# central strut; the solid rim on both sides follows the arch; ribs every --roof-ribs degrees (default 20) as arches.
# An opening remains at each spoke (the elevator tower and the spoke pass through)
ROOF_ARCH = float(STATION.get("roof_arch", 12.0))
RIB_DEG = float(ARGS[ARGS.index("--roof-ribs") + 1]) if "--roof-ribs" in ARGS else float(STATION.get("roof_rib_degrees", 20.0))
ROOF_BORDER, RIB_W, ROOF_STEPS = 12.0, 1.2, 30
roof_spokes = [-math.pi / 2 + k * math.pi / 3 for k in range(6)]   # as spoke_angles below


def roof_r(z):
    """Distance of the roof from the axis at depth z (0 on the sun side to -DEPTH): R - RIM at the end walls, ROOF_ARCH closer in the middle."""
    return R - RIM - ROOF_ARCH * math.sin(math.pi * min(DEPTH, max(0.0, -z)) / DEPTH)


def roof_height(depth):
    """Height of the roof above the ring floor (as in on_ring) at depth depth (positive towards the shadow side)."""
    return R - 0.5 - roof_r(-depth)


def near_spoke(a, z, margin=9.0):
    """Does the point (angle a, depth z) on the roof lie close to a spoke? (spokes at SPOKE_Z, radius 7.5 m)"""
    gap = min(abs(math.remainder(a - s, 2 * math.pi)) for s in roof_spokes) * (R - RIM)
    return gap < margin and abs(z - SPOKE_Z) < margin


zs = [-DEPTH * k / ROOF_STEPS for k in range(ROOF_STEPS + 1)]
bm, bm_rim, bm_ribs = bmesh.new(), bmesh.new(), bmesh.new()
for i in range(PANELS):
    j = (i + 1) % PANELS
    for z0, z1 in zip(zs, zs[1:]):
        quad = [(angles[i], z0), (angles[j], z0), (angles[j], z1), (angles[i], z1)]
        bm.faces.new([bm.verts.new((roof_r(z) * math.cos(a), roof_r(z) * math.sin(a), z)) for a, z in quad])
        if (z0 > -ROOF_BORDER or z1 < -DEPTH + ROOF_BORDER) and not near_spoke((angles[i] + angles[j]) / 2, (z0 + z1) / 2, 9.0 + ROOF_BORDER / 2):
            bm_rim.faces.new([bm_rim.verts.new(((roof_r(z) + 0.3) * math.cos(a), (roof_r(z) + 0.3) * math.sin(a), z)) for a, z in quad])
mesh_object("Ringdecke", bm, m_ceiling, rotor)
rib_count = max(1, round(360 / RIB_DEG))
for n in range(rib_count):
    a = 2 * math.pi * n / rib_count
    for z0, z1 in zip(zs, zs[1:]):
        zm = (z0 + z1) / 2
        if near_spoke(a, zm) or not (-DEPTH + ROOF_BORDER < zm < -ROOF_BORDER):
            continue
        box_at(bm_ribs, Vector(((roof_r(zm) + 0.9) * math.cos(a), (roof_r(zm) + 0.9) * math.sin(a), zm)), a,
               (RIB_W, 1.5, abs(z1 - z0) + 0.4))
mesh_object("Ringdach Rand", bm_rim, m_shell, rotor)
mesh_object("Ringdach Rippen", bm_ribs, m_shell, rotor)

# spokes (glass tubes with an elevator cabin), bearing ring at the axis
m_spoke_wall = hull_material("Speichenwand Platten", BASE / "media" / "polyhaven" / "metal_plate_02", tile=3.0, paint=(0.6, 0.62, 0.66))   # panelled hull;
# the closed side of the spoke also gets a panel pattern
spoke_angles = [-math.pi / 2 + k * math.pi / 3 for k in range(6)]
for k, a in enumerate(spoke_angles):
    d = Vector((math.cos(a), math.sin(a), 0))
    start, end = 14.0, R - RIM
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=7.5, depth=end - start, end_fill_type="NOTHING",   # open: the cabin
                                        location=d * (start + end) / 2 + Vector((0, 0, SPOKE_Z)))   # runs through into the axis tube
    spoke = bpy.context.active_object
    spoke.name = f"Speiche {k}"
    spoke.rotation_mode = "QUATERNION"
    spoke.rotation_quaternion = d.to_track_quat("Z", "Y")
    spoke.data.materials.append(m_spoke)
    # glass only towards the sun: with a window on one side only, a rider can turn away and no longer sees the rotation;
    # locally +Y points to the sun, the window to the hub is there, wall elsewhere
    spoke.data.materials.append(m_spoke_wall)
    for poly in spoke.data.polygons:
        poly.material_index = 0 if poly.normal.y > 0.25 else 1
    spoke.parent = rotor
    bm = bmesh.new()
    box_at(bm, d * (start + (end - start) * (0.35 + 0.1 * k)) + Vector((0, 0, SPOKE_Z)), a, (3.5, 3.0, 3.5))
    mesh_object(f"Aufzug {k}", bm, m_cabin, rotor)
# bearing ring around the standing axis tube (inner 11 m, outer 24 m), open where the spokes arrive: the cabin runs from the
# spoke through the ring to the centre and on into the axis tube
COLLAR_IN, COLLAR_OUT, COLLAR_H, COLLAR_GAP = 11.0, 24.0, 10.0, 8.0
bm = bmesh.new()
for i in range(96):
    for j in range(4):
        a_0, a_1 = 2 * math.pi * i / 96, 2 * math.pi * (i + 1) / 96
        r_0, r_1 = COLLAR_IN + (COLLAR_OUT - COLLAR_IN) * j / 4, COLLAR_IN + (COLLAR_OUT - COLLAR_IN) * (j + 1) / 4
        mid = Vector(((r_0 + r_1) / 2 * math.cos((a_0 + a_1) / 2), (r_0 + r_1) / 2 * math.sin((a_0 + a_1) / 2), 0))
        if any(mid.dot(Vector((math.cos(s), math.sin(s), 0))) > 0 and
               abs(mid.cross(Vector((math.cos(s), math.sin(s), 0))).z) < COLLAR_GAP for s in spoke_angles):
            continue   # opening for the spoke
        corners = [(r_0, a_0), (r_1, a_0), (r_1, a_1), (r_0, a_1)]
        for z in (SPOKE_Z - COLLAR_H / 2, SPOKE_Z + COLLAR_H / 2):
            bm.faces.new([bm.verts.new((r * math.cos(a), r * math.sin(a), z)) for r, a in corners])
        for r in ((r_0,) if j == 0 else ()) + ((r_1,) if j == 3 else ()):
            bm.faces.new([bm.verts.new((r * math.cos(a), r * math.sin(a), z)) for a, z in
                          ((a_0, SPOKE_Z - COLLAR_H / 2), (a_1, SPOKE_Z - COLLAR_H / 2), (a_1, SPOKE_Z + COLLAR_H / 2), (a_0, SPOKE_Z + COLLAR_H / 2))])
collar = mesh_object("Lagerkranz", bm, m_bearing, rotor)

# buildings in the ring: museum at spoke 0 (station.museum), bar at spoke 1, homes at spokes 2 to 5, scattered houses
MUSEUM = STATION.get("museum", {"centre": [0, 100], "diameter": 100, "hall_circumradius": 42, "height": 12,
                                "lift": {"at": [0, 140]}})
a0 = spoke_angles[0]


def on_ring(along, depth, height):
    """Point in the ring: along = m in the direction of rotation from spoke 0, depth = m towards the shadow side, height = m above the floor."""
    a = a0 + along / R
    return Vector((math.cos(a), math.sin(a), 0)) * (R - 0.5 - height) + Vector((0, 0, -depth))


def ring_prism(name, outline, height, mat, base=0.0, bm=None, open_bottom=False, side_tags=()):
    """Vertical solid on the ring floor; the bottom follows the curvature (plates of 2°), outline in (along, depth).
    With bm the solid is only added to that mesh (several solids in one object). If bm has a face layer "tag",
    the bottom gets 2 and the sides whose index is in side_tags get 1 (to remove them after the normals are recalculated)."""
    own = bm is None
    bm = bmesh.new() if own else bm
    tag = bm.faces.layers.int.get("tag")
    bottom = [bm.verts.new(on_ring(u, v, base)) for u, v in outline]
    top = [bm.verts.new(on_ring(u, v, base + height)) for u, v in outline]
    if not open_bottom:   # a large polygon on the curved floor would rise up to floor_rise above the floor in the middle
        face = bm.faces.new(bottom)
        if tag is not None:
            face[tag] = 2
    face = bm.faces.new(list(reversed(top)))
    if tag is not None:
        face[tag] = 4   # top (glass roof of the museum rooms)
    n = len(outline)
    for i in range(n):
        face = bm.faces.new((bottom[i], bottom[(i + 1) % n], top[(i + 1) % n], top[i]))
        if tag is not None and i in side_tags:
            face[tag] = side_tags[i] if isinstance(side_tags, dict) else 1
    return mesh_object(name, bm, mat, rotor) if own else None


def two_sided(name, outside, inside, roughness=0.6):
    """One colour outside, another inside (Geometry > Backfacing): a closed solid that reads as a room from inside."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out, mix, geo = nodes.new("ShaderNodeOutputMaterial"), nodes.new("ShaderNodeMixShader"), nodes.new("ShaderNodeNewGeometry")
    shaders = []
    for color in (outside, inside):
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["Base Color"].default_value = (*color, 1)
        bsdf.inputs["Roughness"].default_value = roughness
        shaders.append(bsdf)
    links.new(geo.outputs["Backfacing"], mix.inputs["Fac"])
    links.new(shaders[0].outputs[0], mix.inputs[1])
    links.new(shaders[1].outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


mx, my = MUSEUM["centre"]
# direction of the gate in the plan: 90 = shadow side, towards the foot of the spoke; 270 would be the sun side.
# Room 1 lies at the gate, the other rooms follow anticlockwise with decreasing angle.
GATE_DEG = int(CONFIG.get("museum_gate_deg", 90))
GATE_SIGN = 1 if GATE_DEG == 90 else -1   # +1: gate at my + mr (shadow side), -1: at my - mr


def k_of_room(room):
    """Index k of the room solid (arc from 60k to 60(k+1) degrees) for rooms 1 to 6."""
    return (int(round((GATE_DEG - 30) / 60)) - (room - 1)) % 6

# scale of the museum: museum_scale shrinks the building, the exhibits and their positions; the camera's eye height, the
# lectern, the furniture and the Borgis stay at human size
S = float(CONFIG.get("museum_scale", 0.5))   # default: half size
mr = MUSEUM["diameter"] / 2 * S
hall_r = MUSEUM["hall_circumradius"] * S
museum_h = max(5.0, MUSEUM.get("height", 12) * S)
hall_top = max(museum_h + 8.0, 30 * S)   # lantern above the centre room
tube_h = max(museum_h + 4.0, 26 * S)     # glass tube of the elevator below the lantern
# openings at human size from building.yaml (station.museum.doors), variants via --doors
DOORS = {**MUSEUM.get("doors", {}), **CONFIG.get("museum_doors", {})}
gate_h = min(float(DOORS.get("gate_height", museum_h * 0.75)), museum_h - 0.3)
main_h = min(float(DOORS.get("main_height", museum_h * 0.75)), museum_h - 0.3)
print(f"Türen: Tor {gate_h} m, Center-Tür {main_h} m, Durchgang {DOORS.get('passage_width')} x {DOORS.get('passage_height')} m", flush=True)
BOARD_EARLY = json.loads(Path(CONFIG["storyboard_file"]).read_text(encoding="utf-8")) if CONFIG.get("storyboard_file") else {}


def palette_color(ref):
    """Colour from wkw_palette.py by name (PAPER, WKW.700, STEEL.300, OKABE_ITO.orange); graubox = the orange of the grey box."""
    if ref == "graubox":
        return (0.84, 0.37, 0.0)
    import wkw_palette
    name, _, step = str(ref).partition(".")
    value = getattr(wkw_palette, name)
    return tuple(value[step] if step else value)


# facade from the corporate design (building.yaml station.museum.facade; field facade in the storyboard for comparisons)
FACADE_SPEC = dict(MUSEUM.get("facade", {}))   # in the storyboard: facade as a colour name or as a set of fields as in building.yaml
board_facade = BOARD_EARLY.get("facade")
FACADE_SPEC.update({"color": board_facade} if isinstance(board_facade, str) else (board_facade or {}))
FACADE = palette_color(FACADE_SPEC.get("color", "graubox"))
print(f"Fassade: {FACADE_SPEC}", flush=True)


def room_outline(k, r_out, r_in_scale=1.0, steps=12, inner_steps=1):
    """Outline of the room between corners 60k and 60(k+1) of the centre room: arc of the outer wall, then the side of the hexagon.
    inner_steps > 1 splits the inner wall into pieces so that it follows the curvature of the ring as a surface (a single 42 m
    chord stood 0.2 m in front of the panels lying on the curved ring in the middle and hid them)."""
    a0_, a1_ = math.radians(60 * k), math.radians(60 * (k + 1))
    arc = [(mx + r_out * math.cos(a0_ + (a1_ - a0_) * i / steps), my + r_out * math.sin(a0_ + (a1_ - a0_) * i / steps)) for i in range(steps + 1)]
    c1 = (mx + hall_r * r_in_scale * math.cos(a1_), my + hall_r * r_in_scale * math.sin(a1_))
    c0 = (mx + hall_r * r_in_scale * math.cos(a0_), my + hall_r * r_in_scale * math.sin(a0_))
    inner = [(c1[0] + (c0[0] - c1[0]) * j / inner_steps, c1[1] + (c0[1] - c1[1]) * j / inner_steps) for j in range(inner_steps + 1)]
    return arc + inner


# Museum: six closed room solids around the open centre room instead of a single disc, so that the centre room stays open up
# to 30 m; orange outside, light house colour inside (two_sided). Before, the window band was a full disc 5 to 6.6 m high above
# all rooms and glowed like a ceiling.
from wkw_palette import WKW  # noqa: E402
bm_museum, bm_floor, bm_band = bmesh.new(), bmesh.new(), bmesh.new()
bm_museum.faces.layers.int.new("tag")
INNER_STEPS = 8   # pieces of the inner wall (so it follows the curvature of the ring)
for k in range(6):
    outline_body = room_outline(k, mr, inner_steps=INNER_STEPS)
    n_out = len(outline_body)   # faces 0 to 11 arc, 12 and n-1 partitions to the neighbouring room (the walls with
    tags = {12: 1, n_out - 1: 1}   # passage stand there), 13 to n-2 the inner wall to the centre room (see-through from one side)
    tags.update({j: 3 for j in range(13, n_out - 1)})
    if k == k_of_room(1):   # room 1 (centred at GATE_DEG): the two middle arc faces are the open gate to the square, so that
        tags.update({5: 1, 6: 1, 16: 1, 17: 1})   # the title slide is visible straight through the open gate; in the inner wall
        # the main door to the centre room on the same axis, so the centre room is entered through the door seen at the very
        # start; lintel above it further down (portal, main_door_lintel)
    if k == k_of_room(6):   # room 6: the last piece of the inner wall before the passage to room 1 is the door into the centre room
        tags[n_out - 2] = 1   # (a graphic on it swings back and becomes the passage door into the
        # centre room); leaf, hinge and lintel further down (Raum 6 Tür)
    n_before = len(bm_museum.faces)
    ring_prism(None, outline_body, museum_h, None, bm=bm_museum, side_tags=tags)
    if k != k_of_room(4):   # glass roof only above room 4 (the vision room);
        bm_museum.faces.ensure_lookup_table()   # the other rooms keep their ceiling
        for f in bm_museum.faces[n_before:]:
            if f[bm_museum.faces.layers.int["tag"]] == 4:
                f[bm_museum.faces.layers.int["tag"]] = 0
    outline = room_outline(k, mr - 0.05, 0.995)   # floor from narrow strips: one large polygon curved on the ring
    arc, (i1, i0) = outline[:-2], outline[-2:]   # was not drawn completely (white floor in room 6)
    inner = [(i0[0] + (i1[0] - i0[0]) * j / (len(arc) - 1), i0[1] + (i1[1] - i0[1]) * j / (len(arc) - 1)) for j in range(len(arc))]
    for j in range(len(arc) - 1):
        ring_prism(None, [arc[j], arc[j + 1], inner[j + 1], inner[j]], 0.06, None, base=0.02, bm=bm_floor)
bmesh.ops.recalc_face_normals(bm_museum, faces=bm_museum.faces)   # on the closed solid, then remove floors and partitions:
tag_layer = bm_museum.faces.layers.int["tag"]   # the floor polygon would stand up to floor_rise high on the curved floor
for f in bm_museum.faces:   # inner wall to the centre room (tag 3): a wall from the room, see-through from the centre room
    if f[tag_layer] == 3:   # (from the centre room one sees into all rooms, at the backs of the exhibits)
        f.material_index = 1
    elif f[tag_layer] == 4:   # top: glass roof
        f.material_index = 2
# Inner walls as two separate one-sided surfaces: as part of the museum they had to be DITHERED (BLENDED on the whole solid cost
# minutes per frame), and DITHERED flickers from frame to frame at the 4 samples of the preview. Now an opaque wall facing the
# room (normal into the room) and, 1 cm in front of it, glass facing the centre room (BLENDED, free of noise), both with backface
# culling; a BLENDED material switching on Backfacing made the wall look half transparent from the room as well
bm_inner_wall, bm_inner_glass = bmesh.new(), bmesh.new()
for f in bm_museum.faces:
    if f[tag_layer] == 3:
        bm_inner_wall.faces.new([bm_inner_wall.verts.new(v.co) for v in reversed(f.verts)])
        bm_inner_glass.faces.new([bm_inner_glass.verts.new(v.co + f.normal * 0.01) for v in f.verts])
bmesh.ops.delete(bm_museum, geom=[f for f in bm_museum.faces if f[tag_layer] in (1, 2, 3)], context="FACES_ONLY")
print("Museum: Flächen", len(bm_museum.faces), "davon senkrecht", sum(1 for f in bm_museum.faces if len(f.verts) == 4))
museum_obj = mesh_object("Museum", bm_museum, two_sided("Museum zweiseitig", FACADE, WKW["50"]), rotor)


def one_way(name, wall_color, glass_color, alpha=0.12, method="DITHERED"):
    """Nearly transparent from the front (normal, towards the centre room), a wall from behind (from the room): a stage set seen from behind."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out, mix, geo = nodes.new("ShaderNodeOutputMaterial"), nodes.new("ShaderNodeMixShader"), nodes.new("ShaderNodeNewGeometry")
    see = nodes.new("ShaderNodeBsdfPrincipled")
    see.inputs["Base Color"].default_value = (*glass_color, 1)
    see.inputs["Roughness"].default_value = 0.15
    see.inputs["Alpha"].default_value = alpha
    wall = nodes.new("ShaderNodeBsdfPrincipled")
    wall.inputs["Base Color"].default_value = (*wall_color, 1)
    wall.inputs["Roughness"].default_value = 0.6
    links.new(geo.outputs["Backfacing"], mix.inputs["Fac"])
    links.new(see.outputs[0], mix.inputs[1])
    links.new(wall.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    mat.surface_render_method = method   # BLENDED on the large museum solid cost minutes per frame
    return mat


museum_obj.data.materials.append(solid("Museum ohne Innenwand", WKW["50"]))   # index 1 is free (inner walls are a separate object, below)
m_inner_wall = solid("Museum Innenwand Raumseite", WKW["50"], roughness=0.6)
m_inner_wall.use_backface_culling = True
mesh_object("Museum Innenwand", bm_inner_wall, m_inner_wall, rotor)
m_inner_glass = glass("Museum Innenwand Glas", WKW["100"], 0.22)   # BLENDED (glass), from the
m_inner_glass.use_backface_culling = True
mesh_object("Museum Innenwand Glas", bm_inner_glass, m_inner_glass, rotor)   # from the
# centre room about 80 % transparent with a faint house tint; at 0.12 and nearly colourless the wall could no longer be seen;
# frames for it further down (inner_frames)
m_roof = glass("Museum Glasdach", (0.82, 0.9, 0.96), 0.22)   # index 2
m_roof.surface_render_method = "DITHERED"
museum_obj.data.materials.append(m_roof)
mesh_object("Museum Böden", bm_floor, solid("Museumsboden", WKW["700"], roughness=0.7), rotor)
# Window band as a ring outside on the wall, with a gap above the gate and the lettering. Below the roof edge and nearly flush:
# earlier at 5.0 to 6.6 m with a room height of 6 m and 0.3 m in front of the wall, it lay as a glowing halo above the roof,
# cut into the logo's box and showed from the centre room as a strip above the walls
band_top, band_h, band_gap = museum_h - 0.4, 0.8, 10   # gap ± 10° around the gate axis: lettering 5.3 m wide, wall radius 25 m;
# 4 to 9 cm in front of the wall: otherwise the chords of the band (5.6°) stand behind the chords of the wall (5°) in the middle
for i in range(64):
    a_i, a_j = 2 * math.pi * i / 64, 2 * math.pi * (i + 1) / 64
    if any(abs(((a_i + a_j) / 2 - door_angle + math.pi) % (2 * math.pi) - math.pi) < math.radians(band_gap) for door_angle in (math.radians(GATE_DEG),)):
        continue
    ring_prism(None, [(mx + (mr + 0.09) * math.cos(a_i), my + (mr + 0.09) * math.sin(a_i)), (mx + (mr + 0.09) * math.cos(a_j), my + (mr + 0.09) * math.sin(a_j)),
                      (mx + (mr + 0.04) * math.cos(a_j), my + (mr + 0.04) * math.sin(a_j)), (mx + (mr + 0.04) * math.cos(a_i), my + (mr + 0.04) * math.sin(a_i))],
               band_h, None, base=band_top - band_h, bm=bm_band)
mesh_object("Museum Fensterband", bm_band, m_window, rotor)
# Flat glass roof over the centre room at the height of the room ceilings, replacing the glass lantern up to 15 m, so the roof
# has one uniform height and no hexagonal box floats above it. The name stays; the check counts it as glass (ray_hit).
# The thread to the hub runs up through the glass.
ring_prism("Museum Mittelraum", hexagon(mx, my, hall_r * 0.999, rot=0), 0.05, glass("Mittelraum Glasdach", WKW["100"], 0.18),
           base=museum_h - 0.05)
hall_top = museum_h   # the light of the centre room now hangs below the glass roof (hall_point)


def rods(bm, points, radius):
    """Thin rods along a sequence of points (threads, frames)."""
    for p0, p1 in zip(points, points[1:]):
        rot = (p1 - p0).to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=radius, radius2=radius, depth=(p1 - p0).length,
                              matrix=Matrix.Translation((p0 + p1) / 2) @ rot)


def inner_frames():
    """Frames of the inner walls on the centre-room side: posts about every 3 m, rails at 2.6 m and below the ceiling, so that the
    80 % transparent wall still reads as a surface; in room 1 the centre door stays free (middle of the wall, 3/8 to 5/8)."""
    bm_f = bmesh.new()
    for k in range(6):
        a0_, a1_ = math.radians(60 * k), math.radians(60 * (k + 1))
        c0 = (mx + hall_r * 0.993 * math.cos(a0_), my + hall_r * 0.993 * math.sin(a0_))
        c1 = (mx + hall_r * 0.993 * math.cos(a1_), my + hall_r * 0.993 * math.sin(a1_))

        def at(t, h):
            return on_ring(c0[0] + (c1[0] - c0[0]) * t, c0[1] + (c1[1] - c0[1]) * t, h)

        door = k == k_of_room(1)
        for j in range(8):
            t = j / 7
            if not (door and 0.36 < t < 0.64):
                rods(bm_f, [at(t, 0.0), at(t, museum_h)], 0.05)
        for h in (2.6, museum_h - 0.1):
            ts = [i / 14 for i in range(15)]
            runs = [[t for t in ts if t <= 0.36], [t for t in ts if t >= 0.64]] if door and h < main_h else [ts]
            if k == k_of_room(6) and h < R6_DOOR_H:   # door from room 6: the piece at corner 60k (t up to 1/8) stays free
                runs = [[t for t in run if t >= 1 / 8] for run in runs]
            for run in runs:
                rods(bm_f, [at(t, h) for t in run], 0.04)
    mesh_object("Museum Innenwand Rahmen", bm_f, solid("Rahmen Innenwand", WKW["800"], roughness=0.5), rotor)


# Centre room (scene 7 "everything is connected", making-of): the WissKomm Wiki globe in the middle, the threads from all rooms
# run to it; light from above. The elevator no longer stands here but as a tower at the foot of the spoke behind the museum
# (lift_tower further down), because arriving at axis height in the centre room made no sense.
# Globe in the middle: the data-tree globe (datenbaum.py: core, network, shell, orbit rings, media marks) on a column; the
# threads of the exhibits end at it
from datenbaum import build_globe, build_pipelines  # noqa: E402
globe_r, globe_h = 1.6, 3.0
globe_root = build_globe(on_ring(mx, my, globe_h), radius=globe_r, icon_dir=BASE / "_scratch" / "globe_icons" / "icons", roof_z=None)
globe_root.name = "Wissenskugel"
globe_root.parent = rotor
for obj in bpy.data.objects:
    if obj.name.startswith("DB2_") and obj.parent is None:
        obj.parent = rotor
globe_light = bpy.data.objects.get("DB2_Light")
if globe_light:   # the test lit a hall; here a room six metres high
    globe_light.data.energy = 25000 * (globe_r / 4.0) ** 2
bm_ped = bmesh.new()
rods(bm_ped, [on_ring(mx, my, 0.0), on_ring(mx, my, globe_h - globe_r + 0.1)], 0.3)
bmesh.ops.create_cone(bm_ped, cap_ends=True, segments=32, radius1=1.4, radius2=1.4, depth=0.1,
                      matrix=Matrix.Translation(on_ring(mx, my, 0.05)) @ (-Vector((on_ring(mx, my, 0).x, on_ring(mx, my, 0).y, 0)).normalized()).to_track_quat("Z", "Y").to_matrix().to_4x4())
mesh_object("Kugelsäule", bm_ped, solid("Säule", WKW["800"], roughness=0.5), rotor)
aura = bpy.data.objects.get("DB2_Aura")
if aura:   # glow shell 1.35 r without aura (it looked like a halo around the globe
    aura.hide_render = True   # and clipped into the logo): it cut through orbit rings and media marks; core, network and shell stay


def build_threads(sources):
    """Threads from the exhibits to the cabin (scene 7 "everything is connected"): sources = points (u, v, h) behind the exhibits at
    the inner wall, from the storyboard; without sources three threads per room from the inner wall. Plus the bundle from the cabin to the tube."""
    bm_threads = bmesh.new()
    if not sources:
        sources = [(mx + hall_r * 0.845 * math.cos(math.radians(60 * k + 30) + spread), my + hall_r * 0.845 * math.sin(math.radians(60 * k + 30) + spread), h0)
                   for k in range(6) for spread, h0 in ((-0.25, 3.5), (0.0, 6.0), (0.25, 4.5))]
    for u0, v0, h0 in sources:   # every thread ends at the globe in the middle
        ang = math.atan2(v0 - my, u0 - mx)
        end = (mx + globe_r * 0.9 * math.cos(ang), my + globe_r * 0.9 * math.sin(ang))
        mid = ((u0 + end[0]) / 2, (v0 + end[1]) / 2)
        pts = []
        for i in range(17):   # quadratic curve: from the wall of the room, arching upwards, onto the globe
            t = i / 16
            u = (1 - t) ** 2 * u0 + 2 * (1 - t) * t * mid[0] + t ** 2 * end[0]
            v = (1 - t) ** 2 * v0 + 2 * (1 - t) * t * mid[1] + t ** 2 * end[1]
            h = (1 - t) ** 2 * h0 + 2 * (1 - t) * t * (h0 + 0.5 * museum_h) + t ** 2 * globe_h
            pts.append(on_ring(u, v, h))
        rods(bm_threads, pts, 0.05)
    mesh_object("Fäden zur Kugel", bm_threads, glow("Faden", WKW["400"], 6.0), rotor)


hall_lamp = bpy.data.lights.new("Licht Mittelraum", "AREA")
hall_lamp.shape, hall_lamp.size = "DISK", 40 * S
hall_lamp.energy = float(CONFIG.get("museum_hall_watts", 20000)) * S * S
hall_obj = bpy.data.objects.new("Licht Mittelraum", hall_lamp)
scene.collection.objects.link(hall_obj)
hall_point = on_ring(mx, my, hall_top - 0.3)   # below the glass roof; formerly 2 m below the lantern at 15 m
hall_obj.location = hall_point
hall_obj.rotation_mode = "QUATERNION"
hall_obj.rotation_quaternion = (-Vector((hall_point.x, hall_point.y, 0)).normalized()).to_track_quat("Z", "Y")   # shines towards the floor
hall_obj.parent = rotor
for k in range(6):   # ceiling light per room: area light below the ceiling, facing the floor
    a_mid = math.radians(60 * k + 30)
    u, v = mx + mr * 0.86 * math.cos(a_mid), my + mr * 0.86 * math.sin(a_mid)
    lamp = bpy.data.lights.new(f"Museum Licht {k}", "AREA")
    lamp.shape, lamp.size, lamp.size_y = "RECTANGLE", 30 * S, 8 * S
    lamp.energy = float(CONFIG.get("museum_room_watts", 6000)) * S * S
    lamp.color = (1.0, 0.96, 0.9)
    obj = bpy.data.objects.new(f"Museum Licht {k}", lamp)
    scene.collection.objects.link(obj)
    point = on_ring(u, v, museum_h - 0.4)
    up_here = -Vector((point.x, point.y, 0)).normalized()
    # long direction of the room: perpendicular to the room centre, in the ring as (in the direction of rotation, towards the shadow side)
    x_axis = (Vector((-math.sin(a0 + u / R), math.cos(a0 + u / R), 0)) * -math.sin(a_mid) + Vector((0, 0, -1)) * math.cos(a_mid)).normalized()
    z_axis = up_here   # an area light shines along -Z, so Z towards the axis, light downwards
    y_axis = z_axis.cross(x_axis)
    obj.matrix_world = Matrix.Translation(point) @ Matrix((x_axis, y_axis, z_axis)).transposed().to_4x4()
    obj.parent = rotor
door_half = mr * math.sin(math.radians(5))   # the gate: two arc faces of 5° are missing in the wall of room 1 (above in the room solid)


def portal(sign, label):
    """Portal around an opening in the outer wall: posts and lintel, dark; closed above up to the ceiling, so that the gate stays
    a door and not a slit up to the top. sign -1: sun side (gate, 270°), +1: shadow side (back door, 90°)."""
    wall_v = my + sign * mr * math.cos(math.radians(5))
    bm_portal = bmesh.new()
    for sx in (-1, 1):
        rods(bm_portal, [on_ring(mx + sx * door_half, wall_v + sign * 0.2, 0.0), on_ring(mx + sx * door_half, wall_v + sign * 0.2, gate_h)], 0.25)
    rods(bm_portal, [on_ring(mx - door_half - 0.25, wall_v + sign * 0.2, gate_h), on_ring(mx + door_half + 0.25, wall_v + sign * 0.2, gate_h)], 0.25)
    mesh_object(f"Museum Portal {label}", bm_portal, solid("Portal", WKW["800"], roughness=0.5), rotor)
    bm_lintel = bmesh.new()
    ring_prism(None, [(mx - door_half - 0.1, wall_v + sign * 0.05), (mx + door_half + 0.1, wall_v + sign * 0.05),
                      (mx + door_half + 0.1, wall_v - sign * 0.25), (mx - door_half - 0.1, wall_v - sign * 0.25)],
               museum_h - gate_h, None, base=gate_h, bm=bm_lintel)
    bmesh.ops.recalc_face_normals(bm_lintel, faces=bm_lintel.faces)
    # colour per face instead of two_sided: the lintel is a closed box, from every side one sees its outside, so from inside
    # an orange field also appeared above the gate. Faces towards the square and the sides stay orange, those towards the room
    # and the underside get the colour of the inner wall
    at_gate = on_ring(mx, wall_v, gate_h)
    to_centre = (on_ring(mx, my, gate_h) - at_gate).normalized()
    up_gate = -Vector((at_gate.x, at_gate.y, 0)).normalized()   # up points to the axis (axis_up is only defined further down)
    for f in bm_lintel.faces:
        f.material_index = 1 if f.normal.dot(to_centre) > 0.5 or f.normal.dot(up_gate) < -0.5 else 0
    lintel = mesh_object(f"Museum Torsturz {label}", bm_lintel, solid("Torsturz außen", FACADE, roughness=0.6), rotor)
    lintel.data.materials.append(solid("Torsturz innen", WKW["50"], roughness=0.6))


portal(GATE_SIGN, "Tor")
# sliding leaves of the gate, so the museum door can be seen closing: two leaves run from the posts to the middle; one object
# per state (half: half closed, closed: shut), shown per panel through the field gate
gate_v = my + GATE_SIGN * (mr * math.cos(math.radians(5)) + 0.45)   # in front of the wall on the square side, in front of the posts
for state, share in (("half", 0.5), ("closed", 1.0)):
    bm_gate = bmesh.new()
    for sx in (-1, 1):
        outer, inner = mx + sx * (door_half + 0.1), mx + sx * (door_half + 0.1 - share * (door_half + 0.1))
        ring_prism(None, [(min(outer, inner), gate_v - 0.06), (max(outer, inner), gate_v - 0.06),
                          (max(outer, inner), gate_v + 0.06), (min(outer, inner), gate_v + 0.06)], gate_h + 0.05, None, base=0.02, bm=bm_gate)
    bmesh.ops.recalc_face_normals(bm_gate, faces=bm_gate.faces)
    mesh_object(f"Museum Tor Flügel {state}", bm_gate, solid("Torflügel", WKW["600"], roughness=0.35, metallic=0.2), rotor).hide_render = True
# Centre door of the centre room in the inner wall of room 1 (faces 16 and 17 of the inner wall are missing, so x = -5.25 to 5.25 m
# at scale 1, on the axis of the gate): lintel above and dark posts as at the gate, so that it reads as a door; plus two door
# leaves that are closed at the start (field main_door per panel)
main_outline = room_outline(k_of_room(1), mr, inner_steps=INNER_STEPS)
p_a, p_b = main_outline[16], main_outline[18]
bm_inner = bmesh.new()
ring_prism(None, [(p_a[0], p_a[1] - 0.3), (p_b[0], p_b[1] - 0.3), (p_b[0], p_b[1] + 0.3), (p_a[0], p_a[1] + 0.3)],
           museum_h - main_h, None, base=main_h, bm=bm_inner)
bmesh.ops.recalc_face_normals(bm_inner, faces=bm_inner.faces)
mesh_object("Museum Center-Tür Sturz", bm_inner, solid("Wand innen", WKW["50"], roughness=0.6), rotor)   # colour of the inner wall, otherwise
# a light blue field appears above the door
bm_posts = bmesh.new()
post_off = GATE_SIGN * 0.08   # posts in the plane of the wall, projecting 0.1 m, so the door frame
for p_ in (p_a, p_b):         # is not flush with the wall; previously 0.35 m in front of the wall
    rods(bm_posts, [on_ring(p_[0], p_[1] + post_off, 0.0), on_ring(p_[0], p_[1] + post_off, main_h)], 0.2)
rods(bm_posts, [on_ring(p_a[0], p_a[1] + post_off, main_h), on_ring(p_b[0], p_b[1] + post_off, main_h)], 0.2)
mesh_object("Museum Center-Tür Portal", bm_posts, solid("Portal", WKW["800"], roughness=0.5), rotor)
# Two door leaves without a gap, like a real door: they meet in the middle and reach to the reveal and under the lintel. Each
# leaf is its own object on a hinge empty (vertical rotation axis at the reveal), so the door can open during the ride; angle 0
# = shut, DOOR_OPEN_DEG = open (opens into the centre room)
p_m = ((p_a[0] + p_b[0]) / 2, (p_a[1] + p_b[1]) / 2)
DOOR_OPEN_DEG = 95
DOOR_SWING = -GATE_SIGN   # opening direction: into the centre room, away from the arriving camera (with +GATE_SIGN
DOOR_HINGES = []          # leaf a swung into the way); if the direction is wrong, swap the sign and look at panel 06.4
for hinge, (q0, q1), sign in ((p_a, (p_a, p_m), 1), (p_b, (p_m, p_b), -1)):
    bm_leaf = bmesh.new()
    ring_prism(None, [(q0[0], q0[1] - 0.05), (q1[0], q1[1] - 0.05), (q1[0], q1[1] + 0.05), (q0[0], q0[1] + 0.05)],
               main_h + 0.03, None, base=0.02, bm=bm_leaf)
    side = -1 if sign > 0 else 1   # astragal over the joint, one per side (room 1 and centre room)
    ring_prism(None, [(p_m[0] - 0.04, p_m[1] + side * 0.05), (p_m[0] + 0.04, p_m[1] + side * 0.05),
                      (p_m[0] + 0.04, p_m[1] + side * 0.08), (p_m[0] - 0.04, p_m[1] + side * 0.08)],
               main_h, None, base=0.02, bm=bm_leaf)
    bmesh.ops.recalc_face_normals(bm_leaf, faces=bm_leaf.faces)
    pivot = bpy.data.objects.new(f"Museum Center-Tür Angel {'a' if sign > 0 else 'b'}", None)
    pivot.empty_display_size = 0.2
    scene.collection.objects.link(pivot)
    pivot.parent = rotor
    pivot.location = on_ring(hinge[0], hinge[1], 0.0)
    pivot.rotation_mode = "AXIS_ANGLE"
    axis = -Vector((pivot.location.x, pivot.location.y, 0)).normalized()   # up = towards the axis
    pivot.rotation_axis_angle = (0.0, axis.x, axis.y, axis.z)
    leaf = mesh_object(f"Museum Center-Tür Flügel {'a' if sign > 0 else 'b'}", bm_leaf, solid("Türflügel", WKW["600"], roughness=0.35, metallic=0.2), rotor)
    leaf.parent = pivot
    leaf.matrix_parent_inverse = Matrix.Translation(-pivot.location)   # the leaf lies in rotor coordinates, the hinge is only translated
    DOOR_HINGES.append((pivot, sign))


def set_main_door(angle_deg, frame=None):
    """Centre door of the centre room: both leaves to angle_deg (0 shut, DOOR_OPEN_DEG open); with frame as a keyframe."""
    for pivot, sign in DOOR_HINGES:
        axis = pivot.rotation_axis_angle
        pivot.rotation_axis_angle = (math.radians(angle_deg) * sign * DOOR_SWING, axis[1], axis[2], axis[3])
        if frame is not None:
            pivot.keyframe_insert("rotation_axis_angle", frame=frame)


# Door from room 6 into the centre room, so the visit can pass straight from room 6 into the centre room: just before the
# passage a graphic swings back and becomes the door. The last piece of the inner wall before the corner to room 1 (2.6 m wide)
# is missing; in it a leaf at the height of the passages, the graphic on the room side (placeholder r6_door from the storyboard),
# hinge at the edge away from the corner, opening into the centre room; above it a lintel up to the ceiling
R6_DOOR_H = float(DOORS.get("passage_height", 3.0))
r6_outline = room_outline(k_of_room(6), mr, inner_steps=INNER_STEPS)
r6_hinge, r6_corner = r6_outline[-2], r6_outline[-1]   # inner wall from corner 60(k+1) to corner 60k; the last piece (face n-2) ends at 60k
bm_r6 = bmesh.new()
r6_n = (-(r6_corner[1] - r6_hinge[1]), r6_corner[0] - r6_hinge[0])
r6_len = math.hypot(*r6_n)
r6_n = (r6_n[0] / r6_len * 0.15, r6_n[1] / r6_len * 0.15)   # half thickness of the lintel across the wall
# room side of the lintel flush with the door graphic (0.035 m in front of the wall line, below), not 0.15 m: otherwise it
# projected 11.5 cm as a ledge above the door into room 6; centre-room side as before
r6_side = 1 if ((r6_hinge[0] + r6_corner[0]) / 2 - mx) * r6_n[0] + ((r6_hinge[1] + r6_corner[1]) / 2 - my) * r6_n[1] > 0 else -1
R6_LINTEL_ROOM = 0.036 / 0.15   # room side in multiples of the half thickness
r6_a = (r6_n[0] * r6_side * R6_LINTEL_ROOM, r6_n[1] * r6_side * R6_LINTEL_ROOM)   # towards the room side
r6_b = (-r6_n[0] * r6_side, -r6_n[1] * r6_side)   # towards the centre room
ring_prism(None, [(r6_hinge[0] + r6_b[0], r6_hinge[1] + r6_b[1]), (r6_corner[0] + r6_b[0], r6_corner[1] + r6_b[1]),
                  (r6_corner[0] + r6_a[0], r6_corner[1] + r6_a[1]), (r6_hinge[0] + r6_a[0], r6_hinge[1] + r6_a[1])],
           museum_h - 0.02 - R6_DOOR_H, None, base=R6_DOOR_H, bm=bm_r6)
bmesh.ops.recalc_face_normals(bm_r6, faces=bm_r6.faces)
mesh_object("Museum Raum 6 Tür Sturz", bm_r6, solid("Wand innen", WKW["50"], roughness=0.6), rotor)
# Leaf 6 cm thick, flush in the wall with no visible gap: joints 5 mm instead of 2 cm; at the corner the leaf ends at the
# partition to room 1 (0.6 m thick, meets the inner wall at 60°, so it reaches 0.3 / sin 60° = 0.35 m into the opening);
# before, the last piece with the edge of the graphic was inside it and hidden from room 6
R6_GAP, R6_CORNER_CUT = 0.005, 0.3 / math.sin(math.radians(60))
r6_dir = ((r6_corner[0] - r6_hinge[0]) / r6_len, (r6_corner[1] - r6_hinge[1]) / r6_len)
R6_LEAF_LEN = r6_len - 2 * R6_GAP - R6_CORNER_CUT
bm_leaf = bmesh.new()
f0 = (r6_hinge[0] + r6_dir[0] * R6_GAP, r6_hinge[1] + r6_dir[1] * R6_GAP)
f1 = (f0[0] + r6_dir[0] * R6_LEAF_LEN, f0[1] + r6_dir[1] * R6_LEAF_LEN)
w_n = (r6_n[0] * 0.2, r6_n[1] * 0.2)   # 0.03 m
ring_prism(None, [(f0[0] - w_n[0], f0[1] - w_n[1]), (f1[0] - w_n[0], f1[1] - w_n[1]), (f1[0] + w_n[0], f1[1] + w_n[1]),
                  (f0[0] + w_n[0], f0[1] + w_n[1])], R6_DOOR_H - 2 * R6_GAP, None, base=R6_GAP, bm=bm_leaf)
bmesh.ops.recalc_face_normals(bm_leaf, faces=bm_leaf.faces)
r6_pivot = bpy.data.objects.new("Museum Raum 6 Tür Angel", None)
r6_pivot.empty_display_size = 0.2
scene.collection.objects.link(r6_pivot)
r6_pivot.parent = rotor
r6_pivot.location = on_ring(r6_hinge[0], r6_hinge[1], 0.0)
r6_pivot.rotation_mode = "AXIS_ANGLE"
r6_axis = -Vector((r6_pivot.location.x, r6_pivot.location.y, 0)).normalized()
r6_pivot.rotation_axis_angle = (0.0, r6_axis.x, r6_axis.y, r6_axis.z)
r6_leaf = mesh_object("Museum Raum 6 Tür Flügel", bm_leaf, solid("Türflügel", WKW["600"], roughness=0.35, metallic=0.2), rotor)
r6_leaf.parent = r6_pivot
r6_leaf.matrix_parent_inverse = Matrix.Translation(-r6_pivot.location)
# opening direction: the one in which the middle of the leaf moves closer to the middle of the museum (into the centre room, away from room 6)
r6_mid = on_ring((f0[0] + f1[0]) / 2, (f0[1] + f1[1]) / 2, 1.0) - r6_pivot.location
r6_centre = on_ring(mx, my, 1.0)
R6_SWING = min((1, -1), key=lambda s: (r6_pivot.location + Matrix.Rotation(math.radians(80) * s, 3, r6_axis) @ r6_mid - r6_centre).length)
R6_ROOM_SIDE = Vector((r6_n[0], r6_n[1]))   # plan normal of the wall; the one pointing away from the middle of the museum faces the room side
if (Vector(((f0[0] + f1[0]) / 2 - mx, (f0[1] + f1[1]) / 2 - my))).dot(R6_ROOM_SIDE) < 0:
    R6_ROOM_SIDE = -R6_ROOM_SIDE
# Graphic on the room side of the leaf, turns with it: image from placeholder r6_door in the storyboard (image), margin 5 cm;
# without an image a light surface with a note.
# Height up to 1.5 cm below the top of the leaf: the resource line runs out of the top of the graphic and continues on the
# lintel above (r6_door "above"); the gap in between stays small
R6_GRAPHIC = (R6_LEAF_LEN - 0.1, R6_DOOR_H - 0.085)   # width, height of the image area in m
r6_spec = next((p for p in BOARD_EARLY.get("placeholders", []) if p.get("id") == "r6_door"), {})
off = R6_ROOM_SIDE.normalized() * 0.035
g0 = (f0[0] + r6_dir[0] * 0.05 + off.x, f0[1] + r6_dir[1] * 0.05 + off.y)
g1 = (f1[0] - r6_dir[0] * 0.05 + off.x, f1[1] - r6_dir[1] * 0.05 + off.y)
bm_g = bmesh.new()
uv_g = bm_g.loops.layers.uv.new()
corners = [on_ring(g0[0], g0[1], 0.07), on_ring(g1[0], g1[1], 0.07), on_ring(g1[0], g1[1], 0.07 + R6_GRAPHIC[1]), on_ring(g0[0], g0[1], 0.07 + R6_GRAPHIC[1])]
# not mirrored from the room side: facing the wall (against the room-side normal, up towards the axis), right is up x normal
room_side_3d = (on_ring(g0[0] + off.x, g0[1] + off.y, 1.0) - on_ring(g0[0], g0[1], 1.0)).normalized()
right = r6_axis.cross(room_side_3d)
order = [0, 1, 2, 3] if (corners[1] - corners[0]).dot(right) > 0 else [1, 0, 3, 2]
face = bm_g.faces.new([bm_g.verts.new(corners[i]) for i in order])
for loop, uv in zip(face.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
    loop[uv_g].uv = uv
r6_graphic = mesh_object("Platzhalter r6_door", bm_g, None, rotor)
r6_graphic.data.materials.clear()
if r6_spec.get("image") and Path(r6_spec["image"]).exists():
    mat = bpy.data.materials.new("Raum 6 Tür Grafik")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    tex, emit, out = nodes.new("ShaderNodeTexImage"), nodes.new("ShaderNodeEmission"), nodes.new("ShaderNodeOutputMaterial")
    tex.image = bpy.data.images.load(r6_spec["image"], check_existing=True)
    links.new(tex.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs[0], out.inputs["Surface"])
    r6_graphic.data.materials.append(mat)
else:
    r6_graphic.data.materials.append(glow("Raum 6 Tür ohne Grafik", WKW["100"], 1.0))
r6_graphic.parent = r6_pivot
r6_graphic.matrix_parent_inverse = Matrix.Translation(-r6_pivot.location)
print(f"Raum 6 Tür: Bildfläche {R6_GRAPHIC[0]:.2f} x {R6_GRAPHIC[1]:.2f} m, Bild {r6_spec.get('image', 'fehlt')}", flush=True)
# Line on the lintel above the door, so the resource curve can run on through the ceiling: transparent image from r6_door
# "above", same width and position as the graphic, on the room side of the lintel from the top of the door to just below the
# ceiling; fixed, it does not turn with the leaf
if r6_spec.get("above") and Path(r6_spec["above"]).exists():
    off_l = R6_ROOM_SIDE.normalized() * 0.039   # room side of the lintel (0.036 m, above) plus 3 mm
    # do not call them a0/a1: a0 is the start angle that on_ring reads
    lint0 = (f0[0] + r6_dir[0] * 0.05 + off_l.x, f0[1] + r6_dir[1] * 0.05 + off_l.y)
    lint1 = (f1[0] - r6_dir[0] * 0.05 + off_l.x, f1[1] - r6_dir[1] * 0.05 + off_l.y)
    bm_a = bmesh.new()
    uv_a = bm_a.loops.layers.uv.new()
    top_a = museum_h - 0.05
    corners_a = [on_ring(lint0[0], lint0[1], R6_DOOR_H), on_ring(lint1[0], lint1[1], R6_DOOR_H), on_ring(lint1[0], lint1[1], top_a),
                 on_ring(lint0[0], lint0[1], top_a)]
    face_a = bm_a.faces.new([bm_a.verts.new(corners_a[i]) for i in order])
    for loop, uv in zip(face_a.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop[uv_a].uv = uv
    r6_above = mesh_object("Raum 6 Tür Strich über r6_door", bm_a, None, rotor)
    mat_a = bpy.data.materials.new("Raum 6 Tür Strich")
    mat_a.use_nodes = True
    nodes, links = mat_a.node_tree.nodes, mat_a.node_tree.links
    nodes.clear()
    tex, emit, clear, mix, out = (nodes.new(t) for t in ("ShaderNodeTexImage", "ShaderNodeEmission", "ShaderNodeBsdfTransparent",
                                                         "ShaderNodeMixShader", "ShaderNodeOutputMaterial"))
    tex.image = bpy.data.images.load(str(Path(r6_spec["above"]).resolve()), check_existing=True)   # Blender needs the full path
    links.new(tex.outputs["Color"], emit.inputs["Color"])
    links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(clear.outputs[0], mix.inputs[1])
    links.new(emit.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    mat_a.surface_render_method = "DITHERED"
    r6_above.data.materials.clear()   # otherwise mesh_object puts a default material in slot 0
    r6_above.data.materials.append(mat_a)
    print(f"Raum 6 Tür: Strich über der Tür {R6_GRAPHIC[0]:.2f} x {top_a - R6_DOOR_H:.2f} m", flush=True)


def set_room6_door(angle_deg, frame=None):
    """Door from room 6 into the centre room to angle_deg (0 shut, DOOR_OPEN_DEG open); with frame as a keyframe."""
    axis = r6_pivot.rotation_axis_angle
    r6_pivot.rotation_axis_angle = (math.radians(angle_deg) * R6_SWING, axis[1], axis[2], axis[3])
    if frame is not None:
        r6_pivot.keyframe_insert("rotation_axis_angle", frame=frame)


inner_frames()
# Elevator tower at the foot of spoke 0, behind the museum, seen right after leaving the museum: glass tower from the ring
# floor up to the ring roof, where the spoke begins; the cabin inside; a hall with a sign below
tower_u, tower_v, tower_r = 0.0, -SPOKE_Z, 4.0


def glass_drum(name, outline, height, mat, base, gap, door_top, roof=True):
    """Glass cylinder like ring_prism (open bottom), but with an opening towards the museum: the sides whose index is in gap only
    start at door_top (height above the floor). Hall, tower and cabin used to be closed, and the camera passed through three
    glass walls on the way back."""
    bm = bmesh.new()
    bottom = [bm.verts.new(on_ring(u, v, base)) for u, v in outline]
    lintel = [bm.verts.new(on_ring(u, v, door_top)) for u, v in outline]
    top = [bm.verts.new(on_ring(u, v, base + height)) for u, v in outline]
    if roof:
        bm.faces.new(list(reversed(top)))
    n = len(outline)
    for i in range(n):
        j = (i + 1) % n
        if i not in gap:
            bm.faces.new((bottom[i], bottom[j], lintel[j], lintel[i]))
        bm.faces.new((lintel[i], lintel[j], top[j], top[i]))
    return mesh_object(name, bm, mat, rotor)


# openings on the side towards the museum (direction 270°, smaller depth), on the axis of the way back (along 0): hall 2.3 m wide,
# tower 2.1 m, cabin 1.8 m (the cabin door in front is 1.4 m wide); height of the opening up to 2.8 m, in the cabin up to the top of the door
tower_ring = [(tower_u + tower_r * math.cos(2 * math.pi * i / 24), tower_v + tower_r * math.sin(2 * math.pi * i / 24)) for i in range(24)]
TOWER_GAP, LOBBY_GAP, CAB_GAP, LIFT_DOOR_TOP = (17, 18), (23, 24), (16, 17, 18, 19), 2.8
glass_drum("Aufzugsturm", tower_ring, RIM - 0.5, glass("Turmglas", (0.75, 0.82, 0.95), 0.1), 0.0, TOWER_GAP, LIFT_DOOR_TOP)   # clearer than
# the spoke: from the cabin (07.5) one looks through cabin, tower and hall; at 0.25 to 0.3 each a grey veil lay over the museum
lobby_ring = [(tower_u + 6.0 * math.cos(2 * math.pi * i / 32), tower_v + 6.0 * math.sin(2 * math.pi * i / 32)) for i in range(32)]   # the back wall of the
# museum lies at depth 125 (half scale), the spoke at 140: 9 m remain between the back door and the hall
glass_drum("Aufzugshalle", lobby_ring, 5.0, glass("Hallenglas", (0.85, 0.93, 1.0), 0.15), 0.0, LOBBY_GAP, LIFT_DOOR_TOP)
cab_r, cab_h = 1.8, 3.0
cab_ring = [(tower_u + cab_r * math.cos(2 * math.pi * i / 24), tower_v + cab_r * math.sin(2 * math.pi * i / 24)) for i in range(24)]
cab = glass_drum("Aufzugskabine", cab_ring, cab_h, glass("Kabinenglas", (0.75, 0.9, 1.0), 0.12), 0.3, CAB_GAP, 2.72)
bm_floor = bmesh.new()   # ring_prism closed the cabin at the bottom: floor as a separate face
bm_floor.faces.new([bm_floor.verts.new(on_ring(u, v, 0.3)) for u, v in cab_ring])
mesh_object("Aufzugskabine Boden", bm_floor, cab.data.materials[0], rotor)
door_v = tower_v - cab_r - 0.08   # cabin door: two sliding glass leaves with a dark
# frame in front of the side towards the museum. They slide: built closed, the shape key "offen" pushes each leaf sideways by
# its width; value 1 open, 0.5 half, 0 shut (cabin_door)
CABIN_DOOR_OPEN = {"open": 1.0, "half": 0.5, "closed": 0.0}
CABIN_DOOR_SECONDS = 1.5   # duration of one movement of the cabin door during the ride


def cabin_door_leaves(slide):
    """Glass and frame of both leaves, pushed sideways by slide (0 shut, 1 open) of their width; same topology for every value."""
    bm_door, bm_door_frame = bmesh.new(), bmesh.new()
    for sx in (-1, 1):
        outer, meet = tower_u + sx * 0.7, tower_u + 0.06   # joint 6 cm beside the middle: the frame edge stood on the line of sight
        shift = slide * (outer - meet)
        lo, hi = min(outer, meet) + shift, max(outer, meet) + shift
        ring_prism(None, [(lo, door_v - 0.02), (hi, door_v - 0.02), (hi, door_v + 0.02), (lo, door_v + 0.02)], 2.4, None, base=0.32, bm=bm_door)
        for u_edge in (lo, hi):
            rods(bm_door_frame, [on_ring(u_edge, door_v - 0.03, 0.32), on_ring(u_edge, door_v - 0.03, 2.72)], 0.025)
        rods(bm_door_frame, [on_ring(lo, door_v - 0.03, 2.72), on_ring(hi, door_v - 0.03, 2.72)], 0.025)
    return bm_door, bm_door_frame


for part, index, mat in (("Glas", 0, glass("Kabinentürglas", (0.8, 0.92, 1.0), 0.18)),
                         ("Rahmen", 1, solid("Kabinentürrahmen", (0.08, 0.08, 0.09), roughness=0.4))):
    leaf = mesh_object(f"Kabinentür {part}", cabin_door_leaves(0.0)[index], mat, rotor)
    leaf.shape_key_add(name="Basis")
    opened = leaf.shape_key_add(name="offen", from_mix=False)
    bm_open = cabin_door_leaves(1.0)[index]
    bm_open.verts.ensure_lookup_table()
    for i, vert in enumerate(bm_open.verts):
        opened.data[i].co = vert.co
    bm_open.free()
    opened.value = CABIN_DOOR_OPEN["open"]
bm_frame_cab = bmesh.new()
for h in (0.3, 0.3 + cab_h):
    rods(bm_frame_cab, [on_ring(u, v, h) for u, v in cab_ring + cab_ring[:1]], 0.05)
# handrail at 1 m instead of a ring at half height, which lay across the image at eye height (07.5); interrupted above the opening to the door
rail = cab_ring[CAB_GAP[-1] + 1:] + cab_ring[:CAB_GAP[0] + 1]
rods(bm_frame_cab, [on_ring(u, v, 1.3) for u, v in rail], 0.05)
for ring, gap, top in ((lobby_ring, LOBBY_GAP, 5.0), (tower_ring, TOWER_GAP, LIFT_DOOR_TOP)):   # door frame at the openings
    for i in (gap[0], gap[-1] + 1):
        u, v = ring[i]
        rods(bm_frame_cab, [on_ring(u, v, 0.0), on_ring(u, v, top)], 0.06)
    rods(bm_frame_cab, [on_ring(*ring[gap[0]], LIFT_DOOR_TOP), on_ring(*ring[gap[-1] + 1], LIFT_DOOR_TOP)], 0.06)
for u, v in cab_ring[3::6]:   # offset by 45°: no strut on the line of sight to the gate (07.5, backwards into the cabin)
    rods(bm_frame_cab, [on_ring(u, v, 0.3), on_ring(u, v, 0.3 + cab_h)], 0.07)
for i in range(0, 24, 4):   # frame of the tower: six struts and rings every 10 m
    u, v = tower_ring[i]
    rods(bm_frame_cab, [on_ring(u, v, 0.0), on_ring(u, v, RIM - 0.5)], 0.12)
for h in range(10, int(RIM), 10):
    rods(bm_frame_cab, [on_ring(u, v, h) for u, v in tower_ring + tower_ring[:1]], 0.08)
for i in range(2, 32, 4):   # posts of the hall, so that the glass reads as a hall (offset, none on the axis to the gate)
    u, v = lobby_ring[i]
    rods(bm_frame_cab, [on_ring(u, v, 0.0), on_ring(u, v, 5.0)], 0.1)
rods(bm_frame_cab, [on_ring(u, v, 5.0) for u, v in lobby_ring + lobby_ring[:1]], 0.1)
mesh_object("Aufzugsrahmen", bm_frame_cab, m_cabin, rotor)
# No "LIFT TO THE HUB" sign any more: all signs were removed. The panel at the hall used to stand here.
# Thread to the hub: from the glass globe a line rises vertically to the glass roof of the ring, runs below the roof to the
# tower, then up the spoke next to the cabin (opposite side) to the bearing ring, so it travels up alongside the rider
hub_thread = [on_ring(mx, my, globe_h + globe_r)] + [   # along below the curved roof (roof_height), not at a fixed height above it
    on_ring(mx + (tower_u - 2.5 - mx) * t, my + (tower_v - my) * t, roof_height(my + (tower_v - my) * t) - 0.6) for t in (k / 8 for k in range(9))]
foot = hub_thread[-1]
hub_thread += [Vector((foot.x, foot.y, 0)).normalized() * r + Vector((0, 0, foot.z)) for r in (R - RIM - 1.0, COLLAR_OUT + 1.0)]
bm_hub_thread = bmesh.new()
rods(bm_hub_thread, hub_thread, 0.12)
mesh_object("Faden zum Hub", bm_hub_thread, glow("Faden zum Hub", WKW["400"], 8.0), rotor).visible_shadow = False   # lay in the
# area light of the centre room and shaded it
bm, bm_bar_win = bmesh.new(), bmesh.new()   # bar in the ring at spoke 1, at the back wall, glass front towards the sun side
bar_radial = Vector((math.cos(spoke_angles[1]), math.sin(spoke_angles[1]), 0))
box_at(bm, bar_radial * (R - 9.3) + Vector((0, 0, -(DEPTH - 22))), spoke_angles[1], (40, 16, 40))   # 0.8 m further in: the corners of the
# straight box stuck out through the curved hull 20 m from the middle
box_at(bm_bar_win, bar_radial * (R - 7) + Vector((0, 0, -(DEPTH - 42.2))), spoke_angles[1], (36, 8, 0.6))
mesh_object("Bar", bm, m_bar, rotor)
mesh_object("Fensterfront der Bar", bm_bar_win, m_window, rotor)
bm, bm_res_win = bmesh.new(), bmesh.new()
for a in spoke_angles[2:]:   # homes at the foot of the spoke as a terraced house around the spoke: four steps of 6 m, narrower at the top
    radial = Vector((math.cos(a), math.sin(a), 0))
    for level in range(4):
        h0 = level * 6.0
        size_t, size_a = 70 - 14 * level, 60 - 10 * level
        for side_sign in (-1, 1):   # two wings on both sides of the spoke, the spoke itself stays free
            # each wing stands at its own place in the ring (angle turned by its distance from the spoke, inset 0.3 m): as a
            # straight box aligned with the spoke its outer corners stuck 1.6 m out through the hull
            a_w = a + side_sign * (size_t / 4 + 6) / R
            radial_w = Vector((math.cos(a_w), math.sin(a_w), 0))
            back = Vector((0, 0, -(DEPTH - 2 - size_a / 2)))   # at the back wall on the shadow side, not through it
            box_at(bm, radial_w * (R - 0.5 - h0 - 3.3) + back, a_w, (size_t / 2 - 12, 6, size_a))
            box_at(bm_res_win, radial_w * (R - 0.5 - h0 - 3.9) + back, a_w, (size_t / 2 - 11.7, 1.0, size_a + 0.3))
mesh_object("Wohnen an den Speichen", bm, m_house, rotor)
mesh_object("Fenster der Wohnungen", bm_res_win, m_window, rotor)

# City in the ring: straight streets towards the sun every 60 m, two ring streets in the direction of rotation, houses in the
# blocks between with a warmly lit window band, trees along the ring streets; the feet of the spokes and the square in front of the museum stay free
m_street = solid("Straße", (0.28, 0.28, 0.3), roughness=0.9)
m_tree = solid("Baum", (0.16, 0.42, 0.18), roughness=0.9)
CIRCUM = 2 * math.pi * R
STREET_STEP, ROADS = 60.0, (45.0, 105.0)   # spacing of the cross streets; position of the ring streets in m towards the shadow side
spoke_alongs = [((s - a0) % (2 * math.pi)) * R for s in spoke_angles]


FARM = (spoke_alongs[3] + 60, spoke_alongs[4] - 60)   # proposal: fields between spokes 3 and 4 (Stanford torus: agriculture in the ring)


def in_farm(along):
    return FARM[0] < along % CIRCUM < FARM[1]


def free_of(along, margin_spoke=35.0, margin_museum=150.0):
    u = along % CIRCUM
    near_spoke = min(min(abs(u - s), CIRCUM - abs(u - s)) for s in spoke_alongs) < margin_spoke
    return not near_spoke and min(u, CIRCUM - u) > margin_museum and not in_farm(u)


bm_street = bmesh.new()


def street(outline, height=0.15):
    bottom = [bm_street.verts.new(on_ring(u, v, 0.02)) for u, v in outline]
    top = [bm_street.verts.new(on_ring(u, v, height)) for u, v in outline]
    bm_street.faces.new(list(reversed(top)))
    for i in range(len(outline)):
        bm_street.faces.new((bottom[i], bottom[(i + 1) % len(outline)], top[(i + 1) % len(outline)], top[i]))


cross = [STREET_STEP / 2 + STREET_STEP * k for k in range(int(CIRCUM // STREET_STEP))]
for u in cross:
    if free_of(u, margin_spoke=0, margin_museum=70):
        street([(u - 3, 3), (u + 3, 3), (u + 3, DEPTH - 3), (u - 3, DEPTH - 3)])
for depth in ROADS:   # ring streets in pieces of 10 m, so that they follow the floor
    for k in range(int(CIRCUM // 10)):
        u = k * 10.0
        if free_of(u + 5, margin_spoke=0, margin_museum=70):
            street([(u, depth - 4), (u + 10, depth - 4), (u + 10, depth + 4), (u, depth + 4)])
mesh_object("Straßen", bm_street, m_street, rotor)

random.seed(5)
bm_house, bm_lit, bm_tree = bmesh.new(), bmesh.new(), bmesh.new()
blocks_depth = [(6, ROADS[0] - 6), (ROADS[0] + 6, ROADS[1] - 6), (ROADS[1] + 6, DEPTH - 6)]
for u0 in cross:
    for d0, d1 in blocks_depth:
        u = u0 + 6
        while u < u0 + STREET_STEP - 10:
            width = random.choice((10, 12, 16, 20))
            if u + width > u0 + STREET_STEP - 4:
                break
            if free_of(u + width / 2):
                d = d0
                while d < d1 - 8:
                    length = min(random.choice((10, 14, 20)), d1 - d)
                    h = random.choice((6, 9, 9, 12, 15, 18))
                    a = a0 + (u + width / 2) / R
                    radial = Vector((math.cos(a), math.sin(a), 0))
                    base = radial * (R - 0.5) + Vector((0, 0, -(d + length / 2)))
                    box_at(bm_house, base - radial * h / 2, a, (width - 1.5, h, length - 1.5))
                    for level in range(1, int(h // 3.33)):   # one window band per storey (step 3.33 m)
                        box_at(bm_lit, base - radial * (level * 3.33 - 1.2), a, (width - 1.3, 1.0, length - 1.3))
                    d += length + random.choice((2, 4))
            u += width + random.choice((2, 3, 5))
    for depth in ROADS:   # trees on both sides of the ring streets
        for k in range(4):
            u = u0 + 8 + k * 13
            if not free_of(u):
                continue
            for off in (-6, 6):
                a = a0 + u / R
                up = -Vector((math.cos(a), math.sin(a), 0))
                foot = on_ring(u, depth + off, 0)
                rot = up.to_track_quat("Z", "Y").to_matrix().to_4x4()
                bmesh.ops.create_cone(bm_tree, cap_ends=True, segments=8, radius1=2.6, radius2=0.0, depth=7.0,
                                      matrix=Matrix.Translation(foot + up * 5.5) @ rot)
                bmesh.ops.create_cone(bm_tree, cap_ends=True, segments=6, radius1=0.35, radius2=0.35, depth=2.5,
                                      matrix=Matrix.Translation(foot + up * 1.25) @ rot)
mesh_object("Häuser", bm_house, m_house, rotor)
# fields: strips of 20 m in the direction of rotation, across the depth of the ring, three alternating colours (farming at grey-box scale)
fields = [bmesh.new() for _ in range(3)]
u, k = FARM[0], 0
while u < FARM[1] - 20:
    for d0, d1 in ((4, DEPTH / 2 - 3), (DEPTH / 2 + 3, DEPTH - 4)):
        bm_f = fields[(k + (d0 > 10)) % 3]
        outline = [(u + 1, d0), (u + 19, d0), (u + 19, d1), (u + 1, d1)]
        bottom = [bm_f.verts.new(on_ring(a, b, 0.05)) for a, b in outline]
        top = [bm_f.verts.new(on_ring(a, b, 0.4)) for a, b in outline]
        bm_f.faces.new(list(reversed(top)))
        for i in range(4):
            bm_f.faces.new((bottom[i], bottom[(i + 1) % 4], top[(i + 1) % 4], top[i]))
    u, k = u + 20, k + 1
for i, (bm_f, color) in enumerate(zip(fields, ((0.55, 0.5, 0.2), (0.25, 0.5, 0.2), (0.4, 0.62, 0.25)))):
    mesh_object(f"Felder {i + 1} (Vorschlag)", bm_f, solid(f"Feld {i + 1}", color, roughness=0.95), rotor)
mesh_object("Fenster der Häuser", bm_lit, m_window, rotor)
mesh_object("Bäume", bm_tree, m_tree, rotor)

# Entrance of the museum, so that it looks like a real building rather than a placeholder with lettering. Variants via
# building.yaml, station.museum.doors.entrance_style (compare with --doors entrance_style=...):
#   sign: earlier sign, large illuminated lettering above the gate; none: no lettering; canopy: flat canopy on two columns,
#   small lettering on the front edge; letters: single metal letters on the wall above the gate
ENTRANCE = str(DOORS.get("entrance_style", "sign"))
a_sign = a0 + mx / R
gate_wall_v = my + GATE_SIGN * mr * math.cos(math.radians(5))


def entrance_text(name, size, v, h, material, extrude):
    """Lettering facing the square, centred on the gate axis at depth v and height h; up is the direction to the axis."""
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = "WissKomm Wiki Museum"
    curve.align_x, curve.align_y, curve.size, curve.extrude = "CENTER", "CENTER", size, extrude
    obj = bpy.data.objects.new(name, curve)
    scene.collection.objects.link(obj)
    obj.data.materials.append(material)
    obj.location = on_ring(mx, v, h)
    obj.rotation_euler = (0, math.pi if GATE_SIGN > 0 else 0, a_sign + math.pi / 2)   # text y points to the axis, text z away from the gate;
    # gate on the shadow side: half turn about its own vertical axis, not about the ring axis (that turned the lettering upside down)
    obj.parent = rotor
    return obj


if ENTRANCE == "sign":
    sign_size = min(3.2 * S * 1.3, museum_h - gate_h - 0.6)   # fits between the gate lintel and the roof edge (panel 07.4 cut off the top of the lettering)
    entrance_text("Museumsschild", sign_size, my + GATE_SIGN * (mr + 1.0), gate_h + 0.3 + sign_size * 0.5, m_window, 0.15)
elif ENTRANCE == "canopy":   # dimensions as at real entrances: depth 3 m, lower edge 0.5 m above the gate lintel, front edge 0.45 m, columns 0.4 m
    depth, under, fascia, overhang = 3.0, gate_h + 0.5, 0.45, 1.2
    v_front = gate_wall_v + GATE_SIGN * depth
    half = door_half + overhang
    bm_canopy = bmesh.new()
    ring_prism(None, [(mx - half, gate_wall_v), (mx + half, gate_wall_v), (mx + half, v_front), (mx - half, v_front)],
               fascia, None, base=under, bm=bm_canopy)
    bmesh.ops.recalc_face_normals(bm_canopy, faces=bm_canopy.faces)
    mesh_object("Museum Vordach", bm_canopy, solid("Vordach", WKW["800"], roughness=0.45), rotor)
    bm_cols = bmesh.new()
    for sx in (-1, 1):
        rods(bm_cols, [on_ring(mx + sx * (half - 0.4), v_front - GATE_SIGN * 0.4, 0.0),
                       on_ring(mx + sx * (half - 0.4), v_front - GATE_SIGN * 0.4, under)], 0.2)
    mesh_object("Museum Vordach Säulen", bm_cols, solid("Säulen", WKW["50"], roughness=0.5), rotor)
    entrance_text("Museumsschild Vordach", fascia * 0.55, v_front + GATE_SIGN * 0.03, under + fascia / 2,
                  solid("Schrift Vordach", WKW["100"], roughness=0.3, metallic=0.6), 0.02)
elif ENTRANCE == "logo":   # the logo as it is, about 30 % larger, in relief; image from
    # a separate logo script (word mark from the original logo, "Museum" below it). Relief through layers: the logo in front,
    # behind it eight layers of the same shape in dark turquoise up to the wall, so the letters have depth and edges
    logo_png = BASE / "_scratch" / "storyboard" / "entrance_logo.png"
    logo_w, logo_h = json.loads((BASE / "_scratch" / "storyboard" / "entrance_logo.json").read_text(encoding="utf-8"))["size_m"]
    h_mid = gate_h + 0.35 + logo_h / 2
    centre = on_ring(mx, gate_wall_v + GATE_SIGN * 0.02, h_mid)
    up_l = (on_ring(mx, gate_wall_v + GATE_SIGN * 0.02, h_mid + 1.0) - centre).normalized()   # axis_up is only defined further down
    out_l = (on_ring(mx, gate_wall_v + GATE_SIGN * 1.0, h_mid) - centre).normalized()
    X_l = up_l.cross(out_l).normalized()

    def logo_layer(name, path, offset):
        img = bpy.data.images.load(str(path), check_existing=True)
        bpy.ops.mesh.primitive_plane_add(size=2)
        plane = bpy.context.active_object
        plane.name = name
        plane.matrix_world = (Matrix.Translation(centre + out_l * offset) @ Matrix((X_l, up_l, out_l)).transposed().to_4x4()
                              @ Matrix.Diagonal((logo_w / 2, logo_h / 2, 1, 1)))
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        tex, emit, out = nodes.new("ShaderNodeTexImage"), nodes.new("ShaderNodeEmission"), nodes.new("ShaderNodeOutputMaterial")
        transparent, mix = nodes.new("ShaderNodeBsdfTransparent"), nodes.new("ShaderNodeMixShader")
        tex.image = img
        links.new(tex.outputs["Color"], emit.inputs["Color"])
        links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(emit.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs["Surface"])
        mat.surface_render_method = "DITHERED"
        plane.data.materials.append(mat)
        plane.parent = rotor

    stand_off = logo_w ** 2 / (8 * mr) + 0.04   # the wall is curved: at the ends of the flat lettering it comes forward by the
    # sagitta (width² / 8 r, about 0.14 m) and hid the wiki box ("Wik"); the lettering stands on spacers in front of it
    for k in range(8):   # depth 0.13 m: layers every 1.6 cm up to just behind the front
        logo_layer(f"Museumsschild Logo Tiefe {k}", BASE / "_scratch" / "storyboard" / "entrance_logo_side.png", stand_off + 0.016 * k)
    logo_layer("Museumsschild Logo", logo_png, stand_off + 0.13)
elif ENTRANCE == "letters":   # metal letters 0.6 m high, 0.6 m above the lintel, 0.12 m in front of the wall (spacers)
    entrance_text("Museumsschild Buchstaben", 0.6, gate_wall_v + GATE_SIGN * 0.12, gate_h + 0.6 + 0.3,
                  solid("Buchstaben Metall", WKW["100"], roughness=0.3, metallic=0.5, emission=0.6), 0.06)   # slightly emissive:
    # purely metallic, they reflected the dark surroundings and disappeared against the wall
# Six walls between the rooms of the museum (rooms 1 to 6 anticlockwise around the centre room), from the corners of the centre
# room to the outer wall, each with a passage 3 m wide and 4 m high in the middle (route anticlockwise through the narrow passages)
bm_walls = bmesh.new()
door_w, door_h = float(DOORS.get("passage_width", 3.0)), float(DOORS.get("passage_height", 4.0))   # building.yaml
for k in range(6):
    ang = math.radians(60 * k)
    nx, ny = -math.sin(ang) * 0.3, math.cos(ang) * 0.3
    r_mid = (hall_r + mr) / 2
    # entirely inside the hull: before, they reached to mr and 0.5 m above the roof, so the corners of the 0.6 m thick wall showed
    # as strips through the outer wall and above roof and inner wall; now 2 cm below the ceiling and closed at both ends without
    # gaps to the walls: on the outside long enough that the corners of the wall just stay inside the chord of the outer wall
    # (arc in pieces of 5°); at the centre room pointed like the corner of the hexagon, the ends lie 1 cm behind the inner walls
    # (the inner walls meet there at 120°: a flat end left a wedge of 17 cm open beside the wall)
    half_t = 0.3
    r_chord = mr * math.cos(math.radians(2.5)) / math.cos(math.radians(2.5) - math.atan2(half_t, mr))
    r_out, top = math.sqrt(r_chord ** 2 - half_t ** 2) - 0.003, museum_h - 0.02
    tip_r = hall_r - 0.01
    side_r = tip_r - half_t / math.tan(math.radians(60))   # inner wall: 30° from the perpendicular to the radius
    for r0, r1, base, height in ((side_r, r_mid - door_w / 2, 0, top), (r_mid + door_w / 2, r_out, 0, top),
                                 (r_mid - door_w / 2, r_mid + door_w / 2, door_h, top - door_h)):
        c0 = (mx + r0 * math.cos(ang), my + r0 * math.sin(ang))
        c1 = (mx + r1 * math.cos(ang), my + r1 * math.sin(ang))
        outline = [(c0[0] - nx, c0[1] - ny), (c1[0] - nx, c1[1] - ny), (c1[0] + nx, c1[1] + ny), (c0[0] + nx, c0[1] + ny)]
        if r0 == side_r:   # tip into the corner of the centre room
            outline.append((mx + tip_r * math.cos(ang), my + tip_r * math.sin(ang)))
        ring_prism(None, outline, height, None, base=base, bm=bm_walls)
mesh_object("Museum Wände mit Durchgang", bm_walls, solid("Trennwand", WKW["100"], roughness=0.6), rotor)


def textured(bsdf, nodes, links, folder, tile, tint=(1.0, 1.0, 1.0), relief=0.6, color=None, detail=0.3):
    """Poly Haven texture (diff, rough, nor_gl) on a Principled BSDF, box projection in object coordinates with tile size tile m
    (the museum solids have no UV maps); tint recolours the colour map. With color (a colour from the corporate design) the
    texture only adds structure: relief, roughness and, with share detail, its light and dark; the colour itself stays that of
    the corporate design."""
    files = {kind: next(iter(sorted((BASE / "media" / "polyhaven" / folder).glob(f"{folder}_{kind}_*.jpg"))), None)
             for kind in ("diff", "rough", "nor_gl")}
    if not files["diff"]:
        print(f"Interieur: Textur {folder} fehlt (fetch_polyhaven.py)", flush=True)
        return
    coords, mapping = nodes.new("ShaderNodeTexCoord"), nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1 / tile, 1 / tile, 1 / tile)
    links.new(coords.outputs["Object"], mapping.inputs["Vector"])

    def image(path, color):
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(path), check_existing=True)
        tex.projection, tex.projection_blend = "BOX", 0.2
        if not color:
            tex.image.colorspace_settings.name = "Non-Color"
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        return tex

    mix = nodes.new("ShaderNodeMix")   # inputs and outputs have the same name for each data type: select by identifier
    mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
    socket = {s.identifier: s for s in mix.inputs}
    if color is None:
        socket["Factor_Float"].default_value = 1.0
        links.new(image(files["diff"], True).outputs["Color"], socket["A_Color"])
        socket["B_Color"].default_value = (*tint, 1)
    else:   # colour fixed; the grey levels of the texture (averaged around 1) darken or lighten it with share detail
        bw, gain = nodes.new("ShaderNodeRGBToBW"), nodes.new("ShaderNodeMath")
        gain.operation, gain.inputs[1].default_value = "MULTIPLY", 2.0
        links.new(image(files["diff"], True).outputs["Color"], bw.inputs["Color"])
        links.new(bw.outputs["Val"], gain.inputs[0])
        socket["Factor_Float"].default_value = detail
        socket["A_Color"].default_value = (*color, 1)
        links.new(gain.outputs["Value"], socket["B_Color"])
    links.new(next(s for s in mix.outputs if s.identifier == "Result_Color"), bsdf.inputs["Base Color"])
    if files["rough"]:
        links.new(image(files["rough"], False).outputs["Color"], bsdf.inputs["Roughness"])
    if files["nor_gl"]:
        nor = nodes.new("ShaderNodeNormalMap")
        nor.inputs["Strength"].default_value = relief
        links.new(image(files["nor_gl"], False).outputs["Color"], nor.inputs["Color"])
        links.new(nor.outputs["Normal"], bsdf.inputs["Normal"])


def apply_interior():
    """Interior by style (building.yaml station.museum.interior): the inside of the room solids, the room side of the inner wall,
    partitions, inner lintels and the floor get textures, the ceiling lights of the rooms colour and strength. The style comes
    from the field interior of the storyboard (comparison per run), otherwise from building.yaml; plain leaves everything as it is."""
    spec_all = MUSEUM.get("interior", {})
    style = BOARD_EARLY.get("interior") or spec_all.get("style", "plain")
    spec = spec_all.get("styles", {}).get(style, {})
    print(f"Interieur: {style}", flush=True)
    if not spec:
        return
    walls = []
    for name in ("Museum Innenwand Raumseite", "Trennwand", "Torsturz innen", "Wand innen"):
        mat = bpy.data.materials.get(name)
        if mat:
            walls.append(next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"))
    museum_mat = bpy.data.materials.get("Museum zweiseitig")   # the second Principled is the inside (two_sided)
    if museum_mat:
        walls.append([n for n in museum_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"][1])
    wall_color = palette_color(spec["wall_color"]) if spec.get("wall_color") else None
    for bsdf in walls:
        tree = bsdf.id_data
        textured(bsdf, tree.nodes, tree.links, spec["wall"], float(spec.get("wall_tile", 2.0)), spec.get("wall_tint", (1, 1, 1)),
                 float(spec.get("wall_relief", 0.6)), wall_color, float(spec.get("wall_detail", 0.3)))
    floor = bpy.data.materials.get("Museumsboden")
    if floor and spec.get("floor"):
        bsdf = floor.node_tree.nodes["Principled BSDF"]
        textured(bsdf, floor.node_tree.nodes, floor.node_tree.links, spec["floor"], float(spec.get("floor_tile", 2.5)),
                 spec.get("floor_tint", (1, 1, 1)), float(spec.get("floor_relief", 0.6)),
                 palette_color(spec["floor_color"]) if spec.get("floor_color") else None, float(spec.get("floor_detail", 0.4)))
    for k in range(6):
        lamp = bpy.data.lights.get(f"Museum Licht {k}")
        if lamp:
            lamp.color = tuple(spec.get("light_color", lamp.color))
            lamp.energy *= float(spec.get("light_factor", 1.0))


apply_interior()


def apply_facade():
    """Facade: plaster texture in the colour of the corporate design on the outside and the gate lintel, plus a whiter surface at
    the entrance (beside the gate up to entrance_half_deg and above the gate), 2 to 5 cm in front of the wall, behind the
    lettering; values in building.yaml station.museum.facade."""
    if FACADE_SPEC.get("texture"):
        tile, relief, detail = (float(FACADE_SPEC.get(k, d)) for k, d in (("tile", 3.0), ("relief", 0.3), ("detail", 0.3)))
        targets = [[n for n in bpy.data.materials["Museum zweiseitig"].node_tree.nodes if n.type == "BSDF_PRINCIPLED"][0]]
        if "Torsturz außen" in bpy.data.materials:
            targets.append(bpy.data.materials["Torsturz außen"].node_tree.nodes["Principled BSDF"])
        for bsdf in targets:
            textured(bsdf, bsdf.id_data.nodes, bsdf.id_data.links, FACADE_SPEC["texture"], tile, relief=relief, color=FACADE, detail=detail)
    if not FACADE_SPEC.get("entrance_color"):
        return
    half = math.radians(float(FACADE_SPEC.get("entrance_half_deg", 9)))
    gate_a, door_a = math.radians(GATE_DEG), math.radians(5)
    top = museum_h - 0.05
    bm_entry = bmesh.new()
    for a_from, a_to, base in ((gate_a - half, gate_a - door_a, 0.0), (gate_a + door_a, gate_a + half, 0.0), (gate_a - door_a, gate_a + door_a, gate_h)):
        steps = max(2, int(math.degrees(a_to - a_from)))
        for i in range(steps):
            a_i, a_j = a_from + (a_to - a_from) * i / steps, a_from + (a_to - a_from) * (i + 1) / steps
            ring_prism(None, [(mx + (mr + 0.05) * math.cos(a_i), my + (mr + 0.05) * math.sin(a_i)),
                              (mx + (mr + 0.05) * math.cos(a_j), my + (mr + 0.05) * math.sin(a_j)),
                              (mx + (mr + 0.02) * math.cos(a_j), my + (mr + 0.02) * math.sin(a_j)),
                              (mx + (mr + 0.02) * math.cos(a_i), my + (mr + 0.02) * math.sin(a_i))], top - base, None, base=base, bm=bm_entry)
    bmesh.ops.recalc_face_normals(bm_entry, faces=bm_entry.faces)
    mat = solid("Fassade Eingang", palette_color(FACADE_SPEC["entrance_color"]), roughness=0.7)
    if FACADE_SPEC.get("texture"):
        textured(mat.node_tree.nodes["Principled BSDF"], mat.node_tree.nodes, mat.node_tree.links, FACADE_SPEC["texture"],
                 float(FACADE_SPEC.get("tile", 3.0)), relief=float(FACADE_SPEC.get("relief", 0.3)),
                 color=palette_color(FACADE_SPEC["entrance_color"]), detail=float(FACADE_SPEC.get("detail", 0.3)))
    mesh_object("Museum Eingang Fläche", bm_entry, mat, rotor)


apply_facade()

# ---------------------------------------------------------------- hub (stationary): honeycomb collector, mirrors, modules, axis tube
# honeycomb cells with an edge at the bottom, grid as in hub_layout_cells.yaml: x = 8.66 m * q, y = 10 m * (r + q/2)
size = CELL / math.sqrt(3)
apothem = COLLECTOR * math.sqrt(3) / 2   # the collector itself is a hexagon with an edge at the bottom: edge normals at 30° + 60° k
MIRROR_RINGS = 3                          # outer honeycomb rings as standing mirrors (pattern of the Stanford torus)
CENTRE_MIRRORS = {(2 * dq, 2 * dr) for dq, dr in ((1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1))}   # six centre mirrors


def cell_xy(q, r):   # cells with a corner at the bottom (as floor_sketches.axial_to_xy)
    return CELL * (q + r / 2), CELL * math.sqrt(3) / 2 * r


def edge_distance(x, y):
    """Largest projection onto the edge normals of the collector: apothem means exactly on the rim."""
    return max(x * math.cos(math.radians(30 + 60 * k)) + y * math.sin(math.radians(30 + 60 * k)) for k in range(6))


bm_cells, bm_frame, bm_mirror = bmesh.new(), bmesh.new(), bmesh.new()
for q in range(-30, 31):
    for r in range(-35, 36):
        cx, cy = cell_xy(q, r)
        corners = hexagon(cx, cy, size, rot=30)
        if max(edge_distance(x, y) for x, y in corners) > apothem:
            continue
        mirror = edge_distance(cx, cy) > apothem - MIRROR_RINGS * CELL or (q, r) in CENTRE_MIRRORS
        prism(bm_mirror if mirror else bm_cells, hexagon(cx, cy, size - 0.35, rot=30), 0.0 if not mirror else 0.4, -0.3)
        for k in range(3):   # honeycomb frame: three edges per cell, the others belong to the neighbours; no continuous plate
            (x0, y0), (x1, y1) = corners[k], corners[k + 1]
            nx, ny = -(y1 - y0), x1 - x0
            length = math.hypot(nx, ny)
            nx, ny = nx / length * 0.2, ny / length * 0.2
            prism(bm_frame, [(x0 - nx, y0 - ny), (x1 - nx, y1 - ny), (x1 + nx, y1 + ny), (x0 + nx, y0 + ny)], -0.3, -1.2)
mesh_object("Kollektor", bm_cells, m_collector)
mesh_object("Wabenrahmen", bm_frame, m_frame)
# mirrors in the six gaps between collector and ring: they stand still and throw the light into the ring
hex_corners = hexagon(0, 0, COLLECTOR, rot=0)
gap_r = R - RIM - 3
for k in range(6):
    (x0, y0), (x1, y1) = hex_corners[k], hex_corners[(k + 1) % 6]
    g0, g1 = math.atan2(y0, x0), math.atan2(y1, x1)   # not a0: that is the angle of spoke 0 (on_ring)
    if g1 < g0:
        g1 += 2 * math.pi
    arc = [(gap_r * math.cos(g0 + (g1 - g0) * i / 12), gap_r * math.sin(g0 + (g1 - g0) * i / 12)) for i in range(13)]
    outline = [(x0, y0)] + arc + [(x1, y1)]
    verts = [bm_mirror.verts.new((x, y, 0.6 + 6 * (math.hypot(x, y) - apothem) / (gap_r - apothem))) for x, y in outline]   # tilted outwards
    bm_mirror.faces.new(verts)
mesh_object("Spiegel", bm_mirror, m_mirror)

# modules from the honeycomb plan (hub_layout_cells.yaml), depth per module from station.modules; windows on the shadow side, towards the stars
depths = {m["id"]: float(m.get("depth", 10)) for m in STATION.get("modules", [])}
layout = CONFIG.get("hub_cells", {})
STEP = 10 / 3   # depth step 3.33 m
bm_mod, bm_win, bm_hangar, bm_corr, bm_map = bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new()
bm_per_module = {}
occupied = {}
# Lobby, one large open space without hatches: the transfer point (rosette at the axis) and the Space Bar form one open room,
# one Space Bar depth high; the cabin comes up through the hole in the floor
LOBBY_CELLS = [tuple(c) for c in layout.get("modules", {}).get("transfer", [])] + [tuple(c) for c in layout.get("modules", {}).get("spacebar", [])]
for module_id, cells in layout.get("modules", {}).items():
    if module_id == "transfer":
        continue   # the transfer point is the axis tube, the lobby above it
    depth = depths.get(module_id, 10.0)
    # one object per module ("Modul <kennung>"), so that the station planner can compare the inventory per module
    target = {"hangar": bm_hangar, "map_room": bm_map}.get(module_id) or bm_per_module.setdefault(module_id, bmesh.new())
    for q, r in cells:
        cx, cy = cell_xy(q, r)
        occupied[(q, r)] = depth
        if (q, r) in LOBBY_CELLS:
            continue   # the Space Bar belongs to the lobby (built below)
        if module_id == "map_room":
            continue   # map room as one room (build_map_room), not as a glass prism per cell
        if module_id == "hangar":   # hangar on the sun side, above the collector, open towards the sun: ships
            # can only approach from the sun side without passing the spokes or the ring; earlier it hung below like the
            # modules
            prism(target, hexagon(cx, cy, size - 0.1, rot=30), 1.2 + depth, 1.2)
            continue
        prism(target, hexagon(cx, cy, size - 0.1, rot=30), -1.2, -1.2 - depth)
        if module_id not in ("hangar", "map_room"):   # glass modules without windows, otherwise the lights hide the inside
            prism(bm_win, hexagon(cx, cy, size * 0.55, rot=30), -1.2 - depth - 0.05, -1.2 - depth - 0.3)
corridors = [tuple(c) for c in layout.get("corridors", [])]
for q, r in corridors:   # corridor modules: one step deep, made of glass (as in Subnautica)
    if (q, r) in LOBBY_CELLS:
        continue
    cx, cy = cell_xy(q, r)
    occupied[(q, r)] = STEP
    prism(bm_corr, hexagon(cx, cy, size - 0.1, rot=30), -1.2, -1.2 - STEP)
# floor on the sun side as a rule (earlier it lay on the shadow side):
# up is towards the shadow side (-z), so heights above the floor are LOBBY_FLOOR - h; the axis tube ends at the ceiling, the cabin sinks in
LOBBY_CEIL = -1.2 - depths.get("spacebar", 10.0)
LOBBY_FLOOR = -1.3
LOBBY_HOLE = 2.8   # shaft for the cabin (2.2 m) in the ceiling; the axis tube (10 m) ends above the ceiling
bm_floor_l, bm_ceil_l, bm_wall_l = bmesh.new(), bmesh.new(), bmesh.new()
centres_l = [Vector((*cell_xy(q, r), 0)) for q, r in LOBBY_CELLS]
# opening to the map room: at edges to cells of the map room no wall and no handrail, the room continues openly there
centres_map = [Vector((*cell_xy(q, r), 0)) for q, r in layout.get("modules", {}).get("map_room", [])]
centres_open = centres_l + centres_map
for c in centres_l:
    corners = [Vector((x, y, 0)) for x, y in hexagon(c.x, c.y, size, rot=30)]
    bm_floor_l.faces.new([bm_floor_l.verts.new((p.x, p.y, LOBBY_FLOOR)) for p in corners])
    n = 8   # ceiling in small triangles, without those in the hole around the axis tube
    for k in range(6):
        a, b = corners[k], corners[(k + 1) % 6]
        for i in range(n):
            for j in range(n - i):
                tris = [((i, j), (i + 1, j), (i, j + 1))]
                if j < n - i - 1:
                    tris.append(((i + 1, j), (i + 1, j + 1), (i, j + 1)))
                for tri in tris:
                    pts = [c + (a - c) * (u / n) + (b - c) * (v / n) for u, v in tri]
                    if (sum(pts, Vector()) / 3).xy.length < LOBBY_HOLE:
                        continue
                    bm_ceil_l.faces.new([bm_ceil_l.verts.new((p.x, p.y, LOBBY_CEIL)) for p in pts])
    for k in range(6):   # outer wall only at edges without a neighbour in the lobby
        a, b = corners[k], corners[(k + 1) % 6]
        across = c + ((a + b) / 2 - c) * 2
        if any((across - other).length < 0.5 for other in centres_open):
            continue
        bm_wall_l.faces.new([bm_wall_l.verts.new((p.x, p.y, z)) for p, z in ((a, LOBBY_CEIL), (b, LOBBY_CEIL), (b, LOBBY_FLOOR), (a, LOBBY_FLOOR))])
mesh_object("Lobby Boden", bm_floor_l, pbr("Lobbyboden Granit", "granite_tile", size_m=2.0))["wkw_id"] = "spacebar"   # comparison in the planner
mesh_object("Lobby Decke", bm_ceil_l, solid("Lobbydecke", (0.45, 0.46, 0.48), roughness=0.7))   # grey instead of white: with
mesh_object("Lobby Wände", bm_wall_l, pbr("Lobbywand Putz", "painted_plaster_wall", size_m=3.0, tint=(0.85, 0.87, 0.9)))   # Poly Haven textures and 3000 W per lamp the lobby was white
bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=LOBBY_HOLE, depth=1.1, end_fill_type="NOTHING", location=(0, 0, LOBBY_CEIL + 0.55))
bpy.context.active_object.name = "Lobby Geländer"   # collar at the shaft in the ceiling
bpy.context.active_object.data.materials.append(glass("Geländer", (0.8, 0.9, 1.0), 0.2))
for c in centres_l:
    lamp = bpy.data.lights.new("Lobby Licht", "POINT")
    lamp.energy, lamp.color = float(CONFIG.get("lobby_light_watts", 500)), (1.0, 0.92, 0.8)
    lamp_obj = bpy.data.objects.new("Lobby Licht", lamp)
    scene.collection.objects.link(lamp_obj)
    lamp_obj.location = c + Vector((0, 0, LOBBY_CEIL + 2.5))   # 2.5 m below the ceiling
# Furnishing of the lobby (Space Bar as in station.terms: "Space Bar with straps and holds for short stays", Job Board from
# station.modules): zero g, up is towards the shadow side (floor on the sun side). Handrail on all outer walls at
# 1 m, counter with an illuminated edge and foot loops in front, shelf with bottles behind, notice board with notes on the end wall
bm_rail, bm_bar_l, bm_shelf, bm_board, bm_notes, bm_bottles = (bmesh.new() for _ in range(6))
for c in centres_l:
    corners = [Vector((x, y, 0)) for x, y in hexagon(c.x, c.y, size, rot=30)]
    for k in range(6):
        a, b = corners[k], corners[(k + 1) % 6]
        if any((c + ((a + b) / 2 - c) * 2 - other).length < 0.5 for other in centres_open):
            continue
        inward = (c - (a + b) / 2).normalized() * 0.3
        rods(bm_rail, [a + inward + Vector((0, 0, LOBBY_FLOOR - 1.0)), b + inward + Vector((0, 0, LOBBY_FLOOR - 1.0))], 0.04)
sb_cells = [Vector((*cell_xy(q, r), 0)) for q, r in layout.get("modules", {}).get("spacebar", [])]
if sb_cells:
    # cells with a corner at the top and bottom: the straight walls lie at the sides (x = centre ± 5 m); counter and shelf on the
    # right, notice board on the left outer wall of the Space Bar (in front of the bend of the end wall they looked crooked)
    left, right = min(sb_cells, key=lambda p: p.x), max(sb_cells, key=lambda p: p.x)
    flat = size * math.sqrt(3) / 2
    wall_r, wall_l = right.x + flat, left.x - flat
    bmesh.ops.create_cube(bm_bar_l, size=1.0, matrix=Matrix.Translation((wall_r - 2.6, right.y, LOBBY_FLOOR - 0.55)) @ Matrix.Diagonal((0.8, 5.0, 1.1, 1)))
    bmesh.ops.create_cube(bm_bottles, size=1.0, matrix=Matrix.Translation((wall_r - 3.0, right.y, LOBBY_FLOOR - 1.12)) @ Matrix.Diagonal((0.06, 5.0, 0.04, 1)))
    for i in range(6):   # foot loops in front of the counter: in zero g one holds on with the feet
        y = right.y - 2.0 + i * 0.8
        rods(bm_rail, [Vector((wall_r - 3.4, y - 0.15, LOBBY_FLOOR)), Vector((wall_r - 3.4, y - 0.15, LOBBY_FLOOR - 0.2)),
                       Vector((wall_r - 3.4, y + 0.15, LOBBY_FLOOR - 0.2)), Vector((wall_r - 3.4, y + 0.15, LOBBY_FLOOR))], 0.025)
    for level in range(3):   # shelf on the wall behind the counter, bottles with clips (zero g)
        z = LOBBY_FLOOR - 1.6 + level * 0.7
        bmesh.ops.create_cube(bm_shelf, size=1.0, matrix=Matrix.Translation((wall_r - 0.25, right.y, z)) @ Matrix.Diagonal((0.4, 4.6, 0.05, 1)))
        for i in range(9):
            bmesh.ops.create_cone(bm_bottles if i % 3 == 0 else bm_shelf, cap_ends=True, segments=8, radius1=0.08, radius2=0.05, depth=0.3,
                                  matrix=Matrix.Translation((wall_r - 0.3, right.y - 2.0 + i * 0.5, z - 0.18)))
    board_c = Vector((wall_l + 0.06, left.y, LOBBY_FLOOR - 2.4))   # notice board (Job Board) on the left wall, 4 x 2.5 m
    bmesh.ops.create_cube(bm_board, size=1.0, matrix=Matrix.Translation(board_c) @ Matrix.Diagonal((0.08, 4.0, 2.5, 1)))
    random.seed(23)
    for i in range(14):   # notes: requests to the WissKomm Wiki
        p = board_c + Vector((0.06, random.uniform(-1.7, 1.7), random.uniform(-1.0, 1.0)))
        bmesh.ops.create_cube(bm_notes, size=1.0, matrix=Matrix.Translation(p) @ Matrix.Rotation(random.uniform(-0.15, 0.15), 4, "X")
                              @ Matrix.Diagonal((0.01, 0.32, 0.42, 1)))
mesh_object("Lobby Handläufe und Schlaufen", bm_rail, solid("Handlauf", (0.75, 0.62, 0.2), roughness=0.35, metallic=0.7))
mesh_object("Space Bar Tresen", bm_bar_l, solid("Tresen", (0.12, 0.1, 0.09), roughness=0.4))
mesh_object("Space Bar Licht und Flaschen", bm_bottles, glow("Barlicht", (1.0, 0.6, 0.25), 3.0))
mesh_object("Space Bar Regal", bm_shelf, solid("Regal", (0.3, 0.32, 0.36), roughness=0.4, metallic=0.4))
mesh_object("Job Board", bm_board, solid("Kork", (0.55, 0.4, 0.25), roughness=0.9))
mesh_object("Job Board Zettel", bm_notes, solid("Zettel", (0.95, 0.92, 0.75), roughness=0.9))




# Equipment on the shadow side of the modules: technical boxes, pipe sections and one pair of radiators per module at the
# deepest cell, as on the modules of the ISS (reference: NASA 3D Resources); random but fixed (seed), grey-box shapes only
bm_greeble, bm_radiator = bmesh.new(), bmesh.new()
random.seed(17)
for module_id, cells in layout.get("modules", {}).items():
    if module_id in ("transfer", "spacebar", "hangar", "map_room") or not cells:
        continue
    bottom = -1.2 - depths.get(module_id, 10.0)
    for q, r in cells:
        cx, cy = cell_xy(q, r)
        for _ in range(random.randint(1, 3)):   # boxes beside the window (window: 55 % of the cell in the middle)
            ang, dist = random.uniform(0, 2 * math.pi), random.uniform(3.4, 4.4)
            sx, sy, sz = random.uniform(0.8, 1.8), random.uniform(0.8, 1.8), random.uniform(0.4, 1.4)
            bmesh.ops.create_cube(bm_greeble, size=1.0, matrix=Matrix.Translation((cx + dist * math.cos(ang), cy + dist * math.sin(ang), bottom - sz / 2))
                                  @ Matrix.Rotation(ang, 4, "Z") @ Matrix.Diagonal((sx, sy, sz, 1)))
        if random.random() < 0.35:   # pipe section across the cell
            ang = random.uniform(0, math.pi)
            rot = Matrix.Rotation(ang, 4, "Z") @ Matrix.Rotation(math.pi / 2, 4, "Y")
            bmesh.ops.create_cone(bm_greeble, cap_ends=True, segments=10, radius1=0.25, radius2=0.25, depth=7.0,
                                  matrix=Matrix.Translation((cx, cy, bottom - 0.6)) @ rot)
    qd, rd = max(cells, key=lambda c: cell_xy(*c)[0] ** 2 + cell_xy(*c)[1] ** 2)   # outermost cell: radiators point outwards
    cx, cy = cell_xy(qd, rd)
    out = Vector((cx, cy, 0)).normalized() if (cx or cy) else Vector((1, 0, 0))
    for side in (-1, 1):   # two wings, 12 x 4 m, below the module on the shadow side, across the outward direction
        centre = Vector((cx, cy, bottom - 3.0)) + out.cross(Vector((0, 0, 1))) * side * 4.0
        bmesh.ops.create_cube(bm_radiator, size=1.0, matrix=Matrix.Translation(centre) @ Matrix.Rotation(math.atan2(out.y, out.x), 4, "Z")
                              @ Matrix.Diagonal((12.0, 0.15, 4.0, 1)))
mesh_object("Aufbauten der Module", bm_greeble, m_frame)
mesh_object("Radiatoren der Module", bm_radiator, solid("Radiator", (0.88, 0.89, 0.9), roughness=0.25, metallic=0.2))
m_module = hull_material("Modulhülle (Poly Haven metal_plate_02)", BASE / "media" / "polyhaven" / "metal_plate_02")
for bm_out in (bm_hangar, bm_corr, bm_map, *bm_per_module.values()):   # prism() creates the sides with normals pointing inwards:
    bmesh.ops.recalc_face_normals(bm_out, faces=bm_out.faces[:])   # dark from outside
for module_id, bm_one in bm_per_module.items():
    if bm_one.faces:   # the Space Bar is in the inventory as the lobby (Lobby Boden, Decke, Wände)
        mesh_object(f"Modul {module_id}", bm_one, m_module)["wkw_id"] = module_id   # identifier as in the plan
bm_mod.free()
# Scattered light on the shadow side: the lit ring throws light onto the back of the hub; without it modules, equipment and
# radiators stayed black from behind. A weak sun from the shadow side; the ring shields its inside
fill = bpy.data.lights.new("Streulicht Schattenseite", "SUN")
fill.energy, fill.color = float(CONFIG.get("hub_fill_strength", 1.2)), (0.85, 0.9, 1.0)
fill.use_shadow = False   # scattered light has no hard direction; with shadows the undersides stayed dark
fill_obj = bpy.data.objects.new("Streulicht Schattenseite", fill)
scene.collection.objects.link(fill_obj)
fill_obj.rotation_euler = (math.radians(160), math.radians(10), 0)   # shines towards the sun, slightly oblique to bring out the edges
mesh_object("Hangar am Rand", bm_hangar, glass("Hangar aus Glas", (0.0, 0.62, 0.45), 0.4))["wkw_id"] = "hangar"   # ships visible inside
mesh_object("Modulfenster", bm_win, m_window)
mesh_object("Gang-Module", bm_corr, m_corridor)
bm_map.free()   # map room no longer as a glass block (build_map_room)


HUB_TURN, HUB_ROOT = 0.0, None   # angle at which the hub stands after decoupling (hub_root_object)


def centroid(module_id):
    cells = layout.get("modules", {}).get(module_id, [])
    return Vector((sum(cell_xy(q, r)[0] for q, r in cells) / len(cells), sum(cell_xy(q, r)[1] for q, r in cells) / len(cells), 0)) if cells else None


map_centre = centroid("map_room")
if map_centre:   # globe of the map room, radius 6 m, in the middle of the room; below it the dark star map with nine lights
    map_depth = depths.get("map_room", 20.0)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=6, location=map_centre + Vector((0, 0, -1.2 - map_depth / 2)))
    bpy.context.active_object.name = "Kugel im Kartenraum"
    bpy.context.active_object.data.materials.append(glow("Kugel", (0.45, 0.8, 1.0), 6.0))


def build_map_room():
    """Map room as one room, adopted from an earlier test scene: the floor is the star map, fully digital, on the sun side;
    galaxies = platforms, suns = channels, planets = videos and podcasts, nearly everything dark; walls only outside with
    lines every 3.33 m, on the shadow side the ceiling with windows to the stars; open to the Space Bar."""
    cells = [tuple(c) for c in layout.get("modules", {}).get("map_room", [])]
    if not cells:
        return
    funnel = CONFIG.get("map_room_funnel")   # funnel above (build_funnel): the honeycomb drum is then only as high as where the funnel begins
    depth, floor = float(funnel["profile"][0][0]) if funnel else depths.get("map_room", 20.0), -1.2
    ceiling = floor - depth
    m_map = solid("Sternkarte", (0.006, 0.012, 0.025), roughness=0.22, metallic=0.85)   # screen off: dark, slightly reflective
    bm_floor, bm_lines, bm_wall, bm_deck, bm_glass, bm_ceil = (bmesh.new() for _ in range(6))
    for q, r in cells:
        cx, cy = cell_xy(q, r)
        prism(bm_floor, hexagon(cx, cy, size - 0.08, rot=30), floor, floor - 0.3)
        corners = hexagon(cx, cy, size, rot=30)
        for k in range(6):
            (x0, y0), (x1, y1) = corners[k], corners[(k + 1) % 6]
            nx, ny = -(y1 - y0), x1 - x0
            length = math.hypot(nx, ny)
            nx, ny = nx / length * 0.06, ny / length * 0.06
            prism(bm_lines, [(x0 - nx, y0 - ny), (x1 - nx, y1 - ny), (x1 + nx, y1 + ny), (x0 + nx, y0 + ny)], floor - 0.3, floor - 0.32)
            across = Vector((cx, cy, 0)) + (Vector(((x0 + x1) / 2, (y0 + y1) / 2, 0)) - Vector((cx, cy, 0))) * 2
            if any((across - o).length < 0.5 for o in centres_map):
                continue   # neighbour in the room: no wall
            to_lobby = any((across - o).length < 0.5 for o in centres_l)
            top = LOBBY_CEIL if to_lobby else floor   # open to the lobby, as high as the lobby; wall below
            out = Vector(((x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy, 0)).normalized() * 0.15
            if top > ceiling:
                prism(bm_wall, [(x0, y0), (x1, y1), (x1 + out.x, y1 + out.y), (x0 + out.x, y0 + out.y)], top, ceiling)
            for s in range(1, int(depth / STEP)):
                z = floor - s * STEP
                if z < top:
                    prism(bm_deck, [(x0 - out.x * 0.5, y0 - out.y * 0.5), (x1 - out.x * 0.5, y1 - out.y * 0.5), (x1, y1), (x0, y0)], z + 0.06, z - 0.06)
        if funnel:
            continue   # the ceiling with windows is then carried by the funnel above
        prism(bm_glass, hexagon(cx, cy, size * 0.7, rot=30), ceiling, ceiling - 0.05)
        outer, inner = hexagon(cx, cy, size, rot=30), hexagon(cx, cy, size * 0.7, rot=30)
        for k in range(6):
            j = (k + 1) % 6
            prism(bm_ceil, [outer[k], outer[j], inner[j], inner[k]], ceiling, ceiling - 0.6)
    for bm_out in (bm_floor, bm_wall, bm_ceil):
        bmesh.ops.recalc_face_normals(bm_out, faces=bm_out.faces[:])
    mesh_object("Kartenraum Sternkarte", bm_floor, m_map)["wkw_id"] = "map_room"   # comparison in the planner
    mesh_object("Kartenraum Wabenrahmen", bm_lines, glow("Wabenrahmen Karte", WKW["700"], 0.6))
    mesh_object("Kartenraum Wände", bm_wall, solid("Kartenraumwand", (0.62, 0.64, 0.66), roughness=0.6, metallic=0.2))
    mesh_object("Kartenraum Decklinien", bm_deck, glow("Decklinie", WKW["400"], 0.7))
    mesh_object("Kartenraum Fenster", bm_glass, glass("Kartenraum Fenster", (0.25, 0.45, 0.6), 0.25))
    mesh_object("Kartenraum Deckenrahmen", bm_ceil, solid("Deckenrahmen", (0.22, 0.24, 0.27), roughness=0.5, metallic=0.7))
    # star map as in the earlier test, positions relative to the middle of the room; only what lies above a cell of the room
    inside = lambda x, y: any((Vector((x, y, 0)) - o).length < size * 0.95 for o in centres_map)
    rng = random.Random(28)
    galaxies = [(-14, -8), (12, -14), (16, 12), (-12, 15), (0, 2)]
    z_map = floor - 0.34   # just above the map (towards the room)
    bm_dust, bm_sun, bm_orbit, bm_planet = bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new()

    def disc(bm, x, y, radius, n=10):
        if inside(x, y):
            prism(bm, [(x + radius * math.cos(2 * math.pi * i / n), y + radius * math.sin(2 * math.pi * i / n)) for i in range(n)], z_map, z_map - 0.02)

    suns = []
    for g, (gx, gy) in enumerate(galaxies):
        gx, gy = map_centre.x + gx, map_centre.y + gy
        twist = rng.uniform(0, math.tau)
        for arm in range(2):   # two spiral arms of dust
            for i in range(90):
                t, a = i / 90, twist + arm * math.pi + i / 90 * 3.2
                disc(bm_dust, gx + (1 + t * 8.5) * math.cos(a) + rng.normalvariate(0, 0.35), gy + (1 + t * 8.5) * math.sin(a) + rng.normalvariate(0, 0.35),
                     rng.choice((0.04, 0.05, 0.08)), n=4)
        for s in range(rng.randint(4, 6)):   # suns on the arms, planets on orbits
            t = rng.uniform(0.2, 0.95)
            a = twist + rng.choice((0, math.pi)) + t * 3.2
            sx, sy = gx + (1 + t * 8.5) * math.cos(a), gy + (1 + t * 8.5) * math.sin(a)
            planets = []
            for p in range(rng.randint(2, 5)):
                radius = 0.6 + 0.35 * p
                for i in range(32):
                    a0, a1 = 2 * math.pi * i / 32, 2 * math.pi * (i + 1) / 32
                    if inside(sx, sy):
                        prism(bm_orbit, [(sx + (radius - 0.025) * math.cos(a0), sy + (radius - 0.025) * math.sin(a0)),
                                         (sx + (radius - 0.025) * math.cos(a1), sy + (radius - 0.025) * math.sin(a1)),
                                         (sx + (radius + 0.025) * math.cos(a1), sy + (radius + 0.025) * math.sin(a1)),
                                         (sx + (radius + 0.025) * math.cos(a0), sy + (radius + 0.025) * math.sin(a0))], z_map + 0.005, z_map - 0.005)
                pa = rng.uniform(0, math.tau)
                planets.append((sx + radius * math.cos(pa), sy + radius * math.sin(pa)))
            suns.append((sx, sy, planets, g))
    lit = [suns[0], next(s for s in suns if s[3] == 2)]   # first entries: one sun in galaxy 0, one in galaxy 2
    for sun in suns:
        if sun in lit:
            continue
        disc(bm_sun, sun[0], sun[1], 0.22)
        for px, py in sun[2]:
            disc(bm_planet, px, py, 0.09, n=8)
    bm_lit = bmesh.new()
    for k, (sx, sy, planets, _) in enumerate(lit):   # glowing entries just above the map
        bmesh.ops.create_uvsphere(bm_lit, u_segments=16, v_segments=8, radius=0.3, matrix=Matrix.Translation((sx, sy, z_map - 0.4)))
        for px, py in planets[: 3 if k == 0 else 1]:
            bmesh.ops.create_uvsphere(bm_lit, u_segments=12, v_segments=6, radius=0.14, matrix=Matrix.Translation((px, py, z_map - 0.3)))
    mesh_object("Sternkarte Staub der Galaxien", bm_dust, glow("Staub", (0.45, 0.6, 0.9), 0.35))
    mesh_object("Sternkarte Sonnen (Kanäle)", bm_sun, glow("Sonne dunkel", (1.0, 0.8, 0.5), 0.9))
    mesh_object("Sternkarte Bahnen", bm_orbit, glow("Bahn", (0.4, 0.55, 0.8), 0.25))
    mesh_object("Sternkarte Planeten (Videos, Podcasts)", bm_planet, glow("Planet dunkel", (0.6, 0.8, 1.0), 0.7))
    mesh_object("Sternkarte, erste Einträge", bm_lit, glow("Eintrag", (0.45, 1.0, 1.0), 10.0))
    fill_map = bpy.data.lights.new("Kartenraum Wandlicht", "AREA")   # soft, below the windows, shines towards the map (towards the sun, +z)
    fill_map.energy, fill_map.size, fill_map.color = float(CONFIG.get("map_room_light_watts", 25000)), 50, (0.85, 0.92, 1.0)
    fill_map_obj = bpy.data.objects.new("Kartenraum Wandlicht", fill_map)
    scene.collection.objects.link(fill_map_obj)
    fill_map_obj.location = map_centre + Vector((0, 0, ceiling + 1.0))
    fill_map_obj.rotation_euler = (math.pi, 0, 0)
    if funnel:
        build_funnel(funnel, floor, fill_map_obj, [(s[0], s[1]) for s in lit])


def build_funnel(spec, floor, fill_obj, lit_points=()):
    """Funnel above the honeycomb drum of the map room: a lobby that uses the full height, with many tiers above, wider towards
    the top; in zero g one glides across easily. Surface of revolution from config.yaml map_room_funnel.profile, at the top
    (shadow side) a glass roof to the stars, tiers as ring galleries with a glowing edge, floating platforms in front, in the
    middle the globe only hinted at and orbits as spirals. Up is towards the shadow side (-z) here."""
    profile = [(floor - float(d), float(r)) for d, r in spec["profile"]]   # (z, radius), from the drum upwards

    def radius_at(z):
        for (z0, r0), (z1, r1) in zip(profile, profile[1:]):
            if z1 <= z <= z0:
                return r0 + (r1 - r0) * (z0 - z) / (z0 - z1)
        return profile[-1][1]

    n = 96
    c = map_centre
    ring = lambda z, r: [c + Vector((r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), z)) for i in range(n)]
    bm_wall, bm_tier, bm_edge, bm_pod, bm_rim, bm_roof, bm_glass_r, bm_paths, bm_ceiling = (bmesh.new() for _ in range(9))
    rows = [[bm_wall.verts.new(p) for p in ring(z, r)] for z, r in profile]
    for low, high in zip(rows, rows[1:]):   # wall of the funnel
        for i in range(n):
            bm_wall.faces.new((low[i], low[(i + 1) % n], high[(i + 1) % n], high[i]))
    z_top, r_top = profile[-1]
    width, every = float(spec.get("tier_width", 4)), float(spec.get("tiers_every", 10))
    z_tiers_end = floor - float(spec.get("tiers_until", spec["profile"][-1][0]))   # no tiers in the tip of the cone
    tier_z = [profile[0][0] - k * every for k in range(int((profile[0][0] - z_tiers_end) / every) + 1)]   # first tier = rim of the drum
    for k, z in enumerate(tier_z):
        r_out = radius_at(z) + (0.0 if k else 1.0)
        r_in = (28.0 if k == 0 else r_out - width)   # at the bottom the first tier covers the corners of the cells up to the funnel
        outer, inner = ring(z - 0.05, r_out), ring(z - 0.05, r_in)
        for i in range(n):
            j = (i + 1) % n
            bm_tier.faces.new([bm_tier.verts.new(p) for p in (outer[i], outer[j], inner[j], inner[i])])
        rods(bm_edge, ring(z - 1.1, r_in + 0.2) + ring(z - 1.1, r_in + 0.2)[:1], 0.05)   # railing, up is -z
        rods(bm_edge, ring(z - 0.1, r_in) + ring(z - 0.1, r_in)[:1], 0.08)   # glowing edge
        pods = int(spec.get("pods_per_tier", 18))
        for p in range(pods):   # floating platforms in front of the tier, offset per tier
            a = 2 * math.pi * (p + 0.5 * (k % 2)) / pods
            rr = r_in - 3.5 - 1.5 * (p % 2)
            centre = c + Vector((rr * math.cos(a), rr * math.sin(a), z - 2.0 - 1.2 * ((p + k) % 3)))
            bmesh.ops.create_cone(bm_pod, cap_ends=True, segments=16, radius1=1.5, radius2=1.1, depth=0.4, matrix=Matrix.Translation(centre))
            rods(bm_rim, [centre + Vector((1.5 * math.cos(2 * math.pi * i / 16), 1.5 * math.sin(2 * math.pi * i / 16), -0.2)) for i in range(17)], 0.04)
    # ceiling: one large transparent pane with a honeycomb pattern across the whole cross-section; the hexagon edges glow like
    # the cells of the collector; before, a small window with spokes in the tip of the cone
    outer = ring(z_top, r_top)
    bm_glass_r.faces.new([bm_glass_r.verts.new(p) for p in outer])
    rods(bm_roof, ring(z_top + 0.3, r_top) + ring(z_top + 0.3, r_top)[:1], 0.4)
    cell = float(spec.get("ceiling_cell", 6.0))   # edge length of the cells in m
    w_hex, h_hex = math.sqrt(3) * cell, 1.5 * cell
    for row in range(-int(r_top / h_hex) - 1, int(r_top / h_hex) + 2):
        for col in range(-int(r_top / w_hex) - 1, int(r_top / w_hex) + 2):
            cx, cy = col * w_hex + (w_hex / 2 if row % 2 else 0.0), row * h_hex
            corners = [Vector((cx + cell * math.cos(math.pi / 6 + math.pi / 3 * k), cy + cell * math.sin(math.pi / 6 + math.pi / 3 * k), 0))
                       for k in range(7)]
            if all(p.length < r_top - 0.5 for p in corners):
                rods(bm_ceiling, [c + p + Vector((0, 0, z_top + 0.2)) for p in corners], 0.12)
    # surfaces from Poly Haven (CC0, see the list of Poly Haven assets): plaster on the wall, wood on the tiers like the galleries
    # in the atrium of the reference images, plants on every tier
    mesh_object("Kartenraum Trichter", bm_wall, pbr("Trichterwand Putz", "painted_plaster_wall", size_m=4.0, tint=(0.95, 0.96, 0.98)))
    mesh_object("Kartenraum Ränge", bm_tier, pbr("Rang Holz", "wood_floor", size_m=3.0))
    plants = int(spec.get("plants_per_tier", 8))
    for k, z in enumerate(tier_z):
        r_in = 28.0 if k == 0 else radius_at(z) - width
        for p in range(plants):
            a = 2 * math.pi * (p + 0.5 * (k % 2)) / plants + 0.2
            root = model("potted_plant_02", c + Vector(((r_in + 1.2) * math.cos(a), (r_in + 1.2) * math.sin(a), z - 0.05)), scale=2.5)
            root.rotation_euler = (math.pi, 0, a)   # grows towards the shadow side: up is -z here
    mesh_object("Kartenraum Geländer und Leuchtkanten", bm_edge, glow("Rangkante", WKW["400"], 1.2))
    mesh_object("Kartenraum Plattformen", bm_pod, solid("Plattform", (0.2, 0.22, 0.25), roughness=0.4, metallic=0.6))
    mesh_object("Kartenraum Plattformränder", bm_rim, glow("Plattformrand", WKW["300"], 1.5))
    mesh_object("Kartenraum Glasdach", bm_glass_r, glass("Kartenraum Glasdach", (0.25, 0.45, 0.6), 0.2))
    mesh_object("Kartenraum Dachrahmen", bm_roof, solid("Dachrahmen", (0.22, 0.24, 0.27), roughness=0.5, metallic=0.7))
    mesh_object("Kartenraum Wabendecke", bm_ceiling, glow("Wabenkante", (0.55, 0.85, 1.0), 2.0))
    bm_paths.free()
    # Outside made of honeycomb panels: hexagonal panels the size of the modules on the outside of the funnel, hull as the
    # modules, corner at the top and bottom; the wall behind shows in the joints. Columns over the circumference at the top
    # (r_top); further down the cone the panels move closer together accordingly
    shell = spec.get("outer_cells")
    if shell:
        bm_shell = bmesh.new()
        cols = int(shell.get("columns", 28))
        lift, inset = float(shell.get("lift", 0.4)), float(shell.get("inset", 0.92))
        s_hex = 2 * math.pi * r_top / cols / math.sqrt(3)   # circumradius; width of a column = edge to edge
        z_low = profile[0][0]   # start of the funnel above the drum; up is -z
        for row in range(int((z_low - z_top) / (1.5 * s_hex)) + 2):
            zc = z_low - row * 1.5 * s_hex
            for col in range(cols):
                ac = 2 * math.pi * (col + 0.5 * (row % 2)) / cols

                def on_wall(du, dz, extra):
                    z = min(z_low, max(z_top, zc + dz))
                    r = radius_at(z)
                    return c + Vector(((r + extra) * math.cos(ac + du / r), (r + extra) * math.sin(ac + du / r), z))

                ring_k = [(s_hex * inset * math.cos(math.radians(90 + 60 * k)), s_hex * inset * math.sin(math.radians(90 + 60 * k))) for k in range(6)]
                outer_k = [on_wall(du, dz, lift) for du, dz in ring_k]
                if max(p.z for p in outer_k) - min(p.z for p in outer_k) < 0.5:
                    continue   # entirely above or below the funnel
                vo = [bm_shell.verts.new(p) for p in outer_k]
                vi = [bm_shell.verts.new(on_wall(du, dz, 0.02)) for du, dz in ring_k]
                vc = bm_shell.verts.new(on_wall(0.0, 0.0, lift))   # fan around the centre: the panel is curved
                for k in range(6):
                    j = (k + 1) % 6
                    bm_shell.faces.new((vc, vo[k], vo[j]))
                    bm_shell.faces.new((vo[k], vi[k], vi[j], vo[j]))
        bmesh.ops.recalc_face_normals(bm_shell, faces=bm_shell.faces[:])
        mesh_object("Kartenraum Außenwaben", bm_shell, m_module)
    # Handrail along the path: in zero g one needs a handrail right from the start, beside oneself, to hold on to while moving
    # along and looking up. From the cabin through the opening to the end position, to the right of the path; replaces the
    # ring around the centre. Points relative to the middle of the room as for the panels; posts stand on the floor of the
    # lobby (z -1.3), 0.2 m into the floor in the star map
    rail = spec.get("railing")
    if rail and rail.get("path"):
        h_rail, foot_z = float(rail.get("height", 1.0)), float(rail.get("foot_z", -1.3))
        path = [c + Vector((float(x), float(y), foot_z - h_rail)) for x, y in rail["path"]]
        bm_rail, bm_post = bmesh.new(), bmesh.new()
        rods(bm_rail, path, 0.045)
        rods(bm_post, [p + Vector((0, 0, h_rail * 0.45)) for p in path], 0.02)   # second rail at half height
        every = float(rail.get("posts_every", 2.5))
        for p0, p1 in zip(path, path[1:]):
            n_posts = max(1, round((p1 - p0).length / every))
            for i in range(n_posts + 1):
                top_p = p0 + (p1 - p0) * (i / n_posts)
                rods(bm_post, [top_p + Vector((0, 0, h_rail)), top_p], 0.035)
        mesh_object("Kartenraum Handlauf", bm_rail, glow("Handlauf Kartenraum", WKW["400"], 1.5))
        mesh_object("Kartenraum Handlaufpfosten", bm_post, solid("Geländerpfosten", (0.55, 0.58, 0.62), roughness=0.35, metallic=0.9))
    globe = bpy.data.objects.get("Kugel im Kartenraum")   # only hinted at: transparent shell with glowing meridians and parallels
    if globe:   # (as pure glow it looked like a flat disc)
        g = spec.get("globe", {})
        centre_g, radius_g = c + Vector((0, 0, floor - float(g.get("depth", 34)))), float(g.get("radius", 7))
        globe.location = centre_g
        # globe as in the earlier test scene: glowing core, networks with nodes and shell from datenbaum.build_globe, which
        # looks like a mysterious data creature; the former empty glass shell with meridians and parallels stays invisible
        globe.hide_render = globe.hide_viewport = True
        # one full turn in turn_seconds, in frames of this run's level: the final hold 09.5 plays in the deck as a seamless loop
        # (rendered as a short loop, not 120 s)
        quality = CONFIG.get("ride_quality", {}).get(ARGS[ARGS.index("--quality") + 1] if "--quality" in ARGS else "preview", {})
        turn = round(float(g["turn_seconds"]) * int(quality.get("fps", 24))) if g.get("turn_seconds") else None
        build_globe(centre_g, radius=radius_g, icon_dir=BASE / "_scratch" / "globe_icons" / "icons", roof_z=None, seed=11, turn_frames=turn)
        # Conduits with a purpose, connecting the globe with something: from the globe to the neighbouring modules (hatch in the
        # wall in their direction and depth, from the plan), to the opening of the Space Bar and down to the glowing entries of
        # the star map; glass conduits with flowing light as in the earlier test
        anchors = {}
        near = []
        for mid in layout.get("modules", {}):
            centre_m = centroid(mid)
            if mid in ("map_room", "transfer") or centre_m is None:
                continue
            offset = Vector((centre_m.x - c.x, centre_m.y - c.y, 0))
            if 0.1 < offset.length < float(spec.get("link_radius", 80)):
                near.append((offset.length, mid, offset.normalized()))
        for _, mid, direction in sorted(near)[: int(spec.get("links", 8))]:
            depth_m = depths.get(mid, 10.0)
            if mid == "spacebar" or depth_m <= profile[0][0] - floor + 2:   # flat neighbours: at the drum, below lobby height
                if mid == "spacebar":   # 25 degrees beside the camera path from the lobby (otherwise only 0.01 and 0.18 m clearance at the conduit)
                    direction = Quaternion((0, 0, 1), math.radians(25)) @ direction
                anchors[mid] = c + direction * 29.0 + Vector((0, 0, floor - 5.0))
            else:
                z_m = floor - min(max(depth_m * 0.5, 15.0), 95.0)
                anchors[mid] = c + direction * (radius_at(z_m) - 0.4) + Vector((0, 0, z_m))
        for k, (x, y) in enumerate(lit_points):
            anchors[f"sternkarte_{k}"] = Vector((x, y, floor - 0.8))
        # straight, thin light beams instead of glass hoses and cables (as in the earlier test: thin light beams to the star map)
        bm_beam = bmesh.new()
        for anchor in anchors.values():
            anchor = Vector(anchor)
            out = (anchor - centre_g).normalized()
            rods(bm_beam, [centre_g + out * radius_g * 1.02, anchor], 0.035)
        mesh_object("Kartenraum Lichtstrahlen", bm_beam, glow("Lichtstrahl", (0.55, 0.92, 1.0), 8.0))
        print(f"Kartenraum: Leitungen von der Kugel zu {', '.join(anchors)}", flush=True)
        for mid, anchor in anchors.items():   # position relative to the middle of the room as for the panels (offset), for paths past the beams
            rel = Vector(anchor) - c
            print(f"  {mid}: offset [{rel.x:.1f}, {rel.y:.1f}, {rel.z:.1f}], Azimut {math.degrees(math.atan2(rel.y, rel.x)):.0f} Grad", flush=True)
    fill_obj.location = c + Vector((0, 0, (profile[0][0] + z_tiers_end) / 2))   # at mid height, shines towards the star map
    fill_obj.data.size = 2 * max(r for _, r in profile)
    fill_obj.data.energy = float(spec.get("light_watts", 90000))


if map_centre:
    build_map_room()
corridor_set = set(corridors)
for q, r in corridors:   # tube railway: tube through neighbouring corridor modules
    for dq, dr in ((1, 0), (0, 1), (1, -1)):
        if (q + dq, r + dr) in corridor_set:
            p0, p1 = Vector((*cell_xy(q, r), -1.2 - STEP / 2)), Vector((*cell_xy(q + dq, r + dr), -1.2 - STEP / 2))
            bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.9, depth=(p1 - p0).length, location=(p0 + p1) / 2)
            tube = bpy.context.active_object
            tube.name = "Röhrenbahn"
            tube.rotation_mode = "QUATERNION"
            tube.rotation_quaternion = (p1 - p0).to_track_quat("Z", "Y")
            tube.data.materials.append(m_cabin)

# axis tube reaching behind the spokes, distribution mirror at its rear, docking module on the axis
axis_end = SPOKE_Z - 40
# Axis tube: behind the bearing ring metal up to the docking module; from the ring up to the floor of the lobby glass, open,
# without a lid: inside it the cabin continues from the spoke towards the sun, straight up to the transfer point at the
# Space Bar; through the glass one sees the backs of the modules and the spokes
bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=10, depth=-(axis_end - (SPOKE_Z - COLLAR_H / 2)),
                                    location=(0, 0, (axis_end + SPOKE_Z - COLLAR_H / 2) / 2))
bpy.context.active_object.name = "Achsrohr"
bpy.context.active_object["wkw_id"] = "transfer"
bpy.context.active_object.data.materials.append(m_axis)
bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=10, depth=LOBBY_CEIL - (SPOKE_Z + COLLAR_H / 2), end_fill_type="NOTHING",
                                    location=(0, 0, (LOBBY_CEIL + SPOKE_Z + COLLAR_H / 2) / 2))
bpy.context.active_object.name = "Achsrohr aus Glas"
bpy.context.active_object.data.materials.append(glass("Achsrohr Glas", (0.8, 0.9, 1.0), 0.12))
dish_top = -float(HUB.get("module_zone", 130)) + 8   # in front of the modules at the deepest point, 18 m in front of the spokes
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=40, location=(0, 0, dish_top - 40))
dish = bpy.context.active_object   # spherical cap, 24 m radius: bulges towards the sun, scatters the light of the centre mirrors onto the windows
dish.name = "Verteilspiegel"
bm = bmesh.new()
bm.from_mesh(dish.data)
bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < 32 or math.hypot(v.co.x, v.co.y) < 10.5], context="VERTS")   # hole for the axis tube
bm.to_mesh(dish.data)
bm.free()
dish.data.materials.append(m_dish)
bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=22, depth=24, location=(0, 0, axis_end - 12), rotation=(0, 0, 0))
dock = bpy.context.active_object
dock.name = "Andockmodul an der Achse"
dock.data.materials.append(m_hangar)

# Equipment on the hub: antennas at the broadcasting centre towards the shadow side (where the stars stand still), tanks and
# trusses in the industrial sector; all grey, positions from the honeycomb plan
bm_tech = bmesh.new()
transmitter = centroid("transmitter")
if transmitter:
    base_z = -1.2 - depths.get("transmitter", 10.0)
    for k, (dx, dy) in enumerate(((0, 0), (14, 6), (-12, 8))):
        foot = transmitter + Vector((dx, dy, base_z))
        bmesh.ops.create_cone(bm_tech, cap_ends=True, segments=8, radius1=0.6, radius2=0.6, depth=8,
                              matrix=Matrix.Translation(foot + Vector((0, 0, -4))))
        bmesh.ops.create_cone(bm_tech, cap_ends=True, segments=24, radius1=0.6, radius2=7 - 2 * min(k, 1), depth=3,
                              matrix=Matrix.Translation(foot + Vector((0, 0, -9.5))))
industry = centroid("industry")
if industry:
    base_z = -1.2 - depths.get("industry", 20.0)
    for dx, dy in ((-10, -6), (0, 8), (10, -6), (0, -16)):
        bmesh.ops.create_uvsphere(bm_tech, u_segments=16, v_segments=8, radius=5.5,
                                  matrix=Matrix.Translation(industry + Vector((dx, dy, base_z - 6))))
    for dx in (-14, 0, 14):   # truss: three beams across
        bmesh.ops.create_cube(bm_tech, size=1.0, matrix=Matrix.Translation(industry + Vector((dx, 0, base_z - 1.5)))
                              @ Matrix.Diagonal((1.2, 36, 1.2, 1)))
mesh_object("Antennen und Industrie", bm_tech, m_frame)

# ladders in the spokes (elevator and ladder): two rails, rungs every 3 m (grey box; real ones 0.3 m)
bm_ladder = bmesh.new()
for a in spoke_angles:
    d = Vector((math.cos(a), math.sin(a), 0))
    side_v = Vector((-d.y, d.x, 0))
    start, end = 14.0, R - RIM
    rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    for s in (-0.25, 0.25):
        centre = d * (start + end) / 2 + side_v * (5.0 + s) + Vector((0, 0, SPOKE_Z))
        bmesh.ops.create_cone(bm_ladder, cap_ends=True, segments=6, radius1=0.06, radius2=0.06, depth=end - start,
                              matrix=Matrix.Translation(centre) @ rot)
    side_rot = side_v.to_track_quat("Z", "Y").to_matrix().to_4x4()
    for k in range(int((end - start) // 3)):
        p = d * (start + 3 * k) + side_v * 5.0 + Vector((0, 0, SPOKE_Z))
        bmesh.ops.create_cone(bm_ladder, cap_ends=True, segments=6, radius1=0.04, radius2=0.04, depth=0.5,
                              matrix=Matrix.Translation(p) @ side_rot)
mesh_object("Leitern", bm_ladder, m_cabin, rotor)

# people for scale (1.7 m): on the square in front of the museum and on the ring street at view 49
random.seed(21)
bm_people = bmesh.new()
spots = [(random.uniform(-60, 60), random.uniform(6, 44)) for _ in range(45)] + \
        [(random.uniform(400, 470), ROADS[0] + random.choice((-5.5, 5.5)) + random.uniform(-1, 1)) for _ in range(18)]
for u, v in spots:
    if abs(u - mx) < 8 and v < 26:
        continue   # nobody directly in front of the camera of image 23
    a = a0 + u / R
    up = -Vector((math.cos(a), math.sin(a), 0))
    rot = up.to_track_quat("Z", "Y").to_matrix().to_4x4()
    foot = on_ring(u, v, 0)
    bmesh.ops.create_cone(bm_people, cap_ends=True, segments=8, radius1=0.25, radius2=0.2, depth=1.4,
                          matrix=Matrix.Translation(foot + up * 0.7) @ rot)
    bmesh.ops.create_uvsphere(bm_people, u_segments=8, v_segments=6, radius=0.14, matrix=Matrix.Translation(foot + up * 1.58))
mesh_object("Menschen", bm_people, solid("Mensch", (0.2, 0.3, 0.55), roughness=0.7), rotor)

# traffic: car of the tube railway, a ship approaching the hangar, one at the docking module, one further out
m_ship = solid("Schiff", (0.9, 0.9, 0.93), roughness=0.35, metallic=0.5)
m_engine = glow("Triebwerk", (0.4, 0.75, 1.0), 20.0)
bm_ship, bm_engine, bm_train = bmesh.new(), bmesh.new(), bmesh.new()


def ship(position, direction, length):
    """Simple ship: hull, bow, wings across, engine at the rear; direction points with the bow."""
    d = Vector(direction).normalized()
    rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    p = Vector(position)
    r = length / 9
    bmesh.ops.create_cone(bm_ship, cap_ends=True, segments=8, radius1=r, radius2=r, depth=length * 0.7, matrix=Matrix.Translation(p) @ rot)
    bmesh.ops.create_cone(bm_ship, cap_ends=True, segments=8, radius1=r, radius2=0, depth=length * 0.3,
                          matrix=Matrix.Translation(p + d * length * 0.5) @ rot)
    bmesh.ops.create_cube(bm_ship, size=1.0, matrix=Matrix.Translation(p - d * length * 0.1) @ rot @ Matrix.Diagonal((length * 0.7, r * 0.4, length * 0.25, 1)))
    bmesh.ops.create_cone(bm_engine, cap_ends=True, segments=8, radius1=r * 0.7, radius2=r * 0.7, depth=1.0,
                          matrix=Matrix.Translation(p - d * length * 0.36) @ rot)


hangar_centre = centroid("hangar")
if hangar_centre:
    hangar_depth = depths.get("hangar", 20.0)
    # Approach from the sun side: ships cannot pass through the spokes or the ring. (Earlier the ship came from below, from the
    # shadow side, and stood in the ascent like a torch above the ring.) Above the hangar, which now sits on the collector,
    # bow down into the hangar
    hangar_mid = 1.2 + hangar_depth / 2
    approach = Vector((hangar_centre.x * 0.95, hangar_centre.y * 0.95, hangar_mid + hangar_depth + 45))
    ship(approach, Vector((hangar_centre.x, hangar_centre.y, hangar_mid)) - approach, 36)
    print(f"Schiffe: Anflug von der Sonnenseite bei {tuple(round(c) for c in approach)}, Hangar Mitte "
          f"{tuple(round(c) for c in hangar_centre)} z {hangar_mid:.1f}, Kollektor r {COLLECTOR:.0f}", flush=True)
    hangar_x = [cell_xy(q, r)[0] for q, r in layout["modules"]["hangar"]]
    span = max(hangar_x) - min(hangar_x)
    for f in (0.2, 0.5, 0.8):   # three ships docked in the band, along the edge (length according to the depth of the hangar)
        ship(Vector((min(hangar_x) + span * f, hangar_centre.y, hangar_mid)), (1, 0, 0), min(30, span / 4))
    # second ship further up in the approach corridor (instead of in front of the docking module at the shadow-side end of the
    # axis, which came along the axis from the shadow side; ships must come from the sun side)
    ship(approach + (approach - Vector((hangar_centre.x, hangar_centre.y, hangar_mid))).normalized() * 110, Vector((hangar_centre.x, hangar_centre.y, hangar_mid)) - approach, 44)
ship((-420, -380, 260), (1, 0.9, -0.55), 30)   # further out, also from the sun side (earlier z -320, below the ring)
random.seed(3)
for q, r in random.sample(corridors, min(10, len(corridors))):
    for dq, dr in ((1, 0), (0, 1), (1, -1)):
        if (q + dq, r + dr) in corridor_set:
            p0, p1 = Vector((*cell_xy(q, r), -1.2 - STEP / 2)), Vector((*cell_xy(q + dq, r + dr), -1.2 - STEP / 2))
            rot = (p1 - p0).to_track_quat("Z", "Y").to_matrix().to_4x4()
            bmesh.ops.create_cone(bm_train, cap_ends=True, segments=10, radius1=0.75, radius2=0.75, depth=6.0,
                                  matrix=Matrix.Translation((p0 + p1) / 2) @ rot)
            break
mesh_object("Schiffe", bm_ship, m_ship)
mesh_object("Triebwerke", bm_engine, m_engine)
mesh_object("Wagen der Röhrenbahn", bm_train, glow("Wagen", (1.0, 0.75, 0.3), 4.0))

# Light of the mirrors in the ring: the mirrors stand still, so the band of light stands still too; here as area lights just
# below the glass roof shining outwards onto the floor. The mirrors tilt for day and night; without an option it is night
# (windows glow), with --day it is day, and the images are then named *_day.png
DAY = "--day" in ARGS
if DAY:
    for k in range(36):
        a = 2 * math.pi * k / 36
        radial = Vector((math.cos(a), math.sin(a), 0))
        lamp = bpy.data.lights.new(f"Lichtband {k}", "AREA")
        lamp.shape, lamp.size, lamp.size_y = "RECTANGLE", 2 * math.pi * (R - RIM) / 36 * 0.8, DEPTH * 0.55
        lamp.energy = float(CONFIG.get("light_band_watts", 25000))
        lamp.color = (1.0, 0.95, 0.85)
        obj = bpy.data.objects.new(f"Lichtband {k}", lamp)
        scene.collection.objects.link(obj)
        obj.location = radial * (R - RIM + 1.0) + Vector((0, 0, -DEPTH * 0.45))
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = (-radial).to_track_quat("Z", "Y")

sun = bpy.data.lights.new("Sonne", "SUN")
sun.energy = 4.0
sun_obj = bpy.data.objects.new("Sonne", sun)
scene.collection.objects.link(sun_obj)
sun_obj.rotation_euler = (math.radians(25), math.radians(-15), 0)   # oblique for readability; in reality the light falls along the axis

# ---------------------------------------------------------------- images along the ride
down = Vector((math.cos(spoke_angles[0]), math.sin(spoke_angles[0]), 0))
side = Vector((-down.y, down.x, 0))
walk = 110   # m on the ring floor in the direction of rotation beside the museum, eye height 1.7 m
to_axis = -Vector((math.cos(a0 + walk / R), math.sin(a0 + walk / R), 0))   # in the ring "up" is the direction to the axis
shots = [
    ("21_station_from_sun.png", (520, -760, 820), (0, 0, -60), 32, None),
    ("22_station_from_shadow.png", (640, 460, -820), (0, 0, -60), 32, None),
    ("23_ring_museum.png", on_ring(mx, 12, 1.7), on_ring(mx, my, 12), 16, -down),   # eye height in the middle of the square, looking straight towards the shadow side:
    # the floor rises equally on the left and right (valley), no tilted horizon
    ("24_spoke_halfway.png", down * 130 + side * 2.5 + Vector((0, 0, SPOKE_Z)), Vector((0, 0, SPOKE_Z)), 20, (0, 0, 1)),
    ("25_hub_transfer.png", Vector((30, -26, SPOKE_Z - 18)), Vector((0, 0, -5)), 16, None),
    ("26_hub_view_back.png", Vector((40, 170, -30)), Vector((-200, -150, SPOKE_Z)), 22, (0, 0, 1)),   # below the collector, clear of modules
    ("28_hub_modules_shadow.png", Vector((150, -260, -260)), Vector((0, -40, -40)), 28, None),   # honeycomb plan from behind, windows, distribution mirror
    # on the ring street (45 m towards the shadow side), looking in the direction of rotation: houses, trees, the floor rises in the distance
    ("49_ring_street.png", on_ring(400, ROADS[0], 1.7), on_ring(470, ROADS[0], 7.0), 18,
     -Vector((math.cos(a0 + 400 / R), math.sin(a0 + 400 / R), 0))),
    # at the edge of the fields (proposal) between spokes 3 and 4, looking in the direction of rotation across the fields
    ("51_ring_fields.png", on_ring(FARM[0] - 25, ROADS[0], 1.7), on_ring(FARM[0] + 70, ROADS[0], 8.0), 18,
     -Vector((math.cos(a0 + (FARM[0] - 25) / R), math.sin(a0 + (FARM[0] - 25) / R), 0))),
    # homes at the foot of spoke 2: terraces at the back wall, the spoke rises between the wings
    ("53_ring_homes_spoke.png", on_ring(spoke_alongs[2] - 90, 70, 20.0), on_ring(spoke_alongs[2], 125, 10.0), 22,
     -Vector((math.cos(a0 + (spoke_alongs[2] - 90) / R), math.sin(a0 + (spoke_alongs[2] - 90) / R), 0))),   # above the cross street, above the roofs
    # approach to the hangar from the shadow side, modules and map room behind
    ("50_hub_hangar_approach.png", Vector((70, -240, -300)), Vector((0, -170, -40)), 28, None),   # behind the ring, within its radius
]
# ---------------------------------------------------------------- storyboard: one still per panel
# With --storyboard the script renders only the panels from storyboard_station.yaml, with the placeholders (panels, boxes)
# that define the rooms; camera points in the systems ring, room, spoke, hub (see the head of the YAML file).
BOARD = json.loads(Path(CONFIG["storyboard_file"]).read_text(encoding="utf-8")) if CONFIG.get("storyboard_file") else None


def ring_dir(along, d_along, d_depth):
    """Direction in the ring at position along: d_along in the direction of rotation, d_depth towards the shadow side."""
    a = a0 + along / R
    return Vector((-math.sin(a), math.cos(a), 0)) * d_along + Vector((0, 0, -d_depth))


def room_point(room, s, r):
    """(along, depth, angle) of a point in room room: r from the middle of the museum, s on the circle in walking direction.
    s and r apply to scale 1 and are reduced with museum_scale."""
    s, r = s * S, r * S
    phi = math.radians(GATE_DEG - 60 * (room - 1)) - s / r   # room 1 on the side of the gate, anticlockwise with decreasing angle
    return mx + r * math.cos(phi), my + r * math.sin(phi), phi


def wall_point(room, x, d):
    """(along, depth, angle of the side normal) of a point on the flat inner wall of the room (side of the hexagon):
    x = m along the wall in walking direction from the middle of the wall, d = m in front of the wall into the room (exhibits
    sit on the flat inner side, so it can later be shown how everything is wired to the inner side)."""
    x, d = x * S, d * S
    phi0 = math.radians(GATE_DEG - 60 * (room - 1))
    inr = hall_r * math.cos(math.radians(30)) + d
    return mx + inr * math.cos(phi0) + x * math.sin(phi0), my + inr * math.sin(phi0) - x * math.cos(phi0), phi0


def hall_point(dx, dy):
    """(along, depth) of a point in the centre room: dx in the direction of rotation, dy towards the shadow side from the middle of the museum (scale 1)."""
    return mx + dx * S, my + dy * S


def board_point(spec, key, scale_height=True):
    """Point from a panel or a placeholder as a world coordinate, at frame; heights in the museum scale too, except for
    cameras (scale_height False: eye height stays)."""
    value, frame = spec[key], spec.get("frame", "ring")
    if frame == "ring":
        return on_ring(*value)
    if frame in ("room", "wall"):
        u, v, _ = (room_point if frame == "room" else wall_point)(spec["room"], value[0], value[1])
        return on_ring(u, v, value[2] * (S if scale_height else 1.0))
    if frame == "spoke":
        return down * value[0] + side * value[1] + Vector((0, 0, SPOKE_Z + value[2]))
    if frame == "hall":
        u, v = hall_point(value[0], value[1])
        return on_ring(u, v, value[2] * (S if scale_height else 1.0))
    point = centroid(value["module"]) + Vector(value.get("offset", (0, 0, 0))) if isinstance(value, dict) else Vector(value)
    return Matrix.Rotation(HUB_TURN, 4, "Z") @ point if frame == "hub" else point   # the hub stands turned by HUB_TURN (hub_root_object)


def axis_up(point):
    """In the ring, up points to the axis."""
    return -Vector((point.x, point.y, 0)).normalized()


def room_basis(room, s, r, h, facing="in", frame="room"):
    """Point and axes in the room: X to the right (for the viewer), Y up (towards the axis), Z towards the viewer.
    frame wall: (s, r) are (x, d) on the flat inner wall, the normal is that of the hexagon side."""
    u, v, phi = (room_point if frame == "room" else wall_point)(room, s, r)
    centre = on_ring(u, v, h)
    up = axis_up(centre)
    inward = ring_dir(u, -math.cos(phi), -math.sin(phi)).normalized()
    if facing in ("back", "ahead"):   # across the room: back towards whoever enters the room (against the walking direction), ahead in the walking direction
        normal = ring_dir(u, -math.sin(phi), math.cos(phi)).normalized() * (1 if facing == "back" else -1)   # (chair station)
    else:
        normal = inward if facing == "in" else -inward
    return centre, up.cross(normal).normalized(), up, normal


def hall_basis(item, h=0.0):
    """Point and axes in the centre room (frame hall): at = [dx, dy, ...] from the middle, facing_deg = direction of the normal in the plan
    (0 = in the direction of rotation, 90 = towards the shadow side, 270 = towards the sun side, i.e. towards the gate)."""
    u, v = hall_point(item["at"][0], item["at"][1])
    centre = on_ring(u, v, h)
    up = axis_up(centre)
    ang = math.radians(item.get("facing_deg", 270))
    normal = ring_dir(u, math.cos(ang), math.sin(ang)).normalized()
    return centre, up.cross(normal).normalized(), up, normal


def item_basis(item, h=0.0):
    """room_basis from a placeholder (frame room or wall, at = [s, r, ...] or [x, d, ...]; frame hall: hall_basis)."""
    if item.get("frame") == "hall":
        return hall_basis(item, h)
    return room_basis(item["room"], item["at"][0], item["at"][1], h, item.get("facing", "in"), item.get("frame", "room"))


def local_box(bm, origin, axes, centre, size):
    X, Y, Z = axes
    matrix = Matrix.Translation(origin + X * centre[0] + Y * centre[1] + Z * centre[2]) @ Matrix((X, Y, Z)).transposed().to_4x4()
    bmesh.ops.create_cube(bm, size=1.0, matrix=matrix @ Matrix.Diagonal((*size, 1)))


BOOK_COLOURS = [WKW["600"], WKW["800"], WKW["300"], (0.7913, 0.3467, 0.0), (0.66539, 0.11193, 0.0), (0.09306, 0.45641, 0.81485), (0.85, 0.8, 0.68)]


def shelves(item):
    """Row of shelves at the outer wall: units of `unit` m from s_from to s_to, each with six shelves of books."""
    room, (s_from, r, _), s_to = item["room"], item["at"], item["to"]
    unit, height = item.get("unit", 4.0), item.get("height", 3.2)
    bm_wood, bm_books = bmesh.new(), [bmesh.new() for _ in BOOK_COLOURS]
    rng = random.Random(item.get("seed", 11))
    s = s_from
    while s + unit <= s_to + 0.01:
        origin, X, Y, Z = room_basis(room, s + unit / 2, r, 0.0, item.get("facing", "in"), item.get("frame", "room"))
        axes = (X, Y, Z)
        local_box(bm_wood, origin, axes, (0, height / 2, -0.2), (unit, height, 0.04))   # back panel
        for side in (-1, 1):
            local_box(bm_wood, origin, axes, (side * unit / 2, height / 2, 0), (0.05, height, 0.42))
        for level in range(6):
            y = 0.08 + level * (height - 0.2) / 5.5
            local_box(bm_wood, origin, axes, (0, y, 0), (unit, 0.04, 0.42))
            if level == 5:
                continue
            x = -unit / 2 + 0.06
            while x < unit / 2 - 0.15:
                w, h = rng.uniform(0.05, 0.11), rng.uniform(0.24, 0.34)
                local_box(bm_books[rng.randrange(len(BOOK_COLOURS))], origin, axes, (x + w / 2, y + 0.02 + h / 2, 0), (w * 0.92, h, 0.3))
                x += w
        s += unit + 0.1
    mesh_object(f"Regale {item['id']}", bm_wood, solid("Regalholz", (0.42, 0.3, 0.2), roughness=0.7), rotor)
    for i, bm_b in enumerate(bm_books):
        mesh_object(f"Bücher {item['id']} {i}", bm_b, solid(f"Buchrücken {i}", BOOK_COLOURS[i], roughness=0.6), rotor)


def image_plane(name, image_path, origin, X, Y, size):
    bpy.ops.mesh.primitive_plane_add(size=2)
    plane = bpy.context.active_object
    plane.name = name
    plane.matrix_world = Matrix.Translation(origin) @ Matrix((X, Y, X.cross(Y))).transposed().to_4x4() @ Matrix.Diagonal((size[0] / 2, size[1] / 2, 1, 1))
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    tex, emit, out = nodes.new("ShaderNodeTexImage"), nodes.new("ShaderNodeEmission"), nodes.new("ShaderNodeOutputMaterial")
    tex.image = bpy.data.images.load(image_path)
    links.new(tex.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs[0], out.inputs["Surface"])
    plane.data.materials.append(mat)
    return plane


def lectern(item):
    """Lectern with an open book: column, sloping top, two pages; the right page as an image.
    base: table puts the book on a reading table instead of the lectern (so the same table does not repeat everywhere);
    thickness makes the book block thick (the book of words in room 6 is printed correspondingly thick)."""
    origin, X, up, normal = item_basis(item)
    on_table = item.get("base") == "table"
    t = math.radians(item.get("tilt", 8 if on_table else 22))
    n_s = (up * math.cos(t) + normal * math.sin(t)).normalized()   # surface of the top
    d = (normal * math.cos(t) - up * math.sin(t)).normalized()     # in the top towards the viewer, downwards
    if item.get("thickness") == "prompts":   # height from the counted prompts (sheets * 0.1 mm), grows with every
        numbers = json.loads((BASE / "_scratch" / "storyboard" / "making_of" / "numbers.json").read_text(encoding="utf-8"))   # count
        thick = numbers["prompts_all"]["sheets"] * 0.0001   # (the stack has to grow as more prompts are given,
    else:                                                    # not stay at a fixed number)
        thick = float(item.get("thickness", 0.05))
    bm = bmesh.new()
    if on_table:   # reading table 1.6 x 0.9 m, top at 0.78 m, four legs; on it a flat book rest so that the book tilts towards the viewer
        for sx in (-0.72, 0.72):
            for sz in (-0.36, 0.36):
                local_box(bm, origin, (X, up, normal), (sx, 0.38, sz), (0.06, 0.76, 0.06))
        local_box(bm, origin, (X, up, normal), (0, 0.765, 0), (1.6, 0.03, 0.9))
        if item.get("stack"):   # stack of paper instead of a book, with a cover sheet showing "Prompts:"
            # and the total number of words; thickness = height of the stack,
            # the cover sheet (image) on top, flat on the table
            mesh_object(f"Pult {item['id']}", bm, solid("Tischholz", (0.48, 0.34, 0.22), roughness=0.6), rotor)
            # continuous form paper in portrait orientation: it runs endlessly from top to bottom, not from left to right; sheet =
            # [width across, sheet length in running direction], sprocket margins left and right, the paper runs away from the viewer;
            # the stack of layers with alternating offset shows the fold edges
            sheet = item.get("sheet", [0.241, 0.279])
            layers = max(6, min(40, int(thick / 0.0008)))
            bm_stack = bmesh.new()
            for k in range(layers):
                shift = 0.0015 * (1 if k % 2 else -1)   # fold edges alternate front and back
                local_box(bm_stack, origin, (X, up, normal), (0, 0.78 + (k + 0.5) * thick / layers, shift), (sheet[0], thick / layers * 0.92, sheet[1]))
            mesh_object(f"Papierstapel {item['id']}", bm_stack, solid("Papierkante", (0.93, 0.92, 0.88), roughness=0.95), rotor)
            top_h = 0.78 + thick
            if item.get("image"):
                image_plane(f"Deckblatt {item['id']}", item["image"], origin + up * (top_h + 0.002), X, -normal, tuple(sheet))
            if item.get("fanfold"):   # the web rises from the stack at the rear edge, arches, runs over the rear edge of the table
                # down and folds on the floor; printed with the empty stripe pattern
                strip = str(BASE / item["fanfold"])   # the launcher resolves only known image fields, not this one
                back = -sheet[1] / 2
                path = [(back - 0.12 * (1 - math.cos(a)), top_h + 0.002 + 0.14 * math.sin(a)) for a in
                        [math.pi * k / 8 for k in range(9)]]   # arch: up and back onto the table
                path += [(-0.45, 0.782), (-0.453, 0.45), (-0.47, 0.05)]   # rear edge of the table (table 0.9 m deep), down to the floor
                for k, ((n0, h0), (n1, h1)) in enumerate(zip(path, path[1:])):
                    a, b = origin + normal * n0 + up * h0, origin + normal * n1 + up * h1
                    if (b - a).length > 1e-4:
                        image_plane(f"Endlosbahn {k} {item['id']}", strip, (a + b) / 2, X, (a - b).normalized(), (sheet[0], (b - a).length))
                bm_pile = bmesh.new()   # folded web on the floor behind the table
                for k in range(6):
                    local_box(bm_pile, origin, (X, up, normal), (0.004 * (k % 2), 0.005 + k * 0.01, -0.6), (sheet[0], 0.008, sheet[1]))
                mesh_object(f"Endlosbahn Boden {item['id']}", bm_pile, solid("Papierkante", (0.93, 0.92, 0.88), roughness=0.95), rotor)
            return
        top = origin + up * (0.8 + 0.33 * math.sin(t))
        local_box(bm, top, (X, n_s, d), (0, -0.02, 0), (1.0, 0.03, 0.7))
    else:
        local_box(bm, origin, (X, up, normal), (0, 0.55, 0), (0.3, 1.1, 0.3))
        local_box(bm, origin, (X, up, normal), (0, 0.03, 0), (0.7, 0.06, 0.5))
        top = origin + up * 1.18
        local_box(bm, top, (X, n_s, d), (0, 0, 0), (1.05, 0.05, 0.75))
    mesh_object(f"Pult {item['id']}", bm, solid("Tischholz" if on_table else "Pultholz", (0.48, 0.34, 0.22) if on_table else (0.36, 0.25, 0.17),
                                                roughness=0.6), rotor)
    page = (0.42, 0.63)   # 2:3 like the generated book pages
    lift = n_s * (thick + 0.01)   # 1 cm above the book block, otherwise the block covers the pages
    # pages meet at the fold, block and cover lie entirely below, so the book does not look like a screenshot with a white
    # frame or show a cover in the middle; before there was a 1 cm gap at the fold and a light block of 1 to 1.5 cm all round
    half = page[0] / 2
    left = image_plane(f"Buchseite links {item['id']}", item["left"], top + lift - X * half, X, -d, page) if item.get("left") else None
    if left is None:
        bm_page = bmesh.new()
        local_box(bm_page, top + lift - X * half, (X, n_s, d), (0, 0, 0), (page[0], 0.01, page[1]))
        mesh_object(f"Buchseite links {item['id']}", bm_page, solid("Papier", (0.93, 0.9, 0.82), roughness=0.9), rotor)
    right = image_plane(f"Buchseite rechts {item['id']}", item["image"], top + lift + X * half, X, -d, page) if item.get("image") else None
    BOOK[item["id"]] = (left, right)   # for panels that open a different double page (field book); "pages" is the first
    BOOK.setdefault("pages", (left, right))   # lectern (room 5): since there is a second one (room 6), the book of that one turned the page otherwise
    BOOK_GEOM[item["id"]] = (top + lift, X, d, n_s, page)   # fold, axes and page size for the sheet that turns during the ride
    BOOK_GEOM.setdefault("pages", BOOK_GEOM[item["id"]])
    bm_block = bmesh.new()   # book block and cover below the pages: thickness visible, red leather
    local_box(bm_block, top + n_s * (thick / 2), (X, n_s, d), (0, 0, 0), (2 * page[0] - 0.01, thick, page[1] - 0.01))
    mesh_object(f"Buchblock {item['id']}", bm_block, solid("Seitenschnitt", (0.86, 0.8, 0.66), roughness=0.8), rotor)
    bm_cover = bmesh.new()
    local_box(bm_cover, top - n_s * 0.005, (X, n_s, d), (0, 0, 0), (2 * page[0] - 0.01, 0.02, page[1] - 0.01))
    mesh_object(f"Einband {item['id']}", bm_cover, solid("Leder", (0.36, 0.06, 0.05), roughness=0.55), rotor)


BOOK = {}
BOOK_GEOM = {}


def open_book(paths, lectern=None):
    """Opens a different double page in the book on the lectern: swap the images of the two page faces (lectern: identifier of
    the lectern, otherwise the first one)."""
    for plane, path in zip(BOOK.get(lectern or "pages", ()), paths):
        if plane is None:
            continue
        for node in plane.data.materials[0].node_tree.nodes:
            if node.type == "TEX_IMAGE":
                node.image = bpy.data.images.load(path, check_existing=True)


def flat(item):
    """Stage set seen from behind (making-of): battens, rails, brace, prop to the floor; the painted side faces away."""
    origin, X, up, normal = item_basis(item)
    w, h = item["size"]
    axes = (X, up, normal)
    bm_wood, bm_skin = bmesh.new(), bmesh.new()
    for side in (-1, 1):
        local_box(bm_wood, origin, axes, (side * (w / 2 - 0.05), h / 2, 0), (0.1, h, 0.06))
    for y in (0.05, h / 2, h - 0.05):
        local_box(bm_wood, origin, axes, (0, y, 0), (w, 0.1, 0.06))
    diag = Vector((w - 0.2, h / 2 - 0.1, 0))
    rot = Matrix.Rotation(math.atan2(diag.y, diag.x), 4, "Z")
    for y0 in (0.05, h / 2):   # braces in both fields
        centre = origin + X * 0 + up * (y0 + (h / 2 - 0.1) / 2)
        matrix = Matrix.Translation(centre) @ Matrix((X, up, normal)).transposed().to_4x4() @ rot @ Matrix.Diagonal((diag.length, 0.08, 0.05, 1))
        bmesh.ops.create_cube(bm_wood, size=1.0, matrix=matrix)
    for side in (-1, 1):   # props slanting to the floor, weight at the foot
        base = origin + X * side * (w / 3) + normal * 1.6
        top_pt = origin + X * side * (w / 3) + up * (h * 0.7)
        rods(bm_wood, [base, top_pt], 0.04)
        local_box(bm_wood, base, axes, (0, 0.12, 0), (0.4, 0.24, 0.25))
    local_box(bm_skin, origin, axes, (0, h / 2, -0.06), (w, h, 0.02))
    mesh_object(f"Kulisse {item['id']}", bm_wood, solid("Latten", (0.62, 0.47, 0.3), roughness=0.8), rotor)
    mesh_object(f"Kulissenhaut {item['id']}", bm_skin, solid("Sperrholz Rückseite", (0.72, 0.62, 0.46), roughness=0.9), rotor)


THREAD_SOURCES = []   # (u, v, h) behind the exhibits at the inner wall: the threads to the cabin start there (scene 7)
m_back = solid("Exponatrückseite", (0.16, 0.16, 0.17), roughness=0.8)
m_cable = solid("Kabel", (0.05, 0.05, 0.06), roughness=0.9)


def cutout(item):
    """Borgi as a cut-out (assets_3d: image plane with alpha), stands on the floor, image top towards the axis; facing as for the panels."""
    origin, X, up, normal = item_basis(item)
    height = item.get("height", 1.6)
    path = item["image"]
    img = bpy.data.images.load(path, check_existing=True)
    width = height * img.size[0] / img.size[1]
    bpy.ops.mesh.primitive_plane_add(size=2)
    plane = bpy.context.active_object
    plane.name = f"Borgi {item['id']}"
    plane.matrix_world = Matrix.Translation(origin + up * height / 2) @ Matrix((X, up, normal)).transposed().to_4x4() @ Matrix.Diagonal((width / 2, height / 2, 1, 1))
    mat = bpy.data.materials.new(f"Borgi {item['id']}")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()   # emissive like the panels, not lit: as a vertical surface under the ceiling light the cut-out stood
    tex, emit, out = nodes.new("ShaderNodeTexImage"), nodes.new("ShaderNodeEmission"), nodes.new("ShaderNodeOutputMaterial")
    transparent, mix = nodes.new("ShaderNodeBsdfTransparent"), nodes.new("ShaderNodeMixShader")   # in shadow otherwise
    tex.image = img   # (the Borgis looked completely shaded)
    links.new(tex.outputs["Color"], emit.inputs["Color"])
    links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(emit.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    mat.surface_render_method = "DITHERED"
    mat.use_backface_culling = False
    plane.data.materials.append(mat)
    # cardboard cut-out with thickness, so the Borgis look more three-dimensional: behind the image side, layers of the
    # silhouette in white card, lit, so the edge shows light and shade; at the very back the rear side and a slanted prop
    thick = float(item.get("thickness", 0.025))
    card = bpy.data.materials.new(f"Borgi Pappe {item['id']}")
    card.use_nodes = True
    c_nodes, c_links = card.node_tree.nodes, card.node_tree.links
    c_nodes.clear()
    c_tex, diffuse, c_transparent, c_mix, c_out = (c_nodes.new(t) for t in ("ShaderNodeTexImage", "ShaderNodeBsdfDiffuse",
                                                                             "ShaderNodeBsdfTransparent", "ShaderNodeMixShader", "ShaderNodeOutputMaterial"))
    c_tex.image = img
    # white like the rim of the Borgis (rim measured as sRGB 252/251/251); before, cardboard brown
    diffuse.inputs["Color"].default_value = (0.973, 0.965, 0.965, 1.0)
    cut = c_nodes.new("ShaderNodeMath")   # hard edge: the soft glow around Borgi and punctuation made a grey
    cut.operation, cut.inputs[1].default_value = "GREATER_THAN", 0.5   # cloud of dots across ten layers (still 05.1)
    c_links.new(c_tex.outputs["Alpha"], cut.inputs[0])
    c_links.new(cut.outputs[0], c_mix.inputs["Fac"])
    c_links.new(c_transparent.outputs[0], c_mix.inputs[1])
    c_links.new(diffuse.outputs[0], c_mix.inputs[2])
    c_links.new(c_mix.outputs[0], c_out.inputs["Surface"])
    card.surface_render_method = "DITHERED"
    card.use_backface_culling = False
    layers = 10
    for k in range(1, layers + 1):
        layer = plane.copy()
        layer.data = plane.data.copy()
        layer.data.materials.clear()
        layer.data.materials.append(card)
        layer.name = f"Borgi Pappe {k} {item['id']}"
        layer.matrix_world = Matrix.Translation(-normal * thick * k / layers) @ plane.matrix_world
        for collection in plane.users_collection:
            collection.objects.link(layer)
        if plane.parent:
            layer.parent, layer.matrix_parent_inverse = plane.parent, plane.matrix_parent_inverse.copy()
    bm_strut = bmesh.new()   # prop at the back, slanting to the floor
    rods(bm_strut, [origin + up * height * 0.55 - normal * thick, origin - normal * (thick + height * 0.3)], 0.012)
    mesh_object(f"Stütze {item['id']}", bm_strut, solid("Pappe Stütze", (0.973, 0.965, 0.965), roughness=0.9), rotor)
    bm = bmesh.new()   # base
    local_box(bm, origin, (X, up, normal), (0, 0.01, 0), (width * 0.6, 0.02, 0.4))
    mesh_object(f"Fuß {item['id']}", bm, m_back, rotor)


def table(item):
    """Round table with stools (discussion corners): top 1.2 m, column, four stools."""
    origin, X, up, normal = item_basis(item)
    bm_wood, bm_metal = bmesh.new(), bmesh.new()
    radius = item.get("radius", 0.6)
    bmesh.ops.create_cone(bm_wood, cap_ends=True, segments=32, radius1=radius, radius2=radius, depth=0.04,
                          matrix=Matrix.Translation(origin + up * 0.74) @ up.to_track_quat("Z", "Y").to_matrix().to_4x4())
    rods(bm_metal, [origin + up * 0.02, origin + up * 0.72], 0.05)
    bmesh.ops.create_cone(bm_metal, cap_ends=True, segments=24, radius1=0.35, radius2=0.35, depth=0.03,
                          matrix=Matrix.Translation(origin + up * 0.015) @ up.to_track_quat("Z", "Y").to_matrix().to_4x4())
    for k in range(item.get("seats", 4)):
        a = 2 * math.pi * k / item.get("seats", 4) + math.radians(item.get("turn", 0))
        seat = origin + (X * math.cos(a) + normal * math.sin(a)) * (radius + 0.45)
        bmesh.ops.create_cone(bm_wood, cap_ends=True, segments=20, radius1=0.2, radius2=0.2, depth=0.05,
                              matrix=Matrix.Translation(seat + up * 0.45) @ up.to_track_quat("Z", "Y").to_matrix().to_4x4())
        rods(bm_metal, [seat + up * 0.02, seat + up * 0.43], 0.03)
    mesh_object(f"Tisch {item['id']}", bm_wood, solid("Tischholz", (0.55, 0.4, 0.26), roughness=0.6), rotor)
    mesh_object(f"Tischgestell {item['id']}", bm_metal, m_back, rotor)


def armchair(item):
    """Armchair (seating corners for a library feel): seat, back, two armrests, house colour."""
    origin, X, up, normal = item_basis(item)
    bm = bmesh.new()
    axes = (X, up, normal)
    local_box(bm, origin, axes, (0, 0.22, 0), (0.9, 0.44, 0.9))
    local_box(bm, origin, axes, (0, 0.6, -0.36), (0.9, 0.76, 0.18))
    for side in (-1, 1):
        local_box(bm, origin, axes, (side * 0.4, 0.5, 0.05), (0.1, 0.56, 0.8))
    mesh_object(f"Sessel {item['id']}", bm, solid("Sesselstoff", WKW["700"], roughness=0.9), rotor)


def tilted_box(bm, origin, axes, centre, size, tilt=0.0, yaw=0.0):
    """Box like local_box, but tilted about its own transverse axis (tilt in degrees, positive: top towards the viewer, i.e. towards +Z)
    and turned about the vertical axis (yaw in degrees); centre in the unrotated axes."""
    X, Y, Z = axes
    c, s_ = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    Xr, Zr = X * c - Z * s_, X * s_ + Z * c
    ct, st = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
    Yt, Zt = Y * ct + Zr * st, -Y * st + Zr * ct
    local_box(bm, origin + X * centre[0] + Y * centre[1] + Z * centre[2], (Xr, Yt, Zt), (0, 0, 0), size)


def station_chair(item):
    """Chair station rebuilt from the video "Hyperoptimized Engineer 2026", with the videos playing on its screens: red reclining
    chair on a base, foot rest, black desk top above the lap, behind the chair a mast with a boom carrying three screens in an
    arc in front of the face, tilted towards the seated person. The seated person looks towards +Z (normal); images: left
    (AI window), image (middle, the video), right (terminal)."""
    # Second version after the still at 1:38, matching the chair in the screenshot exactly:
    # chair reclined far back, red frames around dark cushions, large tilted desk top with a red trackball and keypad, an arm
    # from the floor in front of the chair carries the desk top and the screens, the screens hang high and steeply tilted above the top.
    origin, X, up, normal = item_basis(item)
    axes = (X, up, normal)
    red = solid("Sesselrahmen rot", (0.6, 0.02, 0.02), roughness=0.45)
    pad, dark = solid("Sesselpolster", (0.12, 0.02, 0.02), roughness=0.8), solid("Station dunkel", (0.02, 0.02, 0.025), roughness=0.4)
    bm_red, bm_pad, bm_dark, bm_ball = bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new()

    def framed(centre, width, length, thick, tilt):
        """Cushion with a red frame; the length runs along the tilted vertical axis (tilt in degrees as in tilted_box)."""
        t = math.radians(tilt)
        along = (0, math.cos(t) * length / 2, math.sin(t) * length / 2)
        tilted_box(bm_pad, origin, axes, centre, (width - 0.1, length - 0.1, thick), tilt=tilt)
        for side in (-1, 1):
            tilted_box(bm_red, origin, axes, (centre[0] + side * (width / 2 - 0.035), centre[1], centre[2]), (0.07, length, thick + 0.05), tilt=tilt)
            tilted_box(bm_red, origin, axes, tuple(c + side * a for c, a in zip(centre, along)), (width, 0.07, thick + 0.05), tilt=tilt)

    local_box(bm_dark, origin, axes, (0, 0.13, -0.1), (0.5, 0.26, 0.6))              # base
    framed((0, 0.5, 0.02), 0.62, 0.56, 0.1, 78)                                       # seat, nearly horizontal, higher at the front
    framed((0, 0.84, -0.6), 0.62, 0.95, 0.1, -52)                                     # back, reclined 52°
    framed((0, 1.17, -1.1), 0.42, 0.26, 0.12, -52)                                    # headrest at the upper end of the back
    framed((0, 0.45, 0.52), 0.56, 0.5, 0.08, 115)                                     # foot rest, sloping down at the front
    for side in (-1, 1):
        local_box(bm_red, origin, axes, (side * 0.36, 0.66, -0.1), (0.07, 0.07, 0.55))   # armrests
    desk = (0, 0.98, 0.62)                                                            # desk top above the lap, towards the reclining person
    tilted_box(bm_dark, origin, axes, desk, (1.0, 0.035, 0.66), tilt=-24)             # tilted (lower at the front)
    t = math.radians(-24)
    desk_point = lambda dx, dz: origin + X * dx + up * (desk[1] - math.sin(t) * dz + math.cos(t) * 0.03) + normal * (desk[2] + math.cos(t) * dz)
    bmesh.ops.create_uvsphere(bm_ball, u_segments=20, v_segments=10, radius=0.045, matrix=Matrix.Translation(desk_point(0.05, 0.24)))
    keys = bmesh.new()   # keypad on the right of the top (glowing keys)
    local_box(keys, desk_point(-0.3, 0.05), axes, (0, 0.02, 0), (0.13, 0.04, 0.1))
    mesh_object(f"Stuhlstation Tastenfeld {item['id']}", keys, solid("Tastenfeld", (0.25, 0.55, 0.95), roughness=0.3, emission=2.0), rotor)
    foot = origin + normal * 1.05 + X * 0.15
    rods(bm_dark, [foot, foot + up * 0.75, desk_point(0.15, 0.25)], 0.05)            # arm from the floor to the top
    eye = origin + up * 1.22 - normal * 0.95                                         # head of the reclining person at the headrest
    gaze_up = math.radians(item.get("gaze_up", 28))                                   # looking obliquely upwards (38° hung the
    # screens above 2.4 m; in the still they hang just above the desk top)
    # Node of the arm behind all three screens, so the screen mount comes from behind and does not clip through the middle
    # screen: it used to lie at normal 0.95, up 1.75, i.e. in front of the right screen and only just behind the middle one;
    # the rod to the right screen ran across the middle and hit the right one from the front
    gaze_mid = (normal * math.cos(gaze_up) + up * math.sin(gaze_up)).normalized()
    hub = eye + gaze_mid * 2.15
    rods(bm_dark, [desk_point(0.15, 0.3), hub], 0.045)                                # further up to the screens
    sizes = {"left": (0.56, 0.95), "image": (1.05, 0.6), "right": (1.0, 0.58)}       # left in portrait, middle and right in landscape
    # right 48 instead of 42 degrees: seen from the walking path the right screen covered the top right corner of the video in the middle
    for key, yaw, dist in (("left", 42, 1.45), ("image", 0, 1.6), ("right", -48, 1.5)):
        w, h = sizes[key]
        a = math.radians(yaw)
        flat = (normal * math.cos(a) + X * math.sin(a)).normalized()               # yaw > 0: to the left of the reclining person (he looks towards
        direction = (flat * math.cos(gaze_up) + up * math.sin(gaze_up)).normalized()   # +normal, his right is -X)
        centre = eye + direction * dist
        face = (eye - centre).normalized()                                           # screen faces the head, steeply tilted
        Xs = up.cross(face).normalized()
        Ys = face.cross(Xs).normalized()
        bpy_box = bmesh.new()
        local_box(bpy_box, centre - face * 0.03, (Xs, Ys, face), (0, 0, 0), (w + 0.04, h + 0.04, 0.04))
        mesh_object(f"Bildschirmrahmen {key} {item['id']}", bpy_box, dark, rotor)
        rods(bm_dark, [hub, centre - face * 0.3, centre - face * 0.05], 0.025)   # bracket behind the screen, never through it
        if item.get(key):
            # screen with video: named like a placeholder, so the ride plays the clip on it as in room 3;
            # video_screen chooses it (default the middle; the middle one sat in an awkward place behind the
            # right screen)
            on_video = key == item.get("video_screen", "image") and item.get("video")
            name = f"Platzhalter {item['id']}" if on_video else f"Bildschirm {key} {item['id']}"
            image_plane(name, item[key], centre + face * 0.001, Xs, Ys, (w, h))   # -Xs mirrored the image
    mesh_object(f"Stuhlstation Sessel {item['id']}", bm_red, red, rotor)
    mesh_object(f"Stuhlstation Polster {item['id']}", bm_pad, pad, rotor)
    mesh_object(f"Stuhlstation Gestell {item['id']}", bm_dark, dark, rotor)
    mesh_object(f"Stuhlstation Trackball {item['id']}", bm_ball, solid("Trackball rot", (0.75, 0.02, 0.02), roughness=0.2), rotor)


def tablet(item):
    """Tablet on a table, on which the video plays:
    at = [x, d, h] with h = table height, size at human scale (default 0.26 x 0.18 m), stands at 70° on a small foot."""
    origin, X, up, normal = item_basis(item)
    if item.get("face_toward"):   # [s, r] in the same room: turn towards it, so the tablet faces
        # the visitor a little more
        target = board_point({"frame": "room", "room": item["room"], "at": [*item["face_toward"][:2], 0.0]}, "at")
        flat = target - origin
        flat -= up * flat.dot(up)
        normal = flat.normalized()
        X = up.cross(normal).normalized()
    w, h_ = item.get("size", [0.26, 0.18])
    t = math.radians(item.get("tilt", 70))
    y = (up * math.sin(t) - normal * math.cos(t)).normalized()
    n_s = (up * math.cos(t) + normal * math.sin(t)).normalized()
    centre = origin + up * (item["at"][2] + 0.01) + y * h_ / 2
    bm = bmesh.new()
    local_box(bm, centre - n_s * 0.006, (X, y, n_s), (0, 0, 0), (w + 0.02, h_ + 0.02, 0.008))
    local_box(bm, origin + up * item["at"][2] - normal * 0.05, (X, up, normal), (0, 0.005, 0), (0.08, 0.01, 0.1))
    mesh_object(f"Tablet {item['id']}", bm, solid("Station dunkel", (0.02, 0.02, 0.025), roughness=0.4), rotor)
    if item.get("image"):
        # with video the image is named like a placeholder, so the ride plays the clip on it
        name = f"Platzhalter {item['id']}" if item.get("video") else f"Tablet Bild {item['id']}"
        image_plane(name, item["image"], centre + n_s * 0.0005, X, y, (w, h_))


def rollup(item):
    """Roll-up banner standing in the way: foot,
    pole, banner 0.85 x 2 m with an image or text; stands free in the room, the ride goes around it."""
    origin, X, up, normal = item_basis(item)
    if item.get("facing") == "back":   # across the room, towards whoever enters: the same normal as the panel (room_basis only knows in/out)
        u, v, phi = (room_point if item.get("frame", "room") == "room" else wall_point)(item["room"], *item["at"][:2])
        normal = ring_dir(u, -math.sin(phi), math.cos(phi)).normalized()
        X = up.cross(normal).normalized()
    w, h = item.get("size", [0.85, 2.0])
    bm = bmesh.new()
    local_box(bm, origin, (X, up, normal), (0, 0.04, 0), (w + 0.1, 0.08, 0.3))
    rods(bm, [origin + up * 0.08 - normal * 0.03, origin + up * (h + 0.12) - normal * 0.03], 0.015)
    mesh_object(f"Aufsteller {item['id']}", bm, m_back, rotor)
    board = dict(item, kind="board", size=[w, h], no_back=True, no_scale=True)   # human size, even with a small museum
    board["at"] = [item["at"][0], item["at"][1], (0.1 + h / 2) / S]
    placeholder(board, 900 + len(THREAD_SOURCES))


def divider(item):
    """Room divider that the ride circles once, much larger than a roll-up: free-standing wall at human size (size, default
    3.4 x 2.2 m) on two feet, the image in front (image, towards whoever enters), the second image behind (back_image); facing
    as for rollup."""
    origin, X, up, normal = item_basis(item)
    if item.get("facing") == "back":
        u, v, phi = (room_point if item.get("frame", "room") == "room" else wall_point)(item["room"], *item["at"][:2])
        normal = ring_dir(u, -math.sin(phi), math.cos(phi)).normalized()
        X = up.cross(normal).normalized()
    w, h = item.get("size", [3.4, 2.2])
    bm = bmesh.new()
    local_box(bm, origin, (X, up, normal), (0, 0.1 + h / 2, 0), (w, h, 0.08))
    for side in (-1, 1):
        local_box(bm, origin, (X, up, normal), (side * w / 3, 0.05, 0), (0.5, 0.1, 0.7))
    mesh_object(f"Raumteiler Körper {item['id']}", bm, m_back, rotor)
    middle = origin + up * (0.1 + h / 2)
    if item.get("image"):
        image_plane(f"Raumteiler {item['id']}", item["image"], middle + normal * 0.045, X, up, (w, h))
    if item.get("back_image"):
        image_plane(f"Raumteiler Rückseite {item['id']}", item["back_image"], middle - normal * 0.045, -X, up, (w, h))


def easel(item):
    """Easel with a board at human size (making-of in the centre room, frame hall): board 0.9 m above the floor, two legs at the
    front, two slanting backwards."""
    origin, X, up, normal = item_basis(item)
    w, h = item["size"]
    board = dict(item, kind="board", no_back=True, no_scale=True, backing=True)
    board["at"] = [item["at"][0], item["at"][1], (0.9 + h / 2) / S]
    placeholder(board, 800 + len(THREAD_SOURCES))
    # Like a board easel, with wooden edges in proportion to the board: wooden frame
    # exactly around the board, a ledge below, two legs as an A-frame meeting in the middle above the board, a support leg at the back
    bm = bmesh.new()
    axes, bottom, frame = (X, up, normal), 0.9, 0.07
    for x, y, sx, sy in ((0, bottom - frame / 2, w + 2 * frame, frame), (0, bottom + h + frame / 2, w + 2 * frame, frame),
                         (-(w + frame) / 2, bottom + h / 2, frame, h), ((w + frame) / 2, bottom + h / 2, frame, h)):
        local_box(bm, origin, axes, (x, y, -0.02), (sx, sy, 0.05))   # frame, behind the image surface
    local_box(bm, origin, axes, (0, bottom - frame - 0.02, 0.06), (w + 0.2, 0.04, 0.16))   # ledge below the board
    apex = origin + up * (bottom + h + 0.25) - normal * 0.06
    for side in (-1, 1):
        rods(bm, [origin + X * side * (w / 2 + frame + 0.08) - normal * 0.08, apex], 0.035)   # behind the board, never in front of it
    rods(bm, [apex, origin - normal * (0.5 + 0.25 * h)], 0.035)
    mesh_object(f"Staffelei {item['id']}", bm, solid("Staffeleiholz", (0.5, 0.36, 0.22), roughness=0.7), rotor)


def plate(item):
    """Reading desk in front of the exhibit, slightly angled as in a museum, so one stands in front of it and reads: tilted
    top with the image of the information panel on two legs; at = [x, d, h] (h = upper front edge),
    tilt in degrees from the horizontal (default 25), size at human scale (does not scale)."""
    origin, X, up, normal = item_basis(item)
    w, d_ = item.get("size", [1.7, 1.0])
    t = math.radians(item.get("tilt", 25))
    h = item["at"][2]
    y = (up * math.sin(t) - normal * math.cos(t)).normalized()   # image top: away from the viewer and upwards
    n_s = (up * math.cos(t) + normal * math.sin(t)).normalized()
    centre = origin + up * h + y * d_ / 2
    if item.get("image"):
        image_plane(f"Lesepult {item['id']}", item["image"], centre, X, y, (w, d_))
    bm = bmesh.new()
    local_box(bm, centre - n_s * 0.03, (X, y, n_s), (0, 0, 0), (w + 0.06, d_ + 0.06, 0.04))   # top below the image
    if item.get("pedestal"):   # solid base instead of legs, for a proper slope: solid from the floor
        back = -normal * d_ * math.cos(t)   # to below the top, h high at the front, at the back as high as the rear edge
        points = [origin + X * side * (w / 2) + depth + up * height
                  for side in (-1, 1) for depth, height in ((Vector(), 0.0), (Vector(), h - 0.05), (back, 0.0), (back, h + d_ * math.sin(t) - 0.05))]
        bm_p = bmesh.new()
        verts = [bm_p.verts.new(p) for p in points]
        bmesh.ops.convex_hull(bm_p, input=verts)
        # base anthracite instead of WKW 800: that did not stand out from the green floor
        mesh_object(f"Lesepultgestell {item['id']}", bm_p, solid("Pultsockel", (0.05, 0.05, 0.055), roughness=0.6), rotor)
        mesh_object(f"Lesepultplatte {item['id']}", bm, m_back, rotor)
        return
    for side in (-1, 1):   # legs front and back
        for along_y, hh in ((0.0, h), (d_, h + d_ * math.sin(t))):
            foot_pt = origin + X * side * (w / 2 - 0.08) - normal * along_y * math.cos(t)
            rods(bm, [foot_pt, foot_pt + up * (hh - 0.02)], 0.025)
    mesh_object(f"Lesepultgestell {item['id']}", bm, m_back, rotor)


LINEN = BASE / "media" / "polyhaven" / "rough_linen"   # Poly Haven, CC0


def fabric_banner(item, centre, X, Y, normal, w, h):
    """Banner as a length of fabric, so it does not look like a television hanging above: matt fabric without frame or backing
    board, vertical folds (depth 4.5 cm, every 0.6 m), swinging slightly forward at the bottom, linen weave from Poly Haven;
    at the top on a rod with end knobs that sits on two brackets to the wall (wall_gap m behind the fabric). The image stays
    slightly emissive, otherwise it is too dark in the room light."""
    cols, rows, depth, wave = 60, 10, 0.045, 0.6
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new()
    grid = []
    for j in range(rows + 1):
        t = j / rows   # 0 at the bottom, 1 at the top
        line = []
        for i in range(cols + 1):
            s = i / cols
            fold = depth * math.sin(2 * math.pi * (s * w) / wave) * (0.4 + 0.6 * (1 - t))   # smoother at the top near the rod
            line.append(bm.verts.new(centre + X * (s - 0.5) * w + Y * (t - 0.5) * h + normal * (fold + 0.02 * (1 - t) ** 2)))
        grid.append(line)
    for j in range(rows):
        for i in range(cols):
            face = bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
            for loop, (a, b) in zip(face.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                loop[uv].uv = (a / cols, b / rows)
    obj = mesh_object(f"Platzhalter {item['id']}", bm, None, rotor)
    obj.data.materials.clear()
    for poly in obj.data.polygons:
        poly.use_smooth = True
    mat = bpy.data.materials.new(f"Banner Stoff {item['id']}")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(item["image"], check_existing=True)
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = float(item.get("glow", 0.2))   # 0.35 washed out the folds
    bsdf.inputs["Sheen Weight"].default_value = 0.4
    coords, mapping = nodes.new("ShaderNodeTexCoord"), nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (w / 0.5, h / 0.5, 1)   # weave at its real size (tile 0.5 m)
    links.new(coords.outputs["UV"], mapping.inputs["Vector"])
    rough_file, normal_file = LINEN / "rough_linen_rough_1k.jpg", LINEN / "rough_linen_nor_gl_1k.jpg"
    if rough_file.exists() and normal_file.exists():
        rough, nor_tex, nor = nodes.new("ShaderNodeTexImage"), nodes.new("ShaderNodeTexImage"), nodes.new("ShaderNodeNormalMap")
        rough.image = bpy.data.images.load(str(rough_file), check_existing=True)
        nor_tex.image = bpy.data.images.load(str(normal_file), check_existing=True)
        for img in (rough.image, nor_tex.image):
            img.colorspace_settings.name = "Non-Color"
        links.new(mapping.outputs["Vector"], rough.inputs["Vector"])
        links.new(mapping.outputs["Vector"], nor_tex.inputs["Vector"])
        links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])
        links.new(nor_tex.outputs["Color"], nor.inputs["Color"])
        links.new(nor.outputs["Normal"], bsdf.inputs["Normal"])
    else:
        bsdf.inputs["Roughness"].default_value = 0.9
    obj.data.materials.append(mat)
    gap = float(item.get("wall_gap", 0.22))   # above the passage the fabric hangs 0.26 to 0.34 m in front of the partition (the wall stands
    # radially, the fabric across the room, 1.5° askew to each other); brackets end before it, otherwise the check reports an intersection
    top = centre + Y * (h / 2 + 0.03)
    bm_rod = bmesh.new()
    rods(bm_rod, [top - X * (w / 2 + 0.12), top + X * (w / 2 + 0.12)], 0.022)
    for sx in (-1, 1):
        end = top + X * sx * (w / 2 + 0.12)
        bmesh.ops.create_uvsphere(bm_rod, u_segments=12, v_segments=8, radius=0.045, matrix=Matrix.Translation(end))
        rods(bm_rod, [top + X * sx * (w / 2 - 0.1), top + X * sx * (w / 2 - 0.1) - normal * gap], 0.015)
    mesh_object(f"Bannerstange {item['id']}", bm_rod, solid("Bannerstange", WKW["800"], roughness=0.35, metallic=0.7), rotor)


def placeholder(item, number):
    if item.get("id") == "r6_door":   # graphic on the leaf of the door from room 6, already set when the door is built
        return
    builders = {"shelves": shelves, "lectern": lectern, "flat": flat, "borgi": cutout, "table": table, "armchair": armchair,
                "rollup": rollup, "plate": plate, "divider": divider, "easel": easel, "station_chair": station_chair, "tablet": tablet}
    if item.get("kind") in builders:
        builders[item["kind"]](item)
        return
    if item.get("segments") and item.get("frame") in ("room", "wall"):   # long panel in pieces that follow the curvature (timeline on
        n, (w, h) = int(item["segments"]), item["size"]   # the second wall; on the inner wall the ends
        sign = 1 if item.get("facing") == "in" else -1    # of a flat 18 m panel disappeared behind the wall); image in strips;
        seamless = bool(item.get("seamless"))
        for k in range(n):                                 # image right is the walking direction when the panel faces inwards
            left, right = (0.06 if k > 0 and not seamless else 0.0), (0.06 if k < n - 1 and not seamless else 0.0)   # inner edges overlap, image crop with
            # (otherwise the dark back shows through in the joints; dimensions at scale 1)
            sub = dict(item, segments=None, size=[w / n + left + right, h], uv=(k / n - left / w, (k + 1) / n + right / w),
                       id=f"{item['id']} {k}", no_thread=k != n // 2)   # one thread to the globe per panel, not per strip
            sub["at"] = [item["at"][0] + sign * ((k - (n - 1) / 2) * (w / n) + (right - left) / 2), item["at"][1], item["at"][2]]
            placeholder(sub, number * 10 + k)
        if seamless:   # corners of neighbouring strips on the same points of the wall, to stop the elements flickering
            # in room 4: the overlap lay in almost the same plane, both strips with images shifted against each other; depending on
            # the image and the TAA sample one or the other won, letters in a vertical column were missing or jumped
            x0, d0, z0 = item["at"]
            for k in range(n):
                plane = bpy.data.objects.get(f"Platzhalter {item['id']} {k}")
                if plane is None:
                    continue
                inverse = plane.matrix_world.inverted()
                bounds = [x0 + sign * ((b - n / 2) * (w / n)) for b in (k, k + 1)]
                for vert in plane.data.vertices:
                    world = plane.matrix_world @ vert.co
                    top = vert.co.y > 0
                    candidates = [board_point({"frame": item["frame"], "room": item["room"], "at": [xb, d0, z0 + (h / 2 if top else -h / 2)]}, "at")
                                  for xb in bounds]
                    vert.co = inverse @ min(candidates, key=lambda p: (p - world).length)
        return
    centre, frame = board_point(item, "at"), item.get("frame", "ring")
    up = axis_up(centre)
    if item.get("kind") == "box":
        u, v = (item["at"][0], item["at"][1]) if frame == "ring" else room_point(item["room"], *item["at"][:2])[:2]
        w, d, h = item["size"]
        basis = Matrix((ring_dir(u, 1, 0).normalized(), Vector((0, 0, -1)), up)).transposed().to_4x4()
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation(centre + up * h / 2) @ basis @ Matrix.Diagonal((w, d, h, 1)))
        mesh_object(f"Platzhalter {item['id']}", bm, solid("Platzhalter Kasten", (0.85, 0.62, 0.2), roughness=0.6))
        return
    if frame in ("room", "wall") and item.get("facing") == "back":   # hangs across the room, towards whoever enters the room (sign)
        u, v, phi = (room_point if frame == "room" else wall_point)(item["room"], *item["at"][:2])
        normal = ring_dir(u, -math.sin(phi), math.cos(phi)).normalized()
    elif frame in ("room", "wall"):
        u, v, phi = (room_point if frame == "room" else wall_point)(item["room"], *item["at"][:2])
        normal = ring_dir(u, math.cos(phi), math.sin(phi)).normalized() * (1 if item.get("facing") == "out" else -1)
    elif frame == "hall":
        u, v = hall_point(*item["at"][:2])
        ang = math.radians(item.get("facing_deg", 270))
        normal = ring_dir(u, math.cos(ang), math.sin(ang)).normalized()
    else:
        target = item["face_to"]
        normal = ring_dir(item["at"][0], target[0] - item["at"][0], target[1] - item["at"][1]).normalized()
    tilt = math.radians(item.get("tilt", 0))   # panel tilts backwards (book on the lectern)
    normal = (normal * math.cos(tilt) + up * math.sin(tilt)).normalized()
    y = (up - normal * up.dot(normal)).normalized()
    if tilt > math.radians(80):
        y = Vector((0, 0, -1))   # lying flat: image top towards the shadow side
    x = y.cross(normal)
    rot = Matrix((x, y, normal)).transposed().to_4x4()
    w, h = item["size"]
    if frame in ("room", "wall", "hall") and not item.get("no_scale"):   # exhibits and signs scale with the museum
        w, h = w * S, h * S
    if item.get("fabric") and item.get("image"):
        fabric_banner(item, centre, x, y, normal, w, h)
        return
    if item.get("decal"):   # wall lettering: only letters on the wall, without panel, back or cables (like a wall
        # decal); wording in the field text, replaceable
        body = item.get("text", "")
        lines = body.split("\n")
        curve = bpy.data.curves.new(f"Wandschrift {item['id']}", "FONT")
        curve.body = body
        curve.align_x, curve.align_y = item.get("align", "LEFT"), "CENTER"
        curve.space_line = float(item.get("line_spacing", 1.1))
        if item.get("font"):   # path from the repository root (Open Sans from the corporate design)
            curve.font = bpy.data.fonts.load(str(BASE.parents[3] / item["font"]), check_existing=True)
        curve.offset = float(item.get("weight", 0.0))   # thicker strokes (Blender loads the variable font at regular weight)
        extra = 0.9 if item.get("attribution") else 0.0   # room for the attribution line below (half size)
        curve.size = min(h / (len(lines) * curve.space_line + 0.2 + extra), w / (0.55 * max(len(line) for line in lines) + 0.5))
        label = bpy.data.objects.new(f"Wandschrift {item['id']}", curve)
        scene.collection.objects.link(label)
        material = solid("Wandschrift", tuple(item.get("color", WKW["800"]))[:3], roughness=0.85)
        label.data.materials.append(material)
        left_edge = -w / 2 if curve.align_x == "LEFT" else 0.0
        shift_up = y * (extra * curve.size / 2)   # block including attribution stays centred on at
        label.matrix_world = Matrix.Translation(centre + x * left_edge + shift_up + normal * 0.005) @ rot
        if item.get("attribution"):   # author below the quote, as source and in the exact wording
            small = bpy.data.curves.new(f"Wandschrift Nennung {item['id']}", "FONT")
            small.body = item["attribution"]
            small.align_x, small.align_y = curve.align_x, "TOP"
            small.font, small.offset = curve.font, curve.offset * 0.5
            small.size = curve.size * 0.5
            credit = bpy.data.objects.new(f"Wandschrift Nennung {item['id']}", small)
            scene.collection.objects.link(credit)
            credit.data.materials.append(material)
            below = y * (len(lines) * curve.space_line * curve.size / 2 + 0.35 * curve.size)
            credit.matrix_world = Matrix.Translation(centre + x * left_edge + shift_up - below + normal * 0.005) @ rot
        return
    if item.get("backing"):   # dark backing board: the panel visibly hangs in front of the wall instead of inside it (a banner
        bm_b = bmesh.new()   # hangs on the wall)
        bmesh.ops.create_cube(bm_b, size=1.0, matrix=Matrix.Translation(centre - normal * 0.06) @ rot @ Matrix.Diagonal((w + 0.1, h + 0.1, 0.1, 1)))
        mesh_object(f"Träger {item['id']}", bm_b, m_back, rotor)
    if frame == "wall" and not item.get("no_back"):   # back of the exhibit and cables through the wall into the centre room
        bm_b = bmesh.new()   # (from the centre room one sees the backs of all elements and screens)
        rim = 0.25 * S if item.get("image") and not item.get("no_rim") else 0.0   # images get a dark frame: light stills
        # otherwise blend into the wall; no_rim for images that fill the wall (no needless frame)
        bmesh.ops.create_cube(bm_b, size=1.0, matrix=Matrix.Translation(centre - normal * 0.06) @ rot @ Matrix.Diagonal((w + rim, h + rim, 0.1, 1)))
        mesh_object(f"Rückseite {item['id']}", bm_b, m_back, rotor)
        u_w, v_w, phi_w = wall_point(item["room"], item["at"][0], -0.3)
        behind = on_ring(u_w, v_w, item["at"][2] * S)
        bm_c = bmesh.new()
        rods(bm_c, [centre - normal * 0.1, behind], 0.025)
        mesh_object(f"Kabel {item['id']}", bm_c, m_cable, rotor)
        if not item.get("no_thread"):
            THREAD_SOURCES.append((u_w, v_w, item["at"][2] * S))
            # equipment on the centre-room side, where the cable comes out of the wall, to show how everything is connected:
            # junction box, three cables to the floor, power strip; named "Kabel ...", the check skips cables
            h_box = min(item["at"][2] * S, museum_h - 0.6)
            n_hall = -ring_dir(u_w, math.cos(phi_w), math.sin(phi_w)).normalized()   # points into the centre room
            up_w = axis_up(on_ring(u_w, v_w, 0.0))
            x_w = up_w.cross(n_hall).normalized()
            bm_t = bmesh.new()
            local_box(bm_t, on_ring(u_w, v_w, h_box), (x_w, up_w, n_hall), (0, 0, 0.06), (0.4, 0.3, 0.12))
            for dx in (-0.1, 0.0, 0.1):
                top = on_ring(u_w, v_w, h_box - 0.15) + x_w * dx + n_hall * 0.06
                foot = on_ring(u_w, v_w, 0.08) + x_w * (dx * 3 + 0.25) + n_hall * 0.06
                rods(bm_t, [top, foot], 0.015)
            local_box(bm_t, on_ring(u_w, v_w, 0.05), (x_w, up_w, n_hall), (0.45, 0, 0.08), (0.6, 0.06, 0.1))
            mesh_object(f"Kabel Technik {item['id']}", bm_t, m_cable, rotor)
    bpy.ops.mesh.primitive_plane_add(size=2)
    plane = bpy.context.active_object
    plane.name = f"Platzhalter {item['id']}"
    plane.matrix_world = Matrix.Translation(centre) @ rot @ Matrix.Diagonal((w / 2, h / 2, 1, 1))
    if item.get("image"):
        mat = bpy.data.materials.new(f"Platzhalterbild {number}")
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        tex, emit, out = nodes.new("ShaderNodeTexImage"), nodes.new("ShaderNodeEmission"), nodes.new("ShaderNodeOutputMaterial")
        tex.image = bpy.data.images.load(item["image"], check_existing=True)
        emit.inputs["Strength"].default_value = 1.0
        links.new(tex.outputs["Color"], emit.inputs["Color"])
        links.new(emit.outputs[0], out.inputs["Surface"])
        plane.data.materials.append(mat)
        if item.get("uv"):   # strip of an image (segments): show only the crop u0 to u1
            u0, u1 = item["uv"]
            for loop in plane.data.uv_layers.active.data:
                loop.uv = (u0 + loop.uv[0] * (u1 - u0), loop.uv[1])
        return
    color = tuple(item["color"]) if item.get("color") else (0.86, 0.86, 0.82)   # accent colour per room (signs)
    plane.data.materials.append(glow(f"Platzhalter Tafel {color}", color, 1.0))
    body = item.get("text", "")
    if not body:
        return
    lines = body.split("\n")
    curve = bpy.data.curves.new(f"Platzhaltertext {item['id']}", "FONT")
    curve.body = body
    curve.align_x, curve.align_y = "CENTER", "CENTER"
    curve.size = min(h / (len(lines) + 1.2), w / (0.62 * max(len(line) for line in lines) + 1))
    label = bpy.data.objects.new(f"Platzhaltertext {item['id']}", curve)
    scene.collection.objects.link(label)
    dark = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2] < 0.18   # light lettering on a dark panel
    label.data.materials.append(glow("Platzhalter Schrift hell", (1, 1, 1), 2.0) if dark else
                                solid("Platzhalter Schrift", (0.05, 0.05, 0.08), roughness=0.8))
    label.matrix_world = Matrix.Translation(centre + normal * 0.05) @ rot


def fit_objects(panel):
    """Objects that must lie entirely in the image (field fit: identifiers of placeholders or "book")."""
    found = []
    for name in panel.get("fit") or []:
        if name == "book":
            found += [p for p in BOOK.get("pages", ()) if p]
            continue
        for obj in bpy.data.objects:
            if obj.name in (name, "Platzhalter " + name, "Lesepult " + name, "Raumteiler " + name, "Borgi " + name) \
                    or obj.name.startswith("Platzhalter " + name + " "):
                found.append(obj)
    return found


def fit_camera(cam, objects, margin=0.05, limit=3.0):
    """Moves the camera back along its viewing direction until all corners of the objects lie in the image with a margin, so
    that no top edge is cut off. Returns the distance; at most limit metres (field fit_limit per panel), otherwise the camera
    would end up behind the wall."""
    from bpy_extras.object_utils import world_to_camera_view
    corners = [obj.matrix_world @ Vector(c) for obj in objects for c in obj.bound_box]
    if not corners:
        return 0.0
    bpy.context.view_layer.update()
    forward = (cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))).normalized()
    centre = sum(corners, Vector()) / len(corners)
    moved = 0.0
    for _ in range(80):
        views = [world_to_camera_view(scene, cam, p) for p in corners]
        if all(v.z > 0 and margin <= v.x <= 1 - margin and margin <= v.y <= 1 - margin for v in views):
            return moved
        if moved >= limit:
            print(f"Rahmen: Grenze {limit} m erreicht, {len(objects)} Objekte bleiben angeschnitten", flush=True)
            return moved
        step = max(0.05, (centre - cam.location).length * 0.05)
        hit, *_rest = ray_hit(cam.location, -forward, step + CLEAR)   # never back through a surface (cameras inside the wall)
        if hit:
            print(f"Rahmen: Fläche {hit:.1f} m hinter der Kamera, Rückfahrt endet bei {moved:.1f} m", flush=True)
            return moved
        cam.location = cam.location - forward * step
        moved += step
        bpy.context.view_layer.update()
    return moved


# ---------------------------------------------------------------- check routine: compute instead of hope
# Camera: nearest surface at least CLEAR away (the camera's clip_start is 0.5 m: anything closer is cut off and one sees
# through the wall), clear view to the target. Exhibits: an intersection with walls is not automatically an error, it depends
# on the placement (field mount): free (free in the room, no intersection), wall (back against the wall, intersection of the
# back and the carrier intended), embedded (set into the wall, every intersection intended). Cables always run through the wall.
CLEAR = 0.5
WALL_NAMES = ("Museum", "Museum Innenwand", "Museum Wände mit Durchgang", "Museum Center-Tür Sturz", "Museum Torsturz Tor",
              "Museum Center-Tür Portal", "Museum Portal Tor")


def ray_hit(origin, direction, distance):
    """Distance and name of the first opaque surface along a ray, otherwise (None, None). Glass (name with "Glas", window band,
    lantern of the centre room) does not count: one sees through it (09.3 and 09.4 in the map room were false alarms)."""
    depsgraph, travelled = bpy.context.evaluated_depsgraph_get(), 0.0
    for _ in range(8):
        hit, location, _n, _i, obj, _m = scene.ray_cast(depsgraph, origin + direction * travelled, direction, distance=distance - travelled)
        if not hit:
            return None, None
        travelled = (location - origin).length
        see_through = any(m and m.surface_render_method == "BLENDED" for m in obj.data.materials) if obj.type == "MESH" else False
        if not (see_through or "Glas" in obj.name or obj.name in ("Museum Fensterband", "Museum Mittelraum")):   # translucent
            # material counts as glass (elevator cabin, tower, hall: 07.5 reported the view through the cabin as blocked)
            return travelled, obj.name
        travelled += 0.01
    return None, None


def sync_viewport():
    """ray_cast sees what is visible in the viewport; for the check that must match the render."""
    for obj in bpy.data.objects:
        if obj.hide_viewport != obj.hide_render:
            obj.hide_viewport = obj.hide_render
    bpy.context.view_layer.update()


def mount_of(item):
    if item.get("mount"):
        return item["mount"]
    if item.get("kind") == "shelves" or (item.get("frame") == "wall" and item.get("facing") == "out"):
        return "wall"
    return "free"


def check_objects():
    """Intersections of the exhibits with walls and height against the ceiling, once per run. Result per identifier: list (level, text)."""
    from mathutils.bvhtree import BVHTree
    depsgraph = bpy.context.evaluated_depsgraph_get()
    walls = [(name, BVHTree.FromObject(bpy.data.objects[name], depsgraph)) for name in WALL_NAMES
             if name in bpy.data.objects and bpy.data.objects[name].type == "MESH"]
    found = {}
    for item in BOARD.get("placeholders", []):
        mount, notes = mount_of(item), []
        parts = [o for o in bpy.data.objects if o.type in ("MESH", "FONT") and not o.hide_render   # every part that carries the identifier at
                 and (o.name.endswith(f" {item['id']}") or f" {item['id']} " in o.name)]   # the end ("Raumteiler Körper r5_divider"
        # slipped through a fixed list of names and was not checked, although it stood in the wall)
        top = 0.0
        for obj in parts:
            for c in obj.bound_box:
                p = obj.matrix_world @ Vector(c)
                top = max(top, R - 0.5 - math.hypot(p.x, p.y))
            if obj.type != "MESH" or obj.name.startswith("Kabel "):
                continue
            tree = BVHTree.FromObject(obj, depsgraph)
            for wall_name, wall_tree in walls:
                if tree.overlap(wall_tree):
                    back = obj.name.startswith(("Rückseite ", "Träger "))
                    wanted = mount == "embedded" or (mount == "wall" and back)
                    notes.append(("gewollt" if wanted else "Fehler", f"{obj.name} schneidet {wall_name} (Lage {mount})"))
        if top > museum_h + 0.05:   # heights above the ring floor: the museum floor lies there, the ceiling museum_h above
            notes.append(("Fehler", f"Oberkante {top:.2f} m über der Decke ({museum_h:.1f} m)"))
        if item.get("above_passage"):
            bottom = min(R - 0.5 - math.hypot(*(o.matrix_world @ Vector(c)).xy) for o in parts for c in o.bound_box)
            if bottom < door_h:
                notes.append(("Fehler", f"Unterkante {bottom:.2f} m in der Türöffnung ({door_h:.2f} m)"))
        found[item["id"]] = notes
    return found


def item_objects(item_id, prefix=""):
    """Visible parts of an exhibit; prefix selects one part (chair station: only the screen with the video, "Platzhalter")."""
    return [o for o in bpy.data.objects if o.name.endswith(" " + item_id) and o.name.startswith(prefix)
            and o.type in ("MESH", "FONT") and not o.hide_render]


def credit_prefix(item):
    """Which part of an exhibit shows the third-party work: at the chair station only the video screen (otherwise the credit
    appeared while only the red chair was visible behind the room divider)."""
    return "Platzhalter" if item.get("kind") == "station_chair" or (item.get("kind") == "tablet" and item.get("video")) else ""


def visible_in(cam, item_id, prefix=""):
    """Is a part of the exhibit in the image and visible from the camera (the line of sight hits the exhibit first)?"""
    from bpy_extras.object_utils import world_to_camera_view
    for obj in item_objects(item_id, prefix):
        points = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        points.append(sum(points, Vector()) / len(points))
        for p in points:
            v = world_to_camera_view(scene, cam, p)
            if not (v.z > 0 and 0 <= v.x <= 1 and 0 <= v.y <= 1):
                continue
            ray = p - cam.location
            d, name = ray_hit(cam.location, ray.normalized(), ray.length + 0.05)
            if d is None or name.endswith(" " + item_id) or d >= ray.length - 0.1:
                return True
    return False


CREDIT_MIN_SHARE = 0.02   # a third-party work counts as in the image if it covers at least 2 % of the image area (07.1: tiny
                          # screens behind the glass wall are no quotation)


def screen_share(cam, item_id, prefix=""):
    """Share of the image area taken by the rectangle around the projected corners of the exhibit (0 to 1, ignoring occlusion)."""
    from bpy_extras.object_utils import world_to_camera_view
    xs, ys = [], []
    for obj in item_objects(item_id, prefix):
        for c in obj.bound_box:
            v = world_to_camera_view(scene, cam, obj.matrix_world @ Vector(c))
            if v.z > 0:
                xs.append(min(max(v.x, 0.0), 1.0))
                ys.append(min(max(v.y, 0.0), 1.0))
    return (max(xs) - min(xs)) * (max(ys) - min(ys)) if xs else 0.0


def credit_side(cam, item):
    """Credit of the side facing the camera: back_credit when the camera stands behind the image side (room divider: the
    cover in front, the photo of the talk behind)."""
    front = bpy.data.objects.get(f"Raumteiler {item['id']}")
    if not item.get("back_credit") or front is None:
        return item["credit"]
    normal = front.matrix_world.to_3x3() @ Vector((0, 0, 1))
    return item["credit"] if normal.dot(cam.location - front.matrix_world.translation) > 0 else item["back_credit"]


def check_camera(cam, target, before):
    """Camera clear (nearest surface), clear view to the target, way back without a wall. List (level, text)."""
    notes = []
    bpy.context.view_layer.update()   # rays through a grid of 9 x 5 points in the field of view: only what lies in the image counts
    frame = [cam.matrix_world @ v for v in cam.data.view_frame(scene=scene)]   # (03.1 and 06.3: a wall beside the camera was a false alarm)
    rays = [(frame[3] + (frame[0] - frame[3]) * (i / 8) + (frame[2] - frame[3]) * (j / 4)) - cam.location for i in range(9) for j in range(5)]
    nearest, name = min(((d, n) for d, n in (ray_hit(cam.location, r.normalized(), 50.0) for r in rays) if d is not None), default=(None, None))
    if nearest is not None and nearest < CLEAR:
        notes.append(("Fehler", f"Fläche {name} nur {nearest:.2f} m vor der Kamera im Bild (unter {CLEAR} m wird sie abgeschnitten, man sieht hindurch)"))
    look = Vector(target) - cam.location
    d, name = ray_hit(cam.location, look.normalized(), look.length)
    if d is not None and d < min(1.5, 0.3 * look.length) and not name.endswith(tuple(f" {i}" for i in (p["id"] for p in BOARD.get("placeholders", [])))):
        notes.append(("Fehler", f"Blick nach {d:.2f} m von {name} verstellt"))
    back = cam.location - Vector(before)
    if back.length > 0.01:
        d, name = ray_hit(Vector(before), back.normalized(), back.length)
        if d is not None:
            notes.append(("Fehler", f"Rückfahrt (fit) geht durch {name}"))
    return notes


def image_spread(path):
    """Colour spread of the finished image: standard deviation of the brightness (0 to 1); below 0.04 it is nearly uniform."""
    import numpy as np
    img = bpy.data.images.load(str(path), check_existing=False)
    px = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    rgb = px.reshape(-1, 4)[:, :3]
    return float((rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).std())


def panel_pose(panel, lens=None):
    """Camera of a panel as in the storyboard (target, orientation, lens shift, fitting); returns the camera object.
    lens overrides the focal length of the panel (ride: one focal length, closeness via the position). With fill: true the
    camera moves perpendicularly in front of the first fit object so that it fills the image exactly (so the title slide
    matches the camera frame)."""
    spec = dict(panel["camera"], **({"lens": lens} if lens else {}))
    location, target = board_point(spec, "at", scale_height=False), board_point(spec, "look", scale_height=True)
    if spec.get("up") in ("outward", "inward") and spec.get("frame") == "room":
        u_, v_, phi_ = room_point(spec["room"], *spec["at"][:2])
        up = ring_dir(u_, math.cos(phi_), math.sin(phi_)).normalized() * (1 if spec["up"] == "outward" else -1)
    elif spec.get("up"):
        up = Vector(spec["up"])
    elif spec.get("frame", "ring") in ("ring", "room", "wall", "hall"):
        up = axis_up(location)
    else:
        up = None
    if panel.get("fill") and fit_objects(panel):   # object fills the image exactly: perpendicular in front of it, distance from size and angle of view
        # all fit objects together (for the book both pages; with only the first the centre lay on the left page and the right one
        # was cut off)
        corners = [obj.matrix_world @ Vector(c) for obj in fit_objects(panel) for c in obj.bound_box]
        centre = sum(corners, Vector()) / len(corners)
        normal = Vector(location) - centre
        normal = normal.normalized() if normal.length else Vector((0, 0, 1))
        up0 = Vector(up) if up is not None and abs(Vector(up).normalized().dot(normal)) < 0.9 else axis_up(centre)
        if panel.get("fill_axis") == "surface":   # perpendicular to the surface, its top edge at the top of the image (book: outline
            axes3 = fit_objects(panel)[0].matrix_world.to_3x3()   # exactly around the open book, so one sees only the book)
            face = axes3.col[2].normalized()
            normal = face if face.dot(normal) > 0 else -face   # towards the side of the viewpoint
            up0 = axes3.col[1].normalized()
        elif abs(up0.normalized().dot(normal)) > 0.9:   # looking straight down (book): the top of the image is the walking direction of the panel
            up0 = normal.orthogonal()
        right = normal.cross(up0).normalized()
        up1 = right.cross(normal).normalized()
        width = max(c.dot(right) for c in corners) - min(c.dot(right) for c in corners)
        height = max(c.dot(up1) for c in corners) - min(c.dot(up1) for c in corners)
        if panel.get("fill_height"):   # the height fills the image exactly, centred horizontally in front of the camera (timeline in room 4,
            # flush at top and bottom); the width follows the aspect ratio. Viewing direction horizontal out of the panel (at to look), up is
            # the axis; the surface of the curved wall stood askew (horizon -2.8 degrees at 04.1)
            flat = Vector(location) - Vector(target)
            flat = flat - up0 * flat.dot(up0)
            normal = flat.normalized() if flat.length > 1e-3 else normal
            right = normal.cross(up0).normalized()
            up1 = right.cross(normal).normalized()
            # only the segments in front of the camera: the middle of all segments of a curved wall (room 4, 9 segments over 35 m) does
            # not lie on the wall, the camera stood too close and too low (image 04.1)
            near = [o for o in fit_objects(panel) if abs((o.matrix_world.translation - Vector(location)).dot(right)) < 6.0]
            if near:
                corners = [o.matrix_world @ Vector(c) for o in near for c in o.bound_box]
                centre = sum(corners, Vector()) / len(corners)
            width = max(c.dot(right) for c in corners) - min(c.dot(right) for c in corners)
            height = max(c.dot(up1) for c in corners) - min(c.dot(up1) for c in corners)
            centre = centre + right * (Vector(location).dot(right) - centre.dot(right))
            width = height * scene.render.resolution_x / scene.render.resolution_y
        if panel.get("fill_part"):   # only a crop fills the image: [left, right, bottom, top] as a share of the surface (lectern shot
            x0, x1, y0, y1 = (float(v) for v in panel["fill_part"])   # 03.3a on the graph, zooming in closer on
            lo_x, lo_y = min(c.dot(right) for c in corners), min(c.dot(up1) for c in corners)   # the modelled part)
            # mirrored horizontally: with fill_axis surface, right points to the left in the image (03.3a showed the left half of the lectern instead of the graph)
            centre = centre + right * (lo_x + width * (1 - (x0 + x1) / 2) - centre.dot(right)) + up1 * (lo_y + height * (y0 + y1) / 2 - centre.dot(up1))
            width, height = width * (x1 - x0), height * (y1 - y0)
        aspect = scene.render.resolution_x / scene.render.resolution_y
        hfov = 2 * math.atan(36.0 / (2 * float(spec.get("lens", 24))))
        vfov = 2 * math.atan(math.tan(hfov / 2) / aspect)
        margin = 1 + float(panel.get("fill_margin", 0.0))   # 0 = borderless (title slide); 0.08 leaves 8 % margin (book)
        distance = max(width / 2 / math.tan(hfov / 2), height / 2 / math.tan(vfov / 2)) * margin
        location, target, up = centre + normal * distance, centre, up1
        spec = dict(spec, shift_y=0.0)
    cam = camera(location, target, spec.get("lens", 24), up)
    cam.data.shift_y = float(spec.get("shift_y", 0.0))
    if not panel.get("fill"):
        fit_camera(cam, fit_objects(panel), limit=float(panel.get("fit_limit", 3.0)))
    return cam


def passage_pose(room_from, room_to):
    """Waypoint in the middle of the passage between two neighbouring rooms at eye height, looking into the middle of the next room."""
    r_mid = (hall_r + mr) / 2
    phi_b = math.radians(GATE_DEG - 60 * (room_from - 1) - 30 * (1 if (room_to - room_from) % 6 == 1 else -1))
    phi_n = math.radians(GATE_DEG - 60 * (room_to - 1))
    location = on_ring(mx + r_mid * math.cos(phi_b), my + r_mid * math.sin(phi_b), 1.7)
    target = on_ring(mx + r_mid * math.cos(phi_n), my + r_mid * math.sin(phi_n), 1.7)
    return camera(location, target, 22, axis_up(location))


def nearest_in_view(cam):
    """Distance of the nearest opaque surface in the field of view (rays through a grid of 9 x 5 points), otherwise None."""
    frame = [cam.matrix_world @ v for v in cam.data.view_frame(scene=scene)]
    origin = cam.matrix_world.translation
    rays = [(frame[3] + (frame[0] - frame[3]) * (i / 8) + (frame[2] - frame[3]) * (j / 4)) - origin for i in range(9) for j in range(5)]
    hits = [(d, name) for d, name in (ray_hit(origin, r.normalized(), 50.0) for r in rays) if d is not None]
    return min(hits) if hits else (None, None)


RIDE_LENS = float(CONFIG.get("walk_profile", {}).get("ride_lens", 22))   # one focal length for the ride
QUALITY = CONFIG.get("ride_quality", {}).get(ARGS[ARGS.index("--quality") + 1] if "--quality" in ARGS else "preview",
                                              {"width": 640, "height": 360, "fps": 24, "samples": 4, "format": "JPEG",
                                               "output": "_scratch/ride_station"})   # levels in config.yaml


def ride_up(p):
    """Up direction for the ride and its check: in the ring up to 25 m above the floor and within the ring depth towards the axis;
    in the spoke and the hub up to 150 m from the axis the world axis as in the panels; in between and outside (the station in
    space) no horizon (False). At 40 m the outside ride 10.1 to 10.2 still counted as ring. In the spoke (within the ring depth)
    the world axis applies as in the hub; between 25 and 60 m above the ring floor "up" blends smoothly from the direction to
    the axis to the world axis: so the view down onto the museum and up to the hub is level instead of steep, and the pan out
    of the elevator does not tip over the pole (a hard switch caused roll rates of thousands of degrees per second)."""
    radial = math.hypot(p.x, p.y)
    in_rim = -float(STATION.get("rim_depth", 150)) - 2 < p.z < 2
    if R - 25 < radial < R + 5 and in_rim:
        return axis_up(p)
    # transition 25 to 100 m (previously up to 60 m): at 15 m/s "up" turned by 90 degrees in 2.3 s and the levelling could not
    # keep up (horizon -6.8 degrees on the descent 08.1 to 08.2); 08.2 lies 104 m above the floor
    if R - 100 < radial <= R - 25 and in_rim:
        t = (R - 25 - radial) / 75
        t = t * t * (3 - 2 * t)
        return (axis_up(p) * (1 - t) + Vector((0, 0, 1)) * t).normalized()
    # Hub (floor on the sun side as a rule): in the lobby and rooms up is towards the shadow side (-z); in the axis tube between
    # the bearing ring and the lobby ceiling, up rolls about the viewing direction to the bar from +z (spoke) to -z, through the
    # vertical to the side instead of through zero (otherwise the horizon was at 80 degrees before 09.3, because +z applied here)
    hub_low = -float(HUB.get("module_zone", 130)) - 1.5
    if radial < 12 and SPOKE_Z + 1.0 < p.z < LOBBY_CEIL:
        t = (p.z - SPOKE_Z - 1.0) / (LOBBY_CEIL - SPOKE_Z - 1.0)
        t = t * t * (3 - 2 * t)
        bar = Matrix.Rotation(HUB_TURN, 3, "Z") @ (centroid("spacebar") or Vector((0, -1, 0)))
        # cabin_turn: steady: up in the cabin points to the bar at the bearing ring (pose of 07.5a,
        # the hub stands that way, hub_root_object) and turns to -z by the lobby ceiling, a quarter turn about the horizontal
        flat = Vector((bar.x, bar.y, 0)).normalized()
        return (flat * math.cos(math.pi / 2 * t) + Vector((0, 0, -1)) * math.sin(math.pi / 2 * t)).normalized()
    if radial <= 150 and hub_low < p.z < 2:
        return Vector((0, 0, -1))
    return Vector((0, 0, 1)) if radial <= R - 100 and (in_rim or radial <= 150) else False


def export_objects(path):
    """Inventory of the built scene for the station planner: per object name, type, parent, position in world
    coordinates, rotation (Euler, degrees), size of the bounding box in world space, centre of the bounding box and materials;
    state without rotation of the ring (frame 1). Coordinates as in the scene: z towards the sun, metres. Stars are summarised as one number."""
    rows, stars_count = [], 0
    for obj in scene.objects:
        if obj.name.startswith("Stern"):
            stars_count += 1
            continue
        wkw_id, id_source = obj.get("wkw_id"), "property"
        if wkw_id is None:   # exhibits are named "<part> <identifier> [n]" (Pult r5_lectern, Bücher r5_shelves 0): identifier from the name
            wkw_id = next((token for token in obj.name.split() if re.fullmatch(r"r\d+_[a-z0-9_]+", token)), None)
            id_source = "name" if wkw_id else None
        row = {"name": obj.name, "wkw_id": wkw_id, "wkw_id_source": id_source, "type": obj.type,
               "parent": obj.parent.name if obj.parent else None,
               "location": [round(c, 3) for c in obj.matrix_world.translation],
               "rotation_deg": [round(math.degrees(a), 2) for a in obj.matrix_world.to_euler()]}
        if obj.type in ("MESH", "CURVE", "FONT") and obj.bound_box:
            corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            low = [min(c[i] for c in corners) for i in range(3)]
            high = [max(c[i] for c in corners) for i in range(3)]
            row["bbox_size"] = [round(h - l, 3) for l, h in zip(low, high)]
            row["bbox_centre"] = [round((h + l) / 2, 3) for l, h in zip(low, high)]
            row["materials"] = [m.name for m in getattr(obj.data, "materials", []) if m]
        rows.append(row)
    path.write_text(json.dumps({"source": "station_scene.py", "frame": 1, "units": "m", "axes": "z zur Sonne",
                                "stars": stars_count, "objects": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Bestand: {len(rows)} Objekte nach {path}", flush=True)


def hub_root_object():
    """Put the hub and the stars under a common parent, turned by HUB_TURN, so that after decoupling the ride ends with the bar
    in front: the hub stops at the angle at which the module face_module of the panel with despin lies in the viewing direction
    of the cabin; the camera does not turn for this, the panels in the system hub turn with it (board_point). Applies to the
    ride and the stills; run once after export_objects (the inventory for the planner stays unrotated)."""
    global HUB_TURN, HUB_ROOT
    stop = next((p for s in BOARD.get("scenes", []) for p in s.get("panels", []) if p.get("despin") and p.get("face_module")), None)
    target = centroid(stop["face_module"]) if stop else None
    # During the ride the camera carries the pose of the panel with cabin_view: lock until the release,
    # so its viewing direction counts; without lock that of the panel with despin (still)
    held = next((p for s in BOARD.get("scenes", []) for p in s.get("panels", []) if p.get("cabin_view") == "lock"), stop)
    if target is not None and target.xy.length > 0.1:
        ahead = board_point(held["camera"], "look") - board_point(held["camera"], "at")
        if held is not stop:   # ride: in the axis tube the cabin rights itself, floor towards the sun (cabin_turn:
            # steady, shortest rotation from the cabin's up to up in the hub, -z); the bar lies in the viewing direction after that
            # (before, the bar was aligned before the righting, which resulted in a 180 degree flip)
            ahead = axis_up(board_point(held["camera"], "at")).rotation_difference(Vector((0, 0, -1))) @ ahead
        HUB_TURN = math.atan2(ahead.y, ahead.x) - math.atan2(target.y, target.x)
    rim_low = -float(STATION.get("rim_depth", 150)) - 2
    HUB_ROOT = bpy.data.objects.new("Hub (steht)", None)
    scene.collection.objects.link(HUB_ROOT)
    for obj in list(scene.objects):
        if obj.parent is not None or obj in (rotor, HUB_ROOT) or obj.type in ("CAMERA", "LIGHT"):
            continue
        centre = obj.matrix_world @ (sum((Vector(c) for c in obj.bound_box), Vector()) / 8) if obj.type == "MESH" else obj.location
        in_ring = math.hypot(centre.x, centre.y) > R - RIM - 2 and rim_low < centre.z < 2
        if obj.name.startswith("Stern") or not in_ring:   # placeholders in the museum are not parented to the rotor, but stay in the ring
            obj.parent = HUB_ROOT
    HUB_ROOT.rotation_euler = (0, 0, HUB_TURN)
    print(f"Hub steht nach dem Abkoppeln bei {math.degrees(HUB_TURN):.1f} Grad ({stop['face_module'] if stop else 'ohne face_module'} vorn)", flush=True)


def spin_station(timeline, fps, by_name):
    """Rotation during the ride: from the moment of decoupling the world rotates around the viewer. The ride camera moves in
    cabin coordinates; its check (speed, pan) is not affected. Up to the panel with despin the cabin turns with the ring: in the
    image the ring stands still, hub and stars circle against the rotation (station.rpm, real rotation rate). During the panel
    with despin the cabin in the axis tube is taken out of the rotation (rotation rate smoothly to zero); after that the hub
    stands still and the ring keeps turning. The angle of the hub ends at zero, so the panels in the system hub apply
    unchanged. The light stays fixed (the sun really stands on the axis)."""
    stop = next((s for s in timeline if by_name.get(s["name"], {}).get("despin")), None)
    omega = 2 * math.pi * RPM / 60
    if stop is None:   # partial ride in the ring (e.g. rooms 1 to 7): the hub circles the whole time, so it is
        t0 = t1 = float("inf")   # already turning when looking up (before, ring and hub stood still in such runs)
        print("Drehung: keine Tafel mit despin, der Hub kreist über die ganze Fahrt", flush=True)
    else:
        t0, t1 = (stop["arrive"] + 0.5 * fps) / fps, (stop["frame"] - 0.5 * fps) / fps
    hub_root = HUB_ROOT   # from hub_root_object, turned by HUB_TURN
    rate, phi, angles = [], 0.0, []
    for f in range(1, scene.frame_end + 1):
        t = (f - 1) / fps
        u = 0.0 if stop is None else min(1.0, max(0.0, (t - t0) / max(t1 - t0, 1e-6)))
        angles.append(phi)
        phi += omega * (1 - u * u * (3 - 2 * u)) / fps   # rotation rate of the cabin relative to the hub
    end = angles[-1]
    for f, phi in enumerate(angles, 1):
        hub_root.rotation_euler = (0, 0, end - phi + HUB_TURN)
        rotor.rotation_euler = (0, 0, omega * (f - 1) / fps - phi)
        hub_root.keyframe_insert("rotation_euler", index=2, frame=f)
        rotor.keyframe_insert("rotation_euler", index=2, frame=f)
    from camera_moves import fcurves_of
    for obj in (hub_root, rotor):
        for fc in fcurves_of(obj):
            for point in fc.keyframe_points:
                point.interpolation = "LINEAR"
    if stop is not None:   # partial ride without despin (--panels): stop is None
        print(f"Drehung: Kabine löst sich bei {t0:.1f} bis {t1:.1f} s von der Drehung ({stop['name']})", flush=True)


def cabin_follow(all_frames, eye=1.7):
    """Cabin around the ride camera in the axis tube: floor, four posts and two rings, floor across the axis (up is towards the
    shadow side, floor on the sun side as in the lobby); visible while the camera is on the axis, hidden otherwise. In the lobby it closes
    the shaft in the ceiling (otherwise one saw the ring through the hole). The model has its origin in the camera's eye and turns
    with the ride camera (pose on arrival = floor towards the sun): relative to the cabin the camera never turns, its pose stays
    fixed until leaving the elevator; the ride defines the tilt to floor towards the sun."""
    # A glass cabin with a dark frame (earlier version: yellow rings), with a sliding door to the bar; it stays in the lobby and
    # lets the visitor out into the world again (earlier it disappeared at 0:46), and it runs on rails
    # from the bearing ring through the hole in the lobby ceiling down to the floor
    radius, height, gap = 2.1, 2.66, math.radians(50)   # door opening per side of the exit direction
    floor_z = eye + 0.06
    arrived = LOBBY_FLOOR - eye - 0.05
    on_axis_of = lambda loc: loc.xy.length < 1.0 and loc.z > SPOKE_Z + 1.0
    land = next((k for k, (loc, q) in enumerate(all_frames) if on_axis_of(loc) and loc.z >= arrived), None)
    if land is None:
        land = next((k for k in range(len(all_frames) - 1, -1, -1) if on_axis_of(all_frames[k][0])), len(all_frames) - 1)
    land_loc, arrival = all_frames[land][0].copy(), Quaternion(all_frames[land][1])
    # exit: direction in which the camera leaves the cabin (09.1b); without an exit in the partial ride the viewing direction on arrival
    leave = next((k for k in range(land, len(all_frames)) if (all_frames[k][0] - land_loc).xy.length > 1.5), None)
    out = (all_frames[leave][0] - land_loc) if leave is not None else (arrival @ Vector((0, 0, -1)))
    exit_angle = math.atan2(out.y, out.x)
    m_glass = glass("Kabinenglas Achse", (0.75, 0.9, 1.0), 0.12)
    m_frame = solid("Kabinenrahmen Achse", (0.08, 0.08, 0.09), roughness=0.4)
    bm, bm_glass, bm_frame, bm_door = bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=2.2, radius2=2.2, depth=0.12, matrix=Matrix.Translation((0, 0, floor_z)))
    bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=2.2, radius2=2.2, depth=0.12, matrix=Matrix.Translation((0, 0, floor_z - height - 0.06)))
    n = 48
    at = lambda a, r, z: Vector((r * math.cos(a), r * math.sin(a), z))
    for i in range(n):   # glass wall without the door opening; the door is the same piece of wall and slides behind the wall
        a0, a1 = exit_angle + 2 * math.pi * i / n, exit_angle + 2 * math.pi * (i + 1) / n
        mid = (a0 + a1) / 2 - exit_angle
        target = bm_door if min(mid, 2 * math.pi - mid) < gap else bm_glass
        r = radius - 0.06 if target is bm_door else radius
        target.faces.new([target.verts.new(at(a, r, z)) for a, z in ((a0, floor_z), (a1, floor_z), (a1, floor_z - height), (a0, floor_z - height))])
    for side in (-1, 1):   # posts at the door and opposite, handrail and upper ring dark
        for a in (exit_angle + side * gap, exit_angle + math.pi + side * gap):
            rods(bm_frame, [at(a, radius + 0.03, floor_z), at(a, radius + 0.03, floor_z - height)], 0.04)
    for z in (floor_z - 1.0, floor_z - height):
        rods(bm_frame, [at(exit_angle + gap + (2 * math.pi - 2 * gap) * i / 36, radius - 0.08, z) for i in range(37)], 0.025)
    cab = mesh_object("Kabine im Achsrohr", bm, m_frame)
    glass_obj = mesh_object("Kabine im Achsrohr Glas", bm_glass, m_glass)
    frame_obj = mesh_object("Kabine im Achsrohr Pfosten", bm_frame, m_frame)
    door = mesh_object("Kabine im Achsrohr Tür", bm_door, m_glass)
    parts = (cab, glass_obj, frame_obj)
    for obj in parts:
        obj.rotation_mode = "QUATERNION"
    door.parent = cab   # slides about the axis of the cabin behind the wall
    # door opens as soon as the camera moves on after arriving (after hold 09.1), in 1.2 s; shut before
    moved = lambda k: (all_frames[k][0] - all_frames[k - 1][0]).length > 1e-4
    still = next((k for k in range(land + 1, len(all_frames)) if not moved(k)), None)   # hold 09.1: the cabin stands still
    opens = next((k for k in range(still, len(all_frames)) if moved(k)), None) if still is not None else None
    fps = scene.render.fps
    if opens is not None:
        start = max(land + 1, opens - round(1.2 * fps))
        for f, value in ((start, 0.0), (start + round(1.2 * fps), 2 * gap + math.radians(4))):
            door.rotation_euler = (0, 0, value)
            door.keyframe_insert("rotation_euler", index=2, frame=f + 1)
    first_on_axis = next((k for k, (loc, q) in enumerate(all_frames) if on_axis_of(loc)), None)
    for f, (loc, q) in enumerate(all_frames, 1):
        k = f - 1
        shown = first_on_axis is not None and k >= first_on_axis
        landed = k >= land
        for obj in parts:
            obj.location = land_loc if landed else (loc.copy() if shown else Vector((0, 0, SPOKE_Z)))
            obj.rotation_quaternion = Quaternion() if landed or not shown else (Quaternion(q) @ arrival.inverted())
            obj.hide_render = obj.hide_viewport = not shown
            obj.keyframe_insert("location", frame=f)
            obj.keyframe_insert("rotation_quaternion", frame=f)
            obj.keyframe_insert("hide_render", frame=f)
            obj.keyframe_insert("hide_viewport", frame=f)
        door.hide_render = door.hide_viewport = not shown
        door.keyframe_insert("hide_render", frame=f)
        door.keyframe_insert("hide_viewport", frame=f)
    from camera_moves import fcurves_of
    for obj in parts + (door,):
        for fc in fcurves_of(obj):
            for point in fc.keyframe_points:
                point.interpolation = "CONSTANT" if fc.data_path.startswith("hide") else ("BEZIER" if obj is door else "LINEAR")
    # rails: three guide rails on the axis from the bearing ring down to the lobby floor, not
    # in the direction of the exit; they belong to the standing hub and turn with it before decoupling (parent HUB_ROOT)
    bm_rails = bmesh.new()
    for k in range(3):
        a = exit_angle + math.pi + (k - 1) * math.radians(75)
        rods(bm_rails, [at(a, 2.45, SPOKE_Z + 1.0), at(a, 2.45, LOBBY_FLOOR)], 0.08)
    rails = mesh_object("Kabine im Achsrohr Schienen", bm_rails, m_frame)
    if HUB_ROOT is not None:
        rails.parent = HUB_ROOT
        rails.matrix_parent_inverse = Matrix.Rotation(HUB_TURN, 4, "Z").inverted()   # at the end the hub stands at HUB_TURN
    print(f"Kabine: landet bei Bild {land + 1}, Tür öffnet ab Bild {opens if opens is not None else '-'}, Ausstieg {math.degrees(exit_angle):.0f} Grad", flush=True)


def ride_preview(only, out_dir):
    """Preview of the ride through the panels only (in storyboard order): holds at the panel cameras, at a change of room
    a waypoint in the passage, motion according to the camera motion rules (camera_moves.build_path), focal length per hold;
    every 6 frames a check whether the camera is closer than 0.5 m to a surface (it then passes through a wall). Small and fast:
    640 x 360, 24 fps, 4 samples; result ride_preview.mp4 and ride_check.json in the ride folder."""
    from camera_moves import build_path
    fps = QUALITY["fps"]
    scene.render.fps = fps
    panels = [p for s in BOARD.get("scenes", []) for p in s.get("panels", []) if not only or p["id"] in only]
    # panel without a click along a ride (02.2): no hold, only a look-at point that the morph glides through (with holds the
    # sideways movement stepped from point to point; before, a 0.3 s hold)
    glide_through = lambda panel: not panel.get("click") and panel.get("move") == "track" and not panel.get("dwell_seconds")
    stops, lenses, previous = [], [], None
    for panel in panels:
        spec = panel["camera"]
        room = spec.get("room") if spec.get("frame") in ("room", "wall") else None
        vias = list(panel.get("via", []))
        # waypoints still in the previous room come before the passage (otherwise the camera turned close to the outer wall after
        # 05.9); the others follow the passage as before
        before = [v for v in vias if previous and room and previous != room and v.get("frame") in ("room", "wall") and v.get("room") == previous]
        after = [v for v in vias if v not in before]
        for k, via in enumerate(before):
            way = camera(board_point(via, "at", scale_height=False), board_point(via, "look", scale_height=True), via.get("lens", 22),
                         axis_up(board_point(via, "at", scale_height=False)))
            stops.append({"name": f"{panel['id']} via {k + 1}", "location": way.location.copy(), "rotation": way.rotation_euler.copy(),
                          "pass": True, "look_weight": 0.6 if via.get("look") and via.get("gaze", True) else 0.0})   # gaze: false, path only
            lenses.append(via.get("lens", 22))
        if previous and room and previous != room:
            way = passage_pose(previous, room)
            stops.append({"name": f"Durchgang {previous}-{room}", "location": way.location.copy(), "rotation": way.rotation_euler.copy(),
                          "pass": True, "look_weight": 0.4})   # waypoint without a hold (no stop in the door frame), brief look into the room
            lenses.append(22)
        for k, via in enumerate(after, len(before)):   # waypoints before the panel, given like a camera (around obstacles)
            location = board_point(via, "at", scale_height=False)
            if via.get("up") == "ahead" and via.get("frame") == "room":   # looking straight down, top of the image in walking direction
                u_, v_, phi_ = room_point(via["room"], *via["at"][:2])
                up = -ring_dir(u_, -math.sin(phi_), math.cos(phi_)).normalized()
            elif isinstance(via.get("up"), dict) and "toward" in via["up"]:   # up in the image points horizontally at a point (e.g. the
                aim = board_point(dict(via, look=via["up"]["toward"]), "look", scale_height=True) - location   # next target): when
                vertical = axis_up(location)   # rising from the straight-down view the camera then turns about one axis only
                up = (aim - vertical * aim.dot(vertical)).normalized()
            else:
                up = Vector(via["up"]) if via.get("up") else axis_up(location)   # spoke and hub define up themselves
            way = camera(location, board_point(via, "look", scale_height=True), via.get("lens", 22), up)
            stops.append({"name": f"{panel['id']} via {k + 1}", "location": way.location.copy(), "rotation": way.rotation_euler.copy(),
                          "pass": True, "look_weight": 0.6 if via.get("look") and via.get("gaze", True) else 0.0})   # gaze: false, path only
            lenses.append(via.get("lens", 22))
        cam = panel_pose(panel, lens=RIDE_LENS)
        # lens shift of the panel as a tilt: the ride camera has no shift, so otherwise the centre of its image lay lower than in
        # the panel (room 2: shift_y 0.144; the timeline must be in the middle of the image, not the floor with the upper
        # images cut off)
        shift_x, shift_y = float(spec.get("shift_x", 0.0)), float(spec.get("shift_y", 0.0))
        if shift_x or shift_y:
            sensor, lens_spec = cam.data.sensor_width, float(spec.get("lens", RIDE_LENS))
            turn = Quaternion((1, 0, 0), math.atan(shift_y * sensor / lens_spec)) @ Quaternion((0, 1, 0), -math.atan(shift_x * sensor / lens_spec))
            cam.rotation_euler = (cam.rotation_euler.to_quaternion() @ turn).to_euler("XYZ", cam.rotation_euler)
        stops.append({"name": panel["id"], "location": cam.location.copy(), "rotation": cam.rotation_euler.copy(),
                      "dwell_seconds": float(panel.get("dwell_seconds", 1.0 if panel.get("click") else 0.3)), "cut": panel.get("move") == "cut",
                      "pass": bool(panel.get("pass")) or glide_through(panel), "travel_seconds": panel.get("travel_seconds"), "approach_look": panel.get("approach_look"),
                      "zero_g": bool(panel.get("zero_g")),   # hub: floating instead of walking
                      "look_weight": 0.7 if panel.get("pass") or glide_through(panel) else 0.0})   # pass: panel without a hold
        # (elevator, which simply runs through); its gaze pulls the camera briefly, its speed applies to the section
        try:   # look-at point of the panel: on the way the camera already looks there (look to the side
            target = board_point(spec, "look", scale_height=True)   # while walking); at the centre of the panel's image
            cam_fwd = cam.rotation_euler.to_quaternion() @ Vector((0, 0, -1))   # (with shift), at the distance of the look-at point
            stops[-1]["look_at"] = cam.location + cam_fwd * max(0.5, (target - cam.location).length)
            # backwards only where the panel requires it: dolly out (07.3, 07.4) and crane move into the cabin (08.x; the camera never
            # turns round there, it keeps moving backwards); otherwise one first looks at the target and walks forwards (01.1 to 01.4)
            stops[-1]["backward_ok"] = panel.get("move") in ("dolly out", "crane up", "crane down")
        except (KeyError, TypeError, ValueError):
            pass
        if panel.get("max_speed"):   # justified exception to the rule against walking backwards (e.g. outside shots without anything to bump into)
            stops[-1]["max_speed"], stops[-1]["max_speed_reason"] = panel["max_speed"], panel.get("max_speed_reason", "")
        lenses.append(spec.get("lens", 24))
        previous = room or previous
    # pose fixed in the cabin: the camera does not turn until leaving the elevator and keeps looking at the same point of the
    # glass elevator door: from the panel with cabin_view: lock to the one with cabin_view: release all holds and waypoints
    # carry its pose
    by_id = {p["id"]: p for p in panels}
    locked_rotation = None
    for stop in stops:
        view = by_id.get(stop["name"], {}).get("cabin_view")
        if view == "release" and locked_rotation is not None and by_id[stop["name"]].get("cabin_turn") == "steady":
            # arrival in the pose of the cabin, only righted (shortest rotation from the cabin's up to the
            # panel's up); the bar then lies in front (hub_root_object), the view to the panel follows only on exit (09.1b)
            q_lock, q_panel = locked_rotation.to_quaternion(), stop["rotation"].to_quaternion()
            q_up = (q_lock @ Vector((0, 1, 0))).rotation_difference(q_panel @ Vector((0, 1, 0)))
            stop["rotation"] = (q_up @ q_lock).to_euler("XYZ", stop["rotation"])
            stop.pop("look_at", None)
        if view == "release":   # the panel with release keeps its pose (lobby, up -z): between the last fixed hold (08.4) and
            locked_rotation = None   # it the cabin tilts in the axis tube, the cabin model turns with the camera
        if locked_rotation is not None:
            stop["rotation"], stop["locked"] = locked_rotation.copy(), True
            stop.pop("look_at", None)
        if view == "lock":
            locked_rotation = stop["rotation"].copy()
        elif view == "release":
            locked_rotation = None
    for k in range(1, len(stops)):   # keep Euler angles continuous, otherwise the camera turns the long way round
        stops[k]["rotation"].make_compatible(stops[k - 1]["rotation"])
    rider = camera(stops[0]["location"], stops[0]["location"] + Vector((0, 0, -1)), RIDE_LENS)   # one focal length
    rider.name = "Fahrtkamera"
    rider.rotation_mode = "QUATERNION"
    segments = [[]]   # a cut (move: cut) starts a new section one frame after the last hold: hard cut, no flight
    for stop in stops:   # through modules or hundreds of metres of outer space
        if stop.get("cut") and segments[-1]:
            segments.append([])
        segments[-1].append(stop)
    # walking like a person (ride_motion.walk_segment): constant walking speed over waypoints, braking only before a
    # hold, looking ahead with a limited rotation rate, walking profile; per frame position and rotation (quaternion), horizon from ride_up
    from camera_moves import fcurves_of, horizontal_fov
    from ride_motion import walk_segment
    rules, profile = dict(CONFIG["motion_rules"]), dict(CONFIG["walk_profile"])
    timeline, overrides, first, all_frames = [], [], 1, []
    for segment in segments:
        frames_seg, part, over = walk_segment(segment, fps, profile, rules, horizontal_fov(rider), ride_up, first)
        if timeline:   # the cut itself is a jump over one frame, not a move (for check_motion.py)
            overrides.append({"start": first - 1, "end": first, "max_speed": 1e9, "reason": f"Schnitt zu {part[0]['name']}"})
        timeline += part
        overrides += over
        all_frames += frames_seg
        first = part[-1]["frame"] + 1
    scene["speed_overrides"] = json.dumps(overrides)
    # Cabin in the axis tube: one continuous rotation that prepares the view forwards: before a panel with cabin_turn:
    # steady the camera turns evenly from the last hold to the arrival (slerp with smoothstep) into the pose of the panel;
    # the path stays that of walk_segment, only the rotation is replaced
    named = [s for s in timeline if s["name"] in by_id]
    for before, stop in zip(named, named[1:]):
        if by_id[stop["name"]].get("cabin_turn") != "steady":
            continue
        a, b = before["frame"], stop["arrive"]   # frame numbers from 1
        q_a, q_b = all_frames[a - 1][1].copy(), all_frames[b - 1][1].copy()
        if q_a.dot(q_b) < 0:
            q_b.negate()
        for f in range(a, b + 1):
            u = (f - a) / max(1, b - a)
            all_frames[f - 1] = (all_frames[f - 1][0], q_a.slerp(q_b, u * u * (3 - 2 * u)))
        print(f"Kabine: gleichmäßige Drehung {math.degrees(q_a.rotation_difference(q_b).angle):.0f} Grad von {before['name']} bis "
              f"{stop['name']} in {(b - a) / fps:.1f} s", flush=True)
    previous_q = None
    for f, (loc, q) in enumerate(all_frames, 1):
        if previous_q is not None and q.dot(previous_q) < 0:
            q = -q   # same orientation, same sign: otherwise the curve jumps between two sections (double cover)
        rider.location = loc
        rider.rotation_quaternion = q
        rider.keyframe_insert("location", frame=f)
        rider.keyframe_insert("rotation_quaternion", frame=f)
        previous_q = q
    for fc in fcurves_of(rider):
        for point in fc.keyframe_points:
            point.interpolation = "LINEAR"
    passing = {s["name"] for s in stops if s.get("pass")}
    for stop in timeline:   # markers only at real holds: there check_motion.py checks for stillness; waypoints are passed through
        stop["pass"] = stop["name"] in passing
        if not stop["pass"]:
            scene.timeline_markers.new(stop["name"], frame=stop["frame"])
    # doors during the ride: the main door and the door from room 6 swing open (opens_door), the cabin door slides (cabin_door)
    by_name = {p["id"]: p for p in panels}
    # main door: shut until the panel with opens_door: main (06.4), where it opens in the two seconds before arrival, so the
    # visitor walks through and opens the door; without the field it opens before the first panel of the centre room (scene 7)
    opener = next((s for s in timeline if by_name.get(s["name"], {}).get("opens_door") == "main"), None)
    if opener is None:
        opener = next((s for s in timeline if s["name"].startswith("07.") and s["name"] in by_name), None)
    set_main_door(0.0, frame=1)
    if opener is not None:   # open before the camera reaches the plane of the door (otherwise leaf a was 0.08 m in front of the camera at 2 s)
        set_main_door(0.0, frame=max(1, opener["arrive"] - 5 * fps))
        set_main_door(DOOR_OPEN_DEG, frame=max(2, opener["arrive"] - int(2.5 * fps)))
    # door from room 6: shut until the panel with opens_door: room6, then it opens in the seconds before, like the main door
    r6_opener = next((s for s in timeline if by_name.get(s["name"], {}).get("opens_door") in ("room6", "r6")), None)
    # opens_door_on_leave: r6: shut during the hold at this panel; after the click (end of the hold) the door swings open in
    # R6_OPEN_SECONDS while the camera starts moving through it
    r6_leave = next((s for s in timeline if by_name.get(s["name"], {}).get("opens_door_on_leave") in ("room6", "r6")), None)
    R6_OPEN_SECONDS = 2.0
    set_room6_door(0.0, frame=1)
    if r6_leave is not None:
        set_room6_door(0.0, frame=r6_leave["frame"])
        set_room6_door(DOOR_OPEN_DEG, frame=r6_leave["frame"] + int(R6_OPEN_SECONDS * fps))
    elif r6_opener is not None:
        set_room6_door(0.0, frame=max(1, r6_opener["arrive"] - 5 * fps))
        set_room6_door(DOOR_OPEN_DEG, frame=max(2, r6_opener["arrive"] - int(2.5 * fps)))
    # Cabin door: slides between the positions of the panels (cabin_door, default open). It opens before arrival, like the
    # main door (open before the camera reaches the plane of the door), and closes only after arrival, during the hold at the
    # panel, i.e. behind the camera that is already standing in the cabin (otherwise the camera seemed to glide through the glass door)
    cabin_keys = [obj.data.shape_keys.key_blocks["offen"] for obj in (bpy.data.objects.get(f"Kabinentür {part}") for part in ("Glas", "Rahmen"))
                  if obj is not None and obj.data.shape_keys]
    slide = int(CABIN_DOOR_SECONDS * fps)
    current = CABIN_DOOR_OPEN["open"]
    for key in cabin_keys:
        key.value = current
        key.keyframe_insert("value", frame=1)
    for stop in timeline:
        panel = by_name.get(stop["name"])
        if panel is None:
            continue
        wanted = CABIN_DOOR_OPEN[panel.get("cabin_door", "open")]
        if wanted == current:
            continue
        if wanted < current:   # closes during the hold: adapts to the hold (1 to 1.5 s), so that it is shut before departure
            start, length = stop["arrive"], max(fps, min(slide, stop["frame"] - stop["arrive"]))
        else:
            start, length = max(2, stop["arrive"] - int(2.5 * fps) - slide), slide
        for key in cabin_keys:
            key.value = current
            key.keyframe_insert("value", frame=start)
            key.value = wanted
            key.keyframe_insert("value", frame=start + length)
        current = wanted
    # Turning the pages of the book during the ride: as in the book of an earlier library ride, one leaf turns about the fold
    # per click; the front is the old right page, the back the new left page. Below, the new right page already lies on the
    # right; on the left the page changes when the leaf comes to rest. The leaf starts with the clip after the click (end of the
    # previous hold) and ends after FLIP_SECONDS, at the latest at the end of the hold. The first panel with book swaps without
    # turning (it shows the title page).
    FLIP_SECONDS = 0.9
    book_stops = [(i, s, by_name[s["name"]]) for i, s in enumerate(timeline) if s["name"] in by_name and by_name[s["name"]].get("book")]

    def key_visible(obj, frame, visible):
        obj.hide_render = obj.hide_viewport = not visible
        obj.keyframe_insert("hide_render", frame=frame)
        obj.keyframe_insert("hide_viewport", frame=frame)

    def page_copy(plane, path, tag):
        dup = plane.copy()
        dup.animation_data_clear()   # copy() shares the action of the original: otherwise all visibility keys would act on all pages
        dup.data = plane.data.copy()
        dup.data.materials[0] = plane.data.materials[0].copy()
        for node in dup.data.materials[0].node_tree.nodes:
            if node.type == "TEX_IMAGE":
                node.image = bpy.data.images.load(path, check_existing=True)
        dup.name = f"{plane.name} {tag}"
        scene.collection.objects.link(dup)
        return dup

    for lectern_key in sorted({p.get("book_lectern") or "pages" for _, _, p in book_stops}):
        left0, right0 = BOOK.get(lectern_key, (None, None))
        if left0 is None or right0 is None:
            continue
        spine, X, d, n_s, page = BOOK_GEOM[lectern_key]
        axis = X.cross(n_s).normalized()   # turns the right page over n_s (upwards) to the left
        stops = [(i, s, p) for i, s, p in book_stops if (p.get("book_lectern") or "pages") == lectern_key]
        switched = []   # all faces with visibility keys, set to CONSTANT at the end
        i0, s0, p0 = stops[0]
        shown = [page_copy(left0, p0["book"][0], p0["id"]), page_copy(right0, p0["book"][1], p0["id"])]
        for obj in (left0, right0):
            key_visible(obj, 1, True)
            key_visible(obj, s0["arrive"], False)
        for obj in shown:
            key_visible(obj, 1, False)
            key_visible(obj, s0["arrive"], True)
        switched += [left0, right0] + shown
        old_right = p0["book"][1]
        for i, stop, panel in stops[1:]:
            f0 = timeline[i - 1]["frame"] + 1
            f1 = max(f0 + 2, min(f0 + round(FLIP_SECONDS * fps), stop["frame"]))
            if stop["frame"] - f0 < round(FLIP_SECONDS * fps):
                print(f"Warnung: Halt {stop['name']} zu kurz zum Umblättern ({(stop['frame'] - f0) / fps:.2f} s, dwell_seconds erhöhen)")
            new_left, new_right = page_copy(left0, panel["book"][0], panel["id"]), page_copy(right0, panel["book"][1], panel["id"])
            for obj in (new_left, new_right):
                key_visible(obj, 1, False)
            key_visible(shown[1], f0, False)
            key_visible(new_right, f0, True)
            key_visible(shown[0], f1, False)
            key_visible(new_left, f1, True)
            # the leaf: hinge at the fold 3 mm above the pages, front and back 1 mm apart. When upright it curls towards the fold
            # (half width): fully upright it rose 0.42 m high and came within 0.39 m of the camera at the lectern; below clip_start
            # 0.5 m it would be cut off at the top
            hinge_at = spine + n_s * 0.003
            hinge = bpy.data.objects.new(f"Blatt {lectern_key} {panel['id']}", None)
            scene.collection.objects.link(hinge)
            hinge.location = hinge_at
            hinge.rotation_mode = "AXIS_ANGLE"
            roll = bpy.data.objects.new(f"Blatt Rollen {lectern_key} {panel['id']}", None)   # local x axis across the page
            scene.collection.objects.link(roll)
            roll_world = Matrix.Translation(hinge_at) @ Matrix((X, -d, X.cross(-d))).transposed().to_4x4()
            roll.matrix_world = roll_world
            roll.parent = hinge
            roll.matrix_parent_inverse = Matrix.Translation(hinge_at).inverted()
            front = image_plane(f"Blatt vorn {panel['id']}", old_right, hinge_at + X * (page[0] / 2) + n_s * 0.0005, X, -d, page)
            back = image_plane(f"Blatt hinten {panel['id']}", panel["book"][0], hinge_at + X * (page[0] / 2) - n_s * 0.0005, -X, -d, page)
            for leaf in (front, back):
                leaf.parent = roll
                leaf.matrix_parent_inverse = roll_world.inverted()
                key_visible(leaf, 1, False)
                key_visible(leaf, f0, True)
                key_visible(leaf, f1, False)
            mid = (f0 + f1) // 2
            for frame, angle, width in ((1, 0.0, 1.0), (f0, 0.0, 1.0), (mid, math.pi / 2, 0.5), (f1, math.pi, 1.0)):
                hinge.rotation_axis_angle = (angle, *axis)
                hinge.keyframe_insert("rotation_axis_angle", frame=frame)
                roll.scale = (width, 1.0, 1.0)
                roll.keyframe_insert("scale", frame=frame)
            switched += [new_left, new_right, front, back]
            shown, old_right = [new_left, new_right], panel["book"][1]
        # visibility jumps; via fcurves_of, because in Blender 5 an action no longer has fcurves (curves live in layers): before,
        # the loop stayed empty, the keys slid from frame 1 to the change, and the later double pages already lay on top from
        # halfway (probably also why the earlier image swap never visibly turned a page)
        from camera_moves import fcurves_of
        for obj in switched:
            for fcurve in fcurves_of(obj):
                for point in fcurve.keyframe_points:
                    point.interpolation = "CONSTANT"
    # Videos play during the ride: panels with video: get the clip as a moving texture, starting when their room is entered
    # (first panel of the scene), looping; the clip's frame rate runs at the scene frame rate (preview 24 fps: a little
    # slower than real, final version 30 fps)
    room_entry = {}
    for stop in timeline:
        panel = by_name.get(stop["name"])
        if panel is None:
            continue
        cam_spec = panel["camera"]
        room_key = cam_spec.get("room") if cam_spec.get("frame") in ("room", "wall") else None
        if room_key is not None and room_key not in room_entry:
            room_entry[room_key] = stop["arrive"]
    # video_from: <panel> starts the clip at 0:00 as soon as the ride towards that panel begins (when started on entering the
    # room, it was already in the middle of the loop at the last panel of room 5)
    leg_start = {s["name"]: (timeline[k - 1]["frame"] if k else s["arrive"]) for k, s in enumerate(timeline)}
    for item in BOARD.get("placeholders", []):
        if not item.get("video"):
            continue
        plane = bpy.data.objects.get(f"Platzhalter {item['id']}")
        clip_path = BASE / item["video"]
        if plane is None or not clip_path.exists() or not plane.data.materials:
            print(f"Video für {item['id']} nicht gesetzt ({clip_path.name})", flush=True)
            continue
        movie = bpy.data.images.load(str(clip_path), check_existing=True)
        for node in plane.data.materials[0].node_tree.nodes:
            if node.type == "TEX_IMAGE":
                node.image = movie
                start = leg_start.get(str(item["video_from"])) if item.get("video_from") else None
                node.image_user.frame_start = int(start if start is not None else room_entry.get(item.get("room"), 1))
                node.image_user.frame_duration = max(1, movie.frame_duration)
                node.image_user.frame_offset = 0
                node.image_user.use_cyclic = True
                node.image_user.use_auto_refresh = True
    scene.camera = rider
    scene.frame_start, scene.frame_end = 1, timeline[-1]["frame"]
    spin_station(timeline, fps, by_name)   # ring relative to hub
    cabin_follow(all_frames)   # cabin in the axis tube
    print(f"Fahrt: {len(stops)} Halte, {scene.frame_end} Bilder, {scene.frame_end / fps:.0f} s", flush=True)
    sync_viewport()
    problems = []
    for f in range(1, scene.frame_end + 1, 6):
        scene.frame_set(f)
        near, name = nearest_in_view(rider)
        if near is not None and near < CLEAR:
            problems.append({"frame": f, "second": round(f / fps, 1), "nearest_m": round(near, 2), "surface": name})
    if "--debug-frames" in ARGS:   # debugging: pose of the ride camera at single frames (e.g. 4020,4021,4022,4023)
        for f in (int(x) for x in ARGS[ARGS.index("--debug-frames") + 1].split(",")):
            scene.frame_set(f)
            print(f"Pose {f}: Ort {tuple(round(c, 2) for c in rider.location)}, Euler {tuple(round(math.degrees(a), 1) for a in rider.rotation_euler)}",
                  flush=True)
        print("Halte um diese Bilder:", [(s["name"], s["arrive"], s["frame"]) for s in timeline if 3900 < s["frame"] < 4200], flush=True)
    from check_motion import check_scene   # camera motion rules (speed, pan, stillness at holds, horizon), result next to the distance
    motion = check_scene(scene, CONFIG["motion_rules"], up_at=ride_up)
    # Ring: up to 25 m above the floor (elevator up to 18 m; at 40 m the outside ride 10.1 to 10.2 still counted as ring), up towards the axis; spoke and hub up to 150 m from the axis: up is the world axis as
    # in the panels; in between and outside (10.1 to 10.3, the station in space) there is no horizon and no check there (justified
    # exception to the horizon rule; the move between two level poses rolls by up to 8 degrees there, without reference in space)
    print(f"Bewegtbild-Prüfung: {len([f for f in motion if not f.get('hint')])} Verstöße, "
          f"{len([f for f in motion if f.get('hint')])} Hinweise", flush=True)
    for finding in [f for f in motion if not f.get("hint")][:12]:
        print("  ", finding, flush=True)
    own_out = out_dir.resolve() != (BASE / "_scratch" / "storyboard").resolve()   # --out set: parallel sessions render into their
    ride_dir = out_dir if "--no-render" in ARGS or own_out else BASE / QUALITY["output"]   # own folder; check runs (--no-render --out ...) write into their
    # own folder, otherwise they overwrote ride_check.json next to the rendered video
    # every run gets its own empty frame folder, so no outdated render gets appended: before, ffmpeg read all f_*.jpg in
    # frames/, including the 12 008 frames of an older, longer run
    frames = ride_dir / f"frames_{time.strftime('%Y%m%d_%H%M%S')}"
    frames.mkdir(parents=True, exist_ok=True)
    (ride_dir / "ride_check.json").write_text(json.dumps({"stops": timeline, "too_close": problems, "motion": motion}, indent=1,
                                                         ensure_ascii=False, default=str), encoding="utf-8")
    # path per frame (position, quaternion w x y z) for debugging without Blender (e.g. a rotation jump in the middle of the path)
    (ride_dir / "ride_path.json").write_text(json.dumps([[f, *[round(c, 4) for c in loc], *[round(c, 5) for c in q]]
                                                         for f, (loc, q) in enumerate(all_frames, 1)]), encoding="utf-8")
    print(f"Prüfung der Fahrt: {len(problems)} Stellen näher als {CLEAR} m an einer Fläche", flush=True)
    for p in problems:
        stop = next((s["name"] for s in timeline if s["arrive"] >= p["frame"]), "Ende")
        print(f"  Bild {p['frame']} ({p['second']} s, vor Halt {stop}): {p['nearest_m']} m an {p['surface']}", flush=True)
    if "--credit-frames" in ARGS:   # visibility of third-party works per frame for the credit in the chat (from the frame
        # in which the work appears): pre-check as per panel (share of the image, line of sight), then a grid of points over the
        # image area; the work only counts once at least CREDIT_MIN_VISIBLE of the points are in the image and visible. A single
        # free corner through the door (passage 2-3, about 1 s too early) and a cut-off remainder at the edge do not count.
        from bpy_extras.object_utils import world_to_camera_view
        CREDIT_MIN_VISIBLE = 0.25

        def visible_fraction(cam, item_id, prefix):
            best = 0.0
            for obj in item_objects(item_id, prefix):
                lo = [min(c[k] for c in obj.bound_box) for k in range(3)]
                hi = [max(c[k] for c in obj.bound_box) for k in range(3)]
                a, b = sorted(range(3), key=lambda k: hi[k] - lo[k])[1:]   # the two largest extents = the image area
                thin = 3 - a - b
                points = []
                for u in (0.1, 0.3, 0.5, 0.7, 0.9):
                    for v in (0.1, 0.3, 0.5, 0.7, 0.9):
                        local = [0.0, 0.0, 0.0]
                        local[a], local[b] = lo[a] + u * (hi[a] - lo[a]), lo[b] + v * (hi[b] - lo[b])
                        local[thin] = (lo[thin] + hi[thin]) / 2
                        points.append(obj.matrix_world @ Vector(local))
                seen = 0
                for p in points:
                    c = world_to_camera_view(scene, cam, p)
                    if not (c.z > 0 and 0 <= c.x <= 1 and 0 <= c.y <= 1):
                        continue
                    ray = p - cam.location
                    d, name = ray_hit(cam.location, ray.normalized(), ray.length + 0.05)
                    if d is None or name.endswith(" " + item_id) or d >= ray.length - 0.15:
                        seen += 1
                best = max(best, seen / len(points))
            return best

        credited = [p for p in BOARD.get("placeholders", []) if p.get("credit")]
        runs, started = {}, time.time()
        for f in range(1, len(all_frames) + 1):
            scene.frame_set(f)
            cam = scene.camera
            for p in credited:
                if screen_share(cam, p["id"], credit_prefix(p)) < CREDIT_MIN_SHARE or not visible_in(cam, p["id"], credit_prefix(p)) \
                        or visible_fraction(cam, p["id"], credit_prefix(p)) < CREDIT_MIN_VISIBLE:
                    continue
                work = credit_side(cam, p)
                spans = runs.setdefault(work, [])
                if spans and spans[-1][1] == f - 1:
                    spans[-1][1] = f
                else:
                    spans.append([f, f])
            if f % 500 == 0:
                print(f"Nennung je Bild: {f} von {len(all_frames)} ({time.time() - started:.0f} s)", flush=True)
        (ride_dir / "credit_frames.json").write_text(json.dumps(
            {"stops": timeline, "frames": runs, "panel_credits": {p["id"]: p["credits"] for p in panels if p.get("credits")}},
            indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"Nennung je Bild: {ride_dir / 'credit_frames.json'}, {sum(len(v) for v in runs.values())} Zeiträume", flush=True)
    if "--no-render" in ARGS and not ("--segments" in ARGS and "--cull" in ARGS):   # path and check only, in seconds instead of minutes;
        return   # with --segments --cull continue up to the plan of hiding per segment, without rendering
    scene.render.resolution_x, scene.render.resolution_y = QUALITY["width"], QUALITY["height"]
    scene.eevee.taa_render_samples = QUALITY["samples"]
    scene.render.filepath = str(frames / "f_")
    scene.render.image_settings.file_format = QUALITY["format"]
    if QUALITY.get("jpeg_quality"):   # final quality as JPEG 95 (config.yaml, to save storage space)
        scene.render.image_settings.quality = int(QUALITY["jpeg_quality"])
    # --frame-step N: only every Nth frame, the duration stays real (e.g. the whole ride at about four fps)
    step = int(ARGS[ARGS.index("--frame-step") + 1]) if "--frame-step" in ARGS else 1
    scene.frame_step = step
    # --frame-range a:b[,c:d]: only these frame ranges of the ride, one after the other in one video (render only what is to
    # be shown); ranges e.g. from ride_check.json of a check run without rendering
    # --frame-range stops: per real hold the frame on arrival, additionally under the name of the panel in halts/ (all relevant
    # frames along the planned path in high quality; with --quality final)
    wanted = ARGS[ARGS.index("--frame-range") + 1] if "--frame-range" in ARGS else None
    halts = [s for s in timeline if not s.get("pass")] if wanted == "stops" else []
    # limits also as panel names (05.2:05.6): end of the hold before the first panel to the end of the last, from the schedule of
    # this run; frame numbers shift as soon as someone changes the ride before them (two tests missed the book that way)
    stop_frames = {s["name"]: (timeline[k - 1]["frame"] if k else s["arrive"], s["frame"]) for k, s in enumerate(timeline)}

    def bound(value, end):
        return stop_frames[value][end] if value in stop_frames else int(value)

    ranges = [(s["arrive"], s["arrive"]) for s in halts] if halts else \
        [(bound(r.split(":")[0], 0), bound(r.split(":")[1], 1)) for r in wanted.split(",")] if wanted else [(scene.frame_start, scene.frame_end)]
    if "--segments" in ARGS:   # final render click by click, so that
        render_segments(timeline, all_frames, ranges, ride_dir)   # decisions and updates can be made
        return                                                    # per segment
    for first_f, last_f in ranges:
        scene.frame_start, scene.frame_end = first_f, min(last_f, len(all_frames))
        bpy.ops.render.render(animation=True)
    extension = "jpg" if QUALITY["format"] == "JPEG" else "png"
    if halts:
        (ride_dir / "halts").mkdir(exist_ok=True)
        for s in halts:
            source = frames / f"f_{s['arrive']:04d}.{extension}"
            if source.exists():
                shutil.copy2(source, ride_dir / "halts" / f"{s['name'].replace('.', '_')}.{extension}")
    rendered = sorted(frames.glob(f"f_*.{extension}"))
    listing = frames / "frames.txt"   # concat list: gaps at frame_step > 1 break the pattern f_%04d
    listing.write_text("".join(f"file '{p.name}'\nduration {step / fps}\n" for p in rendered) + f"file '{rendered[-1].name}'\n",
                       encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-r", str(max(1, round(fps / step))), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "26" if QUALITY["format"] == "JPEG" else "16", str(ride_dir / "master.mp4")], check=True)
    shutil.copy2(ride_dir / "master.mp4", ride_dir / "ride_preview.mp4")   # master.mp4 for the slide deck builder (station_ride_preview)
    print("geschrieben:", ride_dir / "master.mp4", flush=True)


def render_segments(timeline, all_frames, ranges, ride_dir):
    """One segment per click in ride_dir/segments/<from>_<to>/ (frame numbers of the whole ride); existing frames stay (aborting
    costs nothing, the next run continues). segment.json carries a fingerprint of the segment's path: if it changes (someone
    shifted the ride before it) or the segment is listed in --redo (scene changed, e.g. the lecterns), the old folder moves to
    segments/_old/ (nothing is deleted). --seed-frames <folder>: take over finished frames of an earlier run with the same path."""
    import hashlib
    clicks = {p["id"] for s in BOARD.get("scenes", []) for p in s.get("panels", []) if p.get("click")}
    pieces, prev_name, prev_frame = [], "start", 0
    for s in timeline:
        if s["name"] in clicks and not s.get("pass") and s["frame"] > prev_frame:
            pieces.append((f"{prev_name}_{s['name']}", s["name"], prev_frame + 1, s["frame"]))
            prev_name, prev_frame = s["name"], s["frame"]
    if prev_frame < len(all_frames):
        pieces.append((f"{prev_name}_end", "end", prev_frame + 1, len(all_frames)))
    redo = set(ARGS[ARGS.index("--redo") + 1].split(",")) if "--redo" in ARGS else set()
    seed = Path(ARGS[ARGS.index("--seed-frames") + 1]) if "--seed-frames" in ARGS else None
    lo, hi = min(r[0] for r in ranges), max(r[1] for r in ranges)
    root, extension = ride_dir / "segments", "jpg" if QUALITY["format"] == "JPEG" else "png"
    scene.render.use_overwrite = False   # skip existing frames
    dry, groups = "--no-render" in ARGS, cull_groups() if "--cull" in ARGS else {}
    order = [p for p in pieces if not (p[3] < lo or p[2] > hi)]
    if "--order" in ARGS and ARGS[ARGS.index("--order") + 1] == "biggest":   # longest clicks first, so that the large segments run
        order.sort(key=lambda p: p[3] - p[2], reverse=True)                  # and the remaining ones get smaller; an abort hits small ones
    if "--shard" in ARGS:   # k/n: several runs share the segments alternately, without overlap
        k, n = (int(x) for x in ARGS[ARGS.index("--shard") + 1].split("/"))
        order = order[k::n]
    for name, end_name, first, last in order:
        culled =[g for g in groups if not group_seen(groups[g], first, last)] if groups else []
        if dry:   # plan only: which areas are dropped per segment, nothing is created or rendered
            print(f"Stück {name}: Bilder {first} bis {last}, ausgeblendet: {', '.join(culled) or 'nichts'}", flush=True)
            continue
        folder, meta = root / name, root / name / "segment.json"
        path = [[round(c, 4) for c in loc] + [round(c, 5) for c in q] for loc, q in all_frames[first - 1:last]]
        fingerprint = hashlib.sha1(json.dumps(path).encode()).hexdigest()[:12]
        old = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else None
        if folder.exists() and (name in redo or end_name in redo or (old and old.get("fingerprint") != fingerprint)):
            (root / "_old").mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), str(root / "_old" / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}"))
            print(f"Stück {name}: alter Stand nach _old ({'--redo' if name in redo or end_name in redo else 'Bahn geändert'})", flush=True)
        folder.mkdir(parents=True, exist_ok=True)
        if seed and seed.is_dir():
            for f in range(first, last + 1):
                source = seed / f"f_{f:04d}.{extension}"
                if source.exists() and not (folder / source.name).exists():
                    shutil.copy2(source, folder / source.name)
        meta.write_text(json.dumps({"name": name, "first": first, "last": last, "frames": last - first + 1, "fps": QUALITY["fps"],
                                    "quality": {k: QUALITY[k] for k in ("width", "height", "samples")}, "fingerprint": fingerprint,
                                    "hub_turn": round(HUB_TURN, 4),   # state of the hub: seam jump if neighbours with the hub in view differ
                                    "culled": culled,   # hidden areas (--cull); empty without --cull
                                    "written": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1), encoding="utf-8")
        # Still hold at the end of the segment: staring at one image for nine seconds need not be rendered nine times thirty
        # times, so still frames are used when the image does not change. From the hold of the click panel first only arrival,
        # middle and departure are rendered; if they differ (video, book, globe), the rest follows. Otherwise the inside of the
        # hold is missing, and the deck builder ends the clip on the arrival frame (hold_moves then returns None);
        # PowerPoint stays there. Only the hold at the end: holds in the middle of a segment are needed in full by the deck.
        if len(list(folder.glob(f"f_*.{extension}"))) >= last - first + 1:   # already fully rendered (e.g. an overnight run)
            print(f"Stück {name}: Bilder {first} bis {last}, alle schon da", flush=True)
            continue
        tail = next((s for s in timeline if s["name"] == end_name and not s.get("pass")), None)
        hold = (tail["arrive"], last) if tail and first <= tail["arrive"] and last - tail["arrive"] >= 2 * QUALITY["fps"] else None
        wanted = list(range(first, last + 1))
        if hold:
            keep = {hold[0], (hold[0] + hold[1]) // 2, hold[1]}
            wanted = [f for f in wanted if not (hold[0] < f < hold[1]) or f in keep]

        def path_of(f):
            return folder / f"f_{f:04d}.{extension}"

        def render_frames(numbers):
            for f in numbers:
                if path_of(f).exists():
                    continue
                scene.frame_set(f)
                scene.render.filepath = str(path_of(f))
                bpy.ops.render.render(write_still=True)

        def hold_still(a, m, b):
            """Mean difference (0 to 255) between arrival, middle and departure below the deck's threshold (still_threshold)?"""
            import numpy
            def pixels(f):
                image = bpy.data.images.load(str(path_of(f)))
                data = numpy.empty(len(image.pixels), dtype=numpy.float32)
                image.pixels.foreach_get(data)
                bpy.data.images.remove(image)
                return data.reshape(-1, 4)[:, :3].mean(axis=1) * 255
            base = pixels(a)
            return all(float(numpy.abs(base - pixels(n)).mean()) <= 1.0 for n in (m, b))

        done = len([f for f in wanted if path_of(f).exists()])
        print(f"Stück {name}: Bilder {first} bis {last}, {done} von {len(wanted)} schon da"
              f"{f', Halt {hold[0]} bis {hold[1]} zuerst nur drei Bilder' if hold else ''}, ausgeblendet: {', '.join(culled) or 'nichts'}",
              flush=True)
        before = {obj.name: obj.hide_render for g in culled for obj in groups[g]}
        for g in culled:
            for obj in groups[g]:
                obj.hide_render = True
        started = time.perf_counter()
        still = None
        try:
            render_frames(wanted)
            if hold:
                still = hold_still(hold[0], (hold[0] + hold[1]) // 2, hold[1])
                if not still:   # something moves during the hold: render it fully
                    wanted = list(range(first, last + 1))
                    render_frames(wanted)
        finally:   # restore, also on abort: the next segment checks and renders with the whole scene
            for g in culled:
                for obj in groups[g]:
                    obj.hide_render = before[obj.name]
        meta_data = json.loads(meta.read_text(encoding="utf-8"))
        meta_data["frames"] = len(wanted)   # deck builder: done when this many frames exist
        meta_data["still_hold"] = [hold[0], hold[1]] if hold and still else None
        meta.write_text(json.dumps(meta_data, indent=1), encoding="utf-8")
        print(f"Stück {name} fertig: {(time.perf_counter() - started) / max(1, len(wanted) - done):.1f} s je Bild"
              f"{f', stiller Halt: {hold[1] - hold[0] - 2} Bilder gespart' if hold and still else ''}", flush=True)


def cull_groups():
    """Areas a segment may hide entirely (--cull): "hub" is everything at the standing hub (lobby, map room, modules, tube
    railway, hangar) except the stars, plus the lights there; "museum" are the parts on the rotor in the ring (rooms,
    placeholders r1_ to r7_, data tree, square, elevators, museum lights) except the parts that span the whole ring (ring,
    floor, houses, streets, roof: one object, visible from everywhere) and the spokes with the bearing ring. The sun and cameras always stay."""
    def ancestors(obj):
        while obj.parent is not None:
            obj = obj.parent
            yield obj
    rim_low = -float(STATION.get("rim_depth", 150)) - 2
    hub, museum = [], []
    for obj in scene.objects:
        if obj.type == "CAMERA" or obj.name.startswith("Stern") or (obj.type == "LIGHT" and obj.data.type == "SUN"):
            continue
        up = list(ancestors(obj))
        if HUB_ROOT is not None and HUB_ROOT in up:
            hub.append(obj)
            continue
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box] if obj.type in ("MESH", "CURVE", "FONT") else [obj.matrix_world.translation]
        span = max(max(c[i] for c in corners) - min(c[i] for c in corners) for i in (0, 1))
        centre = sum(corners, Vector()) / len(corners)
        radial = math.hypot(centre.x, centre.y)
        if rotor in up or obj is rotor:
            if span < 100 and radial > R - RIM - 2 and rim_low < centre.z < 2 and not obj.name.startswith(("Speiche", "Lagerkranz")):
                museum.append(obj)
        elif obj.type == "LIGHT" and radial < R - RIM - 2:   # lobby and map room lights are not parented to the hub (hub_root_object)
            hub.append(obj)
    return {"hub": hub, "museum": museum}


def group_seen(objects, first, last, step=6):
    """Is an area visible anywhere in the frames first to last? Every sixth frame and the last; per object centre and corners
    of the bounding box in the field of view (with margin), then the line of sight from the camera to there (ray_hit, glass
    counts as transparent): clear, or hitting a part of the area first, means seen. Lights count by their location; the check
    does not see reflections and shadows outside the field of view."""
    from bpy_extras.object_utils import world_to_camera_view
    names = {obj.name for obj in objects}
    local = [(obj, [Vector(c) for c in obj.bound_box] + [sum((Vector(c) for c in obj.bound_box), Vector()) / 8]
              if obj.type in ("MESH", "CURVE", "FONT") else [Vector()]) for obj in objects]
    sync_viewport()
    cam, margin = scene.camera, 0.15
    for f in sorted(set(range(first, last + 1, step)) | {last}):
        scene.frame_set(f)
        origin, rays = cam.matrix_world.translation.copy(), 0
        for obj, points in local:
            for p in points:
                world = obj.matrix_world @ p
                v = world_to_camera_view(scene, cam, world)
                if v.z <= 0 or not (-margin <= v.x <= 1 + margin and -margin <= v.y <= 1 + margin):
                    continue
                direction = world - origin
                if direction.length < 0.05:
                    return True
                d, hit = ray_hit(origin, direction.normalized(), direction.length - 0.02)
                if d is None or hit in names:
                    return True
                rays += 1
                if rays > 1500:   # too many occluded points in one frame: better not hide
                    return True
    return False


def render_storyboard():
    out_dir = OUT if TEAM else Path(BOARD["output"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for number, item in enumerate(BOARD.get("placeholders", [])):
        if item.get("above_passage"):   # banner directly above the passage (just a banner above a
            h = item["size"][1] * (1 if item.get("no_scale") else S)   # door): lower edge banner_gap above the lintel, the height in at applies to scale 1
            item = dict(item, at=[*item["at"][:2], (door_h + float(DOORS.get("banner_gap", 0.3)) + h / 2) / S])
        placeholder(item, number)
    build_threads(THREAD_SOURCES)   # threads start behind the exhibits at the inner wall (cables through the wall)
    print(f"Szene gebaut, {len(THREAD_SOURCES)} Fäden, {time.perf_counter() - T0:.0f} s seit Start", flush=True)
    export_objects(out_dir / "scene_objects.json")   # inventory for the station planner
    hub_root_object()   # hub with the bar in front of the cabin
    if "--probe" in ARGS:   # debugging without rendering: position of placeholders (corners in world coordinates, plus r and height in the ring)
        for name in ARGS[ARGS.index("--probe") + 1].split(","):
            obj = bpy.data.objects.get(name) or bpy.data.objects.get("Platzhalter " + name)
            if obj is None:
                print("Probe: fehlt", name, flush=True)
                continue
            for corner in obj.bound_box[::2]:
                p = obj.matrix_world @ Vector(corner)
                radial = math.hypot(p.x, p.y)
                print(f"Probe {obj.name}: Ecke ({p.x:8.2f}, {p.y:8.2f}, {p.z:8.2f})  Höhe über Ringboden {R - 0.5 - radial:6.2f}  depth {-p.z:7.2f}", flush=True)
            print(f"Probe {obj.name}: Maße {tuple(round(d, 2) for d in obj.dimensions)}, hide_render {obj.hide_render}, "
                  f"Materialien {[m.name for m in obj.data.materials]}", flush=True)
            for m in obj.data.materials:
                for node in m.node_tree.nodes:
                    if node.type == "TEX_IMAGE":
                        img = node.image
                        print(f"Probe {obj.name}: Bild {img.name if img else None} {tuple(img.size) if img else ''} geladen {img.has_data if img else ''}", flush=True)
        for scene_spec in BOARD.get("scenes", []):   # cameras of the requested panels (--panels)
            for panel in scene_spec.get("panels", []):
                if "--panels" in ARGS and panel["id"] not in ARGS[ARGS.index("--panels") + 1].split(","):
                    continue
                spec = panel["camera"]
                for key in ("at", "look"):
                    p = board_point(spec, key, scale_height=False)
                    radial = math.hypot(p.x, p.y)
                    print(f"Probe Kamera {panel['id']} {key}: ({p.x:8.2f}, {p.y:8.2f}, {p.z:8.2f})  Höhe {R - 0.5 - radial:6.2f}  depth {-p.z:7.2f}", flush=True)
    for name in BOARD.get("hide_objects", []):
        if name in bpy.data.objects:
            bpy.data.objects[name].hide_render = True
    image = BOARD.get("image", {})
    if not TEAM:
        scene.render.resolution_x, scene.render.resolution_y = image.get("width", 960), image.get("height", 540)
        scene.eevee.taa_render_samples = image.get("samples", 16)
    only = ARGS[ARGS.index("--panels") + 1].split(",") if "--panels" in ARGS else None
    sync_viewport()
    OBJECT_NOTES = check_objects()   # once per run, applies to all panels
    for item_id, item_notes in OBJECT_NOTES.items():
        for level, text in item_notes:
            print(f"Prüfung {item_id}: {level}: {text}", flush=True)
    if "--save-blend" in ARGS:   # built scene saved as a file to open in Blender, without rendering (e.g. for a screenshot of the
        path = out_dir / "station.blend"   # Blender window with this scene for the screen in room 6); images stay linked
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        print(f"Szene gespeichert: {path}", flush=True)
        return
    if "--ride" in ARGS:   # ride instead of stills: holds at the cameras of the panels
        ride_preview(only, out_dir)
        return
    log = []
    for scene_spec in BOARD.get("scenes", []):
        for panel in scene_spec.get("panels", []):
            if only and panel["id"] not in only:
                continue
            spec = panel["camera"]   # camera: position scales with the museum, the eye height stays; the target point (an exhibit) scales too
            location, target = board_point(spec, "at", scale_height=False), board_point(spec, "look", scale_height=True)
            if panel.get("book"):
                open_book(panel["book"], panel.get("book_lectern"))
            set_main_door(0.0 if panel.get("main_door", "open") == "closed" else DOOR_OPEN_DEG)   # main door shut or open (main_door)
            set_room6_door(DOOR_OPEN_DEG if panel.get("room6_door") == "open" else 0.0)   # door from room 6, default shut
            for state in ("half", "closed"):   # gate of the museum and cabin door: open (default), half, closed
                gate_leaves = bpy.data.objects.get(f"Museum Tor Flügel {state}")
                if gate_leaves:
                    gate_leaves.hide_render = panel.get("gate", "open") != state
            for part in ("Glas", "Rahmen"):   # cabin door slides: position from cabin_door
                door = bpy.data.objects.get(f"Kabinentür {part}")
                if door and door.data.shape_keys:
                    door.data.shape_keys.key_blocks["offen"].value = CABIN_DOOR_OPEN[panel.get("cabin_door", "open")]
            if spec.get("up") in ("outward", "inward") and spec.get("frame") == "room":   # looking almost straight down at the lectern:
                u_, v_, phi_ = room_point(spec["room"], *spec["at"][:2])        # the top of the image is the head of the pages (outward:
                up = ring_dir(u_, math.cos(phi_), math.sin(phi_)).normalized() * (1 if spec["up"] == "outward" else -1)   # towards the outer wall)
            elif spec.get("up"):
                up = Vector(spec["up"])
            elif spec.get("frame", "ring") in ("ring", "room", "wall", "hall"):
                up = axis_up(location)
            else:
                up = None
            hidden = [bpy.data.objects[n] for n in panel.get("hide", []) if n in bpy.data.objects]   # e.g. the roof of the museum
            for obj in hidden:
                obj.hide_render = True
            sync_viewport()   # way back and check see the same objects as the render
            cam = camera(location, target, spec.get("lens", 24), up)
            cam.data.shift_y = float(spec.get("shift_y", 0.0))   # lens shift: looking horizontally at eye height, image shifted
            # upwards, verticals stay vertical (as in architectural photography; wall in room 2)
            if panel.get("fill") and fit_objects(panel):   # still like the ride: the object fills the image, so the
                cam = panel_pose(panel)   # camera is focused on the lectern and shows nothing else
                moved = 0.0
            else:
                moved = fit_camera(cam, fit_objects(panel), limit=float(panel.get("fit_limit", 3.0)))
            if moved:
                print(f"Tafel {panel['id']}: Kamera {moved:.1f} m zurück, damit {', '.join(panel['fit'])} ganz im Bild liegt", flush=True)
            notes = check_camera(cam, target, location)
            wanted = 0
            for item_id, item_notes in OBJECT_NOTES.items():   # report intersections only if the exhibit can be seen in the image
                if item_notes and visible_in(cam, item_id):
                    notes += [(level, text) for level, text in item_notes if level == "Fehler"]
                    wanted += sum(1 for level, _ in item_notes if level == "gewollt")
            if wanted:
                notes.append(("Hinweis", f"{wanted} gewollte Schnitte im Bild (Rückseiten an der Wand)"))
            credits = [credit_side(cam, p) for p in BOARD.get("placeholders", [])   # third-party works in the image (credits):
                       if p.get("credit") and p.get("room") == spec.get("room")   # only recognisably large ones in the camera's room (from the
                       and screen_share(cam, p["id"], credit_prefix(p)) >= CREDIT_MIN_SHARE
                       and visible_in(cam, p["id"], credit_prefix(p))]   # centre room one only sees backs)
            credits += panel.get("credits", [])   # by hand per panel: parts of a large panel, e.g. single cards in the timeline
            if panel.get("cabin_frame"):   # frame of the cabin in the foreground: two struts at the image edge, handrail at the bottom
                half_w = 18.0 / spec.get("lens", 24)   # half the image width at 1 m distance (sensor 36 mm)
                bm_cab = bmesh.new()
                for x in (-half_w * 0.93, half_w * 0.93):
                    bmesh.ops.create_cube(bm_cab, size=1.0, matrix=Matrix.Translation((x, 0, -1.0)) @ Matrix.Diagonal((0.035, 3.0, 0.035, 1)))
                bmesh.ops.create_cube(bm_cab, size=1.0, matrix=Matrix.Translation((0, -half_w * 9 / 16 * 0.92, -1.0)) @ Matrix.Diagonal((3.0, 0.02, 0.02, 1)))
                frame_obj = mesh_object(f"Kabinenrahmen vor der Kamera {panel['id']}", bm_cab, m_cabin)
                frame_obj.parent = cam
            name = "SB_" + panel["id"].replace(".", "_") + ".png"
            start = time.perf_counter()
            scene.render.filepath = str(out_dir / name)
            bpy.ops.render.render(write_still=True)
            for obj in hidden:
                obj.hide_render = False
            if panel.get("cabin_frame"):
                frame_obj.hide_render = True   # applies to this panel only
            spread = image_spread(out_dir / name)
            if spread < 0.04:
                notes.append(("Fehler", f"Bild fast einfarbig (Streuung {spread:.3f}): Kamera in einem Körper?"))
            status = "Fehler" if any(level == "Fehler" for level, _ in notes) else "ok"
            log.append({"panel": panel["id"], "file": name, "seconds": round(time.perf_counter() - start, 1), "fit_moved_m": round(moved, 2),
                        "spread": round(spread, 3), "check": status, "credits": list(dict.fromkeys(credits)),
                        "notes": [f"{level}: {text}" for level, text in notes]})
            print(f"Tafel {panel['id']}: {log[-1]['seconds']} s, Prüfung {status}" + "".join(f"\n  {n}" for n in log[-1]["notes"]), flush=True)
    log_file = out_dir / "render_log.json"   # merge: a run with --panels overwrites only its own panels
    try:
        old = {e["panel"]: e for e in json.loads(log_file.read_text(encoding="utf-8"))} if log_file.exists() else {}
    except (ValueError, KeyError):
        old = {}
    old.update({e["panel"]: e for e in log})
    log_file.write_text(json.dumps(list(old.values()), indent=1, ensure_ascii=False), encoding="utf-8")


if BOARD:
    render_storyboard()
    ARGS.append("--no-clip")

wanted = ARGS[ARGS.index("--shots") + 1].split(",") if "--shots" in ARGS else None   # e.g. --shots 21,22 or --shots none
if BOARD:
    wanted = ["none"]
for name, location, target, lens, up in shots:
    if wanted is None or name[:2] in wanted:
        camera(location, target, lens, up)
        render(name.replace(".png", "_day.png") if DAY else name)

# ---------------------------------------------------------------- short film: ring turns, hub stands still (time lapse)
if "--no-clip" not in ARGS:
    realtime = "--realtime" in ARGS
    # time lapse: 24 s of real time in 4 s of film (six times); real time: 8 s of film at 12 frames per second (1.77 rpm: 85° in 8 s)
    frames, seconds_real = (96, 8.0) if realtime else (48, 24.0)
    shadow_view = "--clip-shadow" in ARGS   # from the shadow side: city lights and hub visible
    camera((640, 460, -820) if shadow_view else (520, -760, 820), (0, 0, -60), 32)
    scene.render.resolution_x, scene.render.resolution_y = 480, 270
    scene.eevee.taa_render_samples = 8
    frame_dir = REPO / "_Ressourcen" / "3D_Bibliothek" / "_scratch" / "station_clip"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for f in range(frames):
        rotor.rotation_euler = (0, 0, 2 * math.pi * RPM / 60 * seconds_real * f / frames)
        scene.render.filepath = str(frame_dir / f"frame_{f:03d}.png")
        bpy.ops.render.render(write_still=True)
    clip = OUT / ("52_station_turning_shadow.mp4" if shadow_view else
                  "27_station_turning_realtime.mp4" if realtime else "27_station_turning.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "12", "-i", str(frame_dir / "frame_%03d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", str(clip)], check=True)
    print("geschrieben:", clip)
