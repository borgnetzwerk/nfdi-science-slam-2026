"""Inside Blender: cut a built station scene into modules.

Called by run_split.py, which reads modules.yaml and passes the settings as a JSON file. For each module: open the source file,
go to frame 1, detach parents across module borders (world position is kept), remove everything else, replace Poly Haven
objects by an empty with a link, pack own images and fonts, only reference Poly Haven textures and withheld images, save
<module>.blend and export <module>.glb. Then station.blend links every module collection as an instance, with the world from
environment.blend. Finally manifest.json lists per module its elements, objects, images and Poly Haven placements.
"""
import json
import re
import sys
from pathlib import Path

import bpy

config = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
SOURCE = config["source"]
OUT = Path(config["out"])
# one folder per module: <out>/<module>/<module>.blend and .glb, next to its README and preview
MODULES = config["modules"]
POLYHAVEN = sorted({p.lower() for p in config["polyhaven_ids"]}, key=len, reverse=True)
TRANSFORM_ROOTS = [re.compile(r) for r in config.get("transform_roots", [])]
WITHHOLD = [(w["match"].lower(), w["reason"]) for w in config.get("withhold_images", [])]
WITHHOLD_OBJECTS = [(re.compile(w["match"]), w["reason"]) for w in config.get("withhold_objects", [])]
for module in MODULES:
    for element in module["elements"]:
        element["rx"] = [re.compile(r) for r in element["match"]]
    if module.get("per_object"):
        module["per_rx"] = re.compile(module["per_object"])


def polyhaven_id(name):
    low = name.lower()
    return next((p for p in POLYHAVEN if low.startswith(p)), None)


def ancestors(obj):
    while obj.parent is not None:
        obj = obj.parent
        yield obj


def match_name(name):
    """(module, element) for an object name, or None."""
    for module in MODULES:
        if module.get("per_rx"):
            hit = module["per_rx"].match(name)
            if hit:
                return module["id"], hit.group(1)
        for element in module["elements"]:
            if any(rx.search(name) for rx in element["rx"]):
                return module["id"], element["id"]
    return None


RENAMES = config.get("renames", [])


def set_path(block, path):
    """Set a file path without leaving the old one behind: paths are fixed-size buffers in the .blend file, and the
    tail of a longer old path would stay after the new one; fill the buffer first."""
    attr = "filepath_raw" if isinstance(block, bpy.types.Image) else "filepath"
    setattr(block, attr, "/" * 1000)
    setattr(block, attr, path)


def apply_renames():
    """Rename objects as in public_renames.yaml, the same way as in the published scripts."""
    for obj in bpy.data.objects:
        for r in RENAMES:
            if r["old"] in obj.name:
                obj.name = obj.name.replace(r["old"], r["new"])


def classify():
    """Object name -> (module, element); a Poly Haven object goes with the module of its parents."""
    result = {}
    for obj in bpy.data.objects:
        if any(rx.match(obj.name) for rx in TRANSFORM_ROOTS):
            result[obj.name] = ("_transform", None)
            continue
        own = [o for o in [obj, *ancestors(obj)]
               if not polyhaven_id(o.name) and not any(rx.match(o.name) for rx in TRANSFORM_ROOTS)]
        hit = next((match_name(o.name) for o in own if match_name(o.name)), None)
        if hit is None and not own:   # placed Poly Haven model without own parent: only its place is kept, as a marker
            hit = ("polyhaven_placements", "polyhaven_markers")
        result[obj.name] = hit or ("unassigned", "unassigned")
    return result


def image_kind(image):
    path = image.filepath.replace("\\", "/").lower()
    if image.source != "FILE" or not path:
        return "internal", None
    if "/polyhaven/" in path:
        return "polyhaven", None
    reason = next((r for m, r in WITHHOLD if m in path or m in image.name.lower()), None)
    return ("withheld", reason) if reason else ("own", None)


