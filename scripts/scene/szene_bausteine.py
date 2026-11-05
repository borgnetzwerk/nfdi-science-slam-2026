"""Shared building blocks for the scenes (runs inside Blender): PBR materials from Poly Haven, inserting models,
simple shapes. Used by station_scene.py.

Textures are projected in object coordinates (box projection, size in metres), so that walls and floors appear at the
right scale without UV unwrapping; apply the object scale first, otherwise the texture is stretched with it.
"""
import math
import os
from pathlib import Path

import bpy
from mathutils import Vector

POLYHAVEN = Path(__file__).resolve().parent.parent / "media" / "polyhaven"


def _maps(asset):
    folder = POLYHAVEN / asset
    found = {}
    for path in folder.glob("*.*"):
        name = path.name.lower()
        for key, marker in (("diff", "_diff_"), ("nor", "_nor_gl_"), ("rough", "_rough_"), ("disp", "_disp")):
            if marker in name and key not in found:
                found[key] = path
    return found


def pbr(name, asset, size_m=2.0, tint=None, roughness=None, metallic=None):
    """Material from a Poly Haven texture, box-projected in object coordinates."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    coords, mapping = nodes.new("ShaderNodeTexCoord"), nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1 / size_m,) * 3
    links.new(coords.outputs["Object"], mapping.inputs["Vector"])
    maps = _maps(asset)

    def image(path, non_color):
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(path), check_existing=True)
        tex.projection, tex.projection_blend = "BOX", 0.25
        if non_color:
            tex.image.colorspace_settings.name = "Non-Color"
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        return tex

    if "diff" in maps:
        color = image(maps["diff"], False).outputs["Color"]
        if tint:
            mix = nodes.new("ShaderNodeMix")
            mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            links.new(color, mix.inputs["A"])
            mix.inputs["B"].default_value = (*tint, 1)
            color = mix.outputs["Result"]
        links.new(color, bsdf.inputs["Base Color"])
    if "rough" in maps and roughness is None:
        links.new(image(maps["rough"], True).outputs["Color"], bsdf.inputs["Roughness"])
    elif roughness is not None:
        bsdf.inputs["Roughness"].default_value = roughness
    if "nor" in maps:
        normal = nodes.new("ShaderNodeNormalMap")
        links.new(image(maps["nor"], True).outputs["Color"], normal.inputs["Color"])
        links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
    if metallic is not None:
        bsdf.inputs["Metallic"].default_value = metallic
    return mat


def solid(name, color, roughness=0.5, metallic=0.0, emission=0.0):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*color, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    return mat


def glow(name, color, strength, alpha=1.0):
    """Pure emission, optionally partly transparent."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out, emit = nodes.new("ShaderNodeOutputMaterial"), nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (*color, 1)
    emit.inputs["Strength"].default_value = strength
    if alpha >= 1:
        links.new(emit.outputs[0], out.inputs["Surface"])
    else:
        mix, transparent = nodes.new("ShaderNodeMixShader"), nodes.new("ShaderNodeBsdfTransparent")
        mix.inputs["Fac"].default_value = alpha
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(emit.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs["Surface"])
        mat.surface_render_method = "BLENDED"
    return mat