def export_module(module, assignment, manifest):
    bpy.ops.wm.open_mainfile(filepath=SOURCE)
    bpy.context.preferences.filepaths.save_version = 0   # no .blend1 backups next to the published files
    apply_renames()
    scene = bpy.context.scene
    scene.frame_set(1)
    mid = module["id"]
    keep = [o for o in bpy.data.objects if assignment.get(o.name, ("",))[0] == mid]
    keep_names = {o.name for o in keep}
    for obj in keep:   # parents outside the module: detach, keep world position
        if obj.parent is not None and obj.parent.name not in keep_names:
            world = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = world
    placements = []   # Poly Haven objects: remember where, replace the top object of each group by an empty
    for obj in list(keep):
        pid = polyhaven_id(obj.name)
        if not pid:
            continue
        if not (obj.parent is not None and polyhaven_id(obj.parent.name)):
            marker = bpy.data.objects.new(f"PolyHaven {pid}", None)
            marker.empty_display_type = "CUBE"
            marker.matrix_world = obj.matrix_world.copy()
            marker["polyhaven_id"] = pid
            marker["url"] = f"https://polyhaven.com/a/{pid}"
            marker["licence"] = "CC0"
            keep.append(marker)
            placements.append({"id": pid, "location": [round(c, 3) for c in obj.matrix_world.translation]})
        keep.remove(obj)
    withheld_objects = []   # objects we may not publish: keep only their place
    for obj in list(keep):
        reason = next((r for rx, r in WITHHOLD_OBJECTS if rx.search(obj.name)), None)
        if not reason:
            continue
        for child in obj.children:   # children stay where they are
            world = child.matrix_world.copy()
            child.parent = None
            child.matrix_world = world
        marker = bpy.data.objects.new(f"Withheld {obj.name}", None)
        marker.empty_display_type = "PLAIN_AXES"
        marker.matrix_world = obj.matrix_world.copy()
        marker["withheld"] = reason
        keep.append(marker)
        assignment[marker.name] = assignment.get(obj.name, (mid, mid))
        withheld_objects.append({"name": obj.name, "reason": reason})
        keep.remove(obj)
    keep_set = set(keep)
    bpy.data.batch_remove([o for o in bpy.data.objects if o not in keep_set])
    for coll in list(bpy.data.collections):   # one collection per module, one child collection per element
        bpy.data.collections.remove(coll)
    root = bpy.data.collections.new(mid)
    scene.collection.children.link(root)
    elements = {}
    for obj in keep:
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
        eid = "polyhaven_markers" if obj.get("polyhaven_id") else (assignment.get(obj.name, (mid, mid))[1] or mid)
        if eid not in elements:
            elements[eid] = bpy.data.collections.new(f"{mid}.{eid}")
            root.children.link(elements[eid])
        elements[eid].objects.link(obj)
    if mid != "environment":
        for world in list(bpy.data.worlds):
            bpy.data.worlds.remove(world)
    bpy.data.orphans_purge(do_recursive=True)
    images = []
    for image in bpy.data.images:
        kind, reason = image_kind(image)
        name = Path(bpy.path.abspath(image.filepath)).name if image.filepath else image.name
        entry = {"name": image.name, "file": name, "kind": kind}   # file name only, no local paths
        if kind == "withheld":   # file not in the repository; the material keeps its slot
            set_path(image, f"//../withheld/{name}")
            entry.update(packed=False, reason=reason)
        elif kind == "own":
            try:
                # Blender stores the path at packing time inside the packed data; packing from the bytes with a
                # relative path first keeps the local path out of the file
                if image.packed_file:
                    data = bytes(image.packed_file.data)
                else:
                    data = Path(bpy.path.abspath(image.filepath)).read_bytes()
                set_path(image, f"//images/{name}")
                image.pack(data=data, data_len=len(data))
                entry["packed"] = all(p.filepath.startswith("//") for p in image.packed_files)
            except RuntimeError as error:
                entry["packed"], entry["error"] = False, str(error)[:200]
        elif kind == "polyhaven":
            parts = image.filepath.replace("\\", "/").split("/")
            asset = parts[parts.index("polyhaven") + 1] if "polyhaven" in parts else "unknown"
            set_path(image, f"//../textures/polyhaven/{asset}/{name}")   # download from Poly Haven, see assets/README.md
            entry.update(packed=False, polyhaven_id=asset, url=f"https://polyhaven.com/a/{asset}")
        images.append(entry)
    for font in bpy.data.fonts:
        if font.filepath and not font.packed_file and font.filepath != "<builtin>":
            font.pack()
        if font.filepath and font.filepath != "<builtin>":
            set_path(font, f"//fonts/{Path(bpy.path.abspath(font.filepath)).name}")
    folder = OUT / mid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{mid}.blend"
    neutral_ui()
    bpy.ops.wm.save_as_mainfile(filepath=str(path), compress=True, relative_remap=False)
    # GLB next to it; missing images (Poly Haven, withheld) are missing there too, glTF carries text objects and lights only in part
    glb = folder / f"{mid}.glb"
    glb_note = None
    try:
        bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", export_apply=True, export_lights=True, export_extras=True)
    except (RuntimeError, TypeError) as error:
        glb_note = str(error)[:300]
        print(f"GLB {mid} failed: {glb_note}", flush=True)
    manifest["modules"].append({
        "id": mid, "title": module["title"], "description": module.get("description", ""), "alt": module.get("alt", ""), "file": f"{mid}/{mid}.blend", "bytes": path.stat().st_size,
        "glb": f"{mid}/{mid}.glb" if glb.exists() else None, "glb_bytes": glb.stat().st_size if glb.exists() else 0,
        "glb_error": glb_note,
        "elements": {eid: sorted(o.name for o in coll.objects) for eid, coll in elements.items()},
        "objects": len(keep), "images": images, "polyhaven": placements, "withheld_objects": withheld_objects,
        "fonts": sorted({f.name for f in bpy.data.fonts}),
    })
    print(f"module {mid}: {len(keep)} objects, {len(elements)} elements, {path.stat().st_size / 1e6:.1f} MB", flush=True)