def box(name, center, size, mat, rotation=(0, 0, 0), bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(location=center, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        mod = obj.modifiers.new("Bevel", "BEVEL")
        mod.width, mod.segments, mod.limit_method = bevel, 2, "ANGLE"
    obj.data.materials.append(mat)
    return obj


def rod(name, a, b, radius, mat, vertices=12):
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=(b - a).length, location=(a + b) / 2)
    obj = bpy.context.active_object
    obj.name = name
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (b - a).to_track_quat("Z", "Y")
    obj.data.materials.append(mat)
    return obj


def beam(name, a, b, width, height, mat):
    """Box beam from a to b (cross section width x height)."""
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cube_add(location=(a + b) / 2)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (width / 2, height / 2, (b - a).length / 2)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (b - a).to_track_quat("Z", "Y")
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    obj.data.materials.append(mat)
    return obj


def text(name, body, location, size, mat, font=None, rotation=(math.radians(90), 0, 0), align="CENTER", extrude=0.02):
    bpy.ops.object.text_add(location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.body = body
    if font and Path(font).exists():
        obj.data.font = bpy.data.fonts.load(str(font), check_existing=True)
    obj.data.size, obj.data.extrude = size, extrude
    obj.data.align_x, obj.data.align_y = align, "CENTER"
    obj.data.materials.append(mat)
    return obj


_model_cache = {}


def model(asset, location, rotation_z=0.0, scale=1.0, harmonize_tint=None):
    """Insert a Poly Haven model, resolving texture paths relative to the model folder. Returns the parent object."""
    folder = POLYHAVEN / asset
    blend = next(folder.glob("*.blend"))
    if asset not in _model_cache:
        with bpy.data.libraries.load(str(blend), link=False) as (source, target):
            target.objects = list(source.objects)
        objects = [obj for obj in target.objects if obj is not None]
        for obj in objects:
            for slot in getattr(obj, "material_slots", []):
                if not slot.material or not slot.material.use_nodes:
                    continue
                for node in slot.material.node_tree.nodes:
                    if node.type == "TEX_IMAGE" and node.image and node.image.filepath.startswith("//"):
                        node.image.filepath = str(folder / node.image.filepath[2:])
                        node.image.reload()
        if harmonize_tint:
            harmonize({slot.material for obj in objects for slot in getattr(obj, "material_slots", [])}, harmonize_tint)
        _model_cache[asset] = objects
    source_objects = _model_cache[asset]
    root = bpy.data.objects.new(f"{asset}_root", None)
    bpy.context.collection.objects.link(root)
    copies = {}
    for obj in source_objects:
        copy = obj.copy()   # the copy shares mesh and material, which saves memory
        bpy.context.collection.objects.link(copy)
        copies[obj] = copy
    for obj, copy in copies.items():
        copy.parent = copies.get(obj.parent, root)
    root.location, root.rotation_euler, root.scale = location, (0, 0, rotation_z), (scale,) * 3
    return root


def setup_render(scene, width=1280, height=720, samples=32, bloom=0.6):
    """Eevee with ray tracing, the Khronos PBR Neutral view transform and bloom via the compositor."""
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = samples
    scene.eevee.use_raytracing = True
    scene.eevee.use_shadows = True
    scene.eevee.shadow_pool_size = "2048"   # a hall with many reading and pendant lights reported "Shadow buffer full" at 1024
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.view_settings.view_transform = "Khronos PBR Neutral"
    if not bloom:
        return
    tree = bpy.data.node_groups.new("Glow", "CompositorNodeTree")
    scene.compositing_node_group = tree
    layers, glare = tree.nodes.new("CompositorNodeRLayers"), tree.nodes.new("CompositorNodeGlare")
    for attribute, value in (("glare_type", "BLOOM"), ("quality", "HIGH")):
        if hasattr(glare, attribute):
            setattr(glare, attribute, value)
    for key, value in (("Strength", bloom), ("Size", 0.6), ("Threshold", 1.2)):
        if key in glare.inputs:
            glare.inputs[key].default_value = value
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    output = tree.nodes.new("NodeGroupOutput")
    tree.links.new(layers.outputs["Image"], glare.inputs["Image"])
    tree.links.new(glare.outputs["Image"], output.inputs[0])


def world_hdri(scene, path, strength=1.0):
    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    env = nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(path))
    links.new(env.outputs["Color"], nodes["Background"].inputs["Color"])
    nodes["Background"].inputs["Strength"].default_value = strength


def haze(center, size, density=0.006, anisotropy=0.4):
    """Haze inside a box, so that light from above becomes visible as rays."""
    bpy.ops.mesh.primitive_cube_add(location=center)
    cube = bpy.context.active_object
    cube.name = "Haze"
    cube.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    mat = bpy.data.materials.new("Haze")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out, volume = nodes.new("ShaderNodeOutputMaterial"), nodes.new("ShaderNodeVolumePrincipled")
    volume.inputs["Density"].default_value = density
    volume.inputs["Anisotropy"].default_value = anisotropy
    links.new(volume.outputs[0], out.inputs["Volume"])
    cube.data.materials.append(mat)
    return cube


def cutout(name, image_path, location, height, yaw=0.0):
    """Figure as a cardboard cutout (image with alpha), standing on location, facing -y rotated by yaw."""
    image = bpy.data.images.load(str(image_path), check_existing=True)
    width = height * image.size[0] / image.size[1]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = image
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    mat.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 0.25
    x, y, z = location
    bpy.ops.mesh.primitive_plane_add(size=1, location=(x, y, z + height / 2), rotation=(math.radians(90), 0, yaw))
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (width, height, 1)
    obj.data.materials.append(mat)
    return obj, width


# WissKomm Wiki colours from the design tokens (scale B, teal 50 to 900, already linear), generated into wkw_palette.py.
# No hand-written hex values here, so that the scene always matches the house colours.
from wkw_palette import OKABE_ITO, SIGNAL, TEXT, WKW, WKW_HEX  # noqa: E402,F401


def srgb_to_linear(hex_value):
    def channel(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return tuple(channel(hex_value[i:i + 2]) for i in (0, 2, 4))




def harmonize(materials, tint, saturation=0.25):
    """Bring colourful textures of third-party models in line with the house colours: lower the saturation, then
    multiply with a teal tone."""
    for mat in materials:
        if not mat or not mat.use_nodes or mat.get("wkw_harmonized"):
            continue
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        for bsdf in [n for n in nodes if n.type == "BSDF_PRINCIPLED"]:
            socket = bsdf.inputs["Base Color"]
            hue = nodes.new("ShaderNodeHueSaturation")
            hue.inputs["Saturation"].default_value = saturation
            mix = nodes.new("ShaderNodeMix")
            mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            mix.inputs["B"].default_value = (*tint, 1)
            if socket.is_linked:
                links.new(socket.links[0].from_socket, hue.inputs["Color"])
            else:
                hue.inputs["Color"].default_value = socket.default_value
            links.new(hue.outputs["Color"], mix.inputs["A"])
            links.new(mix.outputs["Result"], socket)
        mat["wkw_harmonized"] = True