def neutral_ui():
    """File browsers in the saved UI remember the last folder of this machine; point them at the file's own folder."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == "FILE_BROWSER" and getattr(space, "params", None):
                    # the folder is a fixed-size buffer: fill it first, or the rest of the old path stays behind the new one
                    space.params.directory = b"/" * 1000
                    space.params.directory = b"//"
                    space.params.filename = "x" * 300
                    space.params.filename = ""


def scene_settings():
    """Colour management and render basics of the source scene, so station.blend looks like the talk."""
    s = bpy.context.scene
    return {"view_transform": s.view_settings.view_transform, "look": s.view_settings.look,
            "exposure": s.view_settings.exposure, "gamma": s.view_settings.gamma,
            "display_device": s.display_settings.display_device, "engine": s.render.engine,
            "resolution": (s.render.resolution_x, s.render.resolution_y), "fps": s.render.fps}


def build_station(manifest, settings):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.save_version = 0
    scene = bpy.context.scene
    scene.name = "Station"
    scene.display_settings.display_device = settings["display_device"]
    scene.view_settings.view_transform = settings["view_transform"]
    scene.view_settings.look = settings["look"]
    scene.view_settings.exposure, scene.view_settings.gamma = settings["exposure"], settings["gamma"]
    scene.render.engine = settings["engine"]
    scene.render.resolution_x, scene.render.resolution_y = settings["resolution"]
    scene.render.fps = settings["fps"]
    for entry in manifest["modules"]:
        with bpy.data.libraries.load(str(OUT / entry["file"]), link=True, relative=True) as (src, dst):
            dst.collections = [entry["id"]]
            if entry["id"] == "environment":
                dst.worlds = list(src.worlds)
        holder = bpy.data.objects.new(entry["id"], None)
        holder.instance_type = "COLLECTION"
        holder.instance_collection = dst.collections[0]
        scene.collection.objects.link(holder)
        if entry["id"] == "environment" and dst.worlds:
            scene.world = dst.worlds[0]
    for library in bpy.data.libraries:   # forward slashes, so Linux and macOS find the modules
        name = Path(bpy.path.abspath(library.filepath)).stem
        set_path(library, f"//{name}/{name}.blend")
    neutral_ui()
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "station.blend"), compress=True, relative_remap=False)
    print(f"station.blend: {len(manifest['modules'])} modules linked", flush=True)


bpy.ops.wm.open_mainfile(filepath=SOURCE)
apply_renames()
SETTINGS = scene_settings()
ASSIGNMENT = classify()
manifest = {"source": Path(SOURCE).name, "frame": 1, "units": "m", "modules": [],
            "unassigned": sorted(n for n, (m, _) in ASSIGNMENT.items() if m == "unassigned"),
            "transform_roots": sorted(n for n, (m, _) in ASSIGNMENT.items() if m == "_transform")}
used = {m for m, _ in ASSIGNMENT.values()}
EXTRA = [{"id": "polyhaven_placements", "title": "Where Poly Haven models stood (empties with links, no files)", "elements": [],
          "description": "Where furniture and plants from Poly Haven stood. Each place is an empty named after the asset, with its link; download the asset and parent it to the empty."},
         {"id": "unassigned", "title": "Objects without a module (to sort)", "elements": []}]
manifest["withheld_modules"] = [{"id": m["id"], "reason": m["withheld"]} for m in MODULES if m.get("withheld")]
for module in MODULES + EXTRA:
    if module["id"] in used and not module.get("withheld"):   # withheld: objects are claimed, so they land nowhere else
        export_module(module, ASSIGNMENT, manifest)
build_station(manifest, SETTINGS)
(OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"manifest: {OUT / 'manifest.json'}, unassigned: {len(manifest['unassigned'])}", flush=True)
