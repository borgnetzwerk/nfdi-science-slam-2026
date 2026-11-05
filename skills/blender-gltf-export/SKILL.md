---
name: blender-gltf-export
description: Export Blender scenes or single animated pieces to glTF (GLB) with bpy for PowerPoint and web viewers. Use when the glTF exporter crashes or drops textures, when box-projected or video textures look wrong after export, when an animation must play in PowerPoint (it needs bones), when one file must carry several scenes, or when a GLB must stay small.
license: CC-BY-4.0
compatibility: Blender 5.2 or later, run headless with bpy; ffmpeg for video stills
metadata:
  bnw-scope: public
  bnw-status: draft
  bnw-updated: "2026-10-28"
---

# Blender to glTF (GLB)

Blender's built-in glTF exporter (`bpy.ops.export_scene.gltf`) writes what glTF can hold: meshes, PBR materials with image textures over UVs, cameras, point, spot and sun lights, and animation. Anything else has to be converted first. Tested with Blender 5.2 LTS in October 2026, run without a user interface (`blender -b file.blend -P script.py`).

## Before exporting

1. **Video textures crash the exporter** without a message. Replace each movie image by a still frame (extract one with ffmpeg, then `image.user_remap(still)`).
2. **Box projection does not exist in glTF.** Write real UVs: per face, take the two coordinates across the main axis of the normal, in metres; reconnect the texture inputs from the "Object" to the "UV" output of the Texture Coordinate node and set the image nodes to flat projection. Keep the scale in the Mapping node; it exports as `KHR_texture_transform`.
3. **Area lights are dropped.** The viewer lights the model; plan for that.
4. **Limit texture size** when the target is PowerPoint (`image.scale(w, h)`); see the `powerpoint-3d-models` skill.

## Motion for PowerPoint

PowerPoint plays only skinned animation. For a single animated piece:

- one bone per moving object, placed at the object's pose in the first frame
- freeze each of its meshes in that pose (`mesh.transform(...)`), give it a vertex group with weight 1 for the bone and an Armature modifier
- key the bone from the object's world matrix frame by frame (`pose_bone.matrix = ...`), starting at frame 0, since glTF counts time from frame 0 of the scene

Code outline and checks: [references/skeleton-conversion.md](references/skeleton-conversion.md).

## Several scenes in one file

Each action becomes one glTF animation, which PowerPoint offers as one scene. Make one action per piece, put each into its own NLA track (`nla_tracks.new().strips.new(name, 0, action)`), then set `animation_data.action = None` and export. Cut pieces without gaps (each starts where the previous ends) and hold the end pose for a few frames. `export_animation_mode="SCENE"` did not merge separate actions in 5.2.

## Checking without the target app

Import the GLB into an empty scene (`bpy.ops.wm.read_factory_settings(use_empty=True)`, then `bpy.ops.import_scene.gltf`), aim a camera at the evaluated vertices of one mesh (object origins of skinned meshes sit at the skeleton) and render a few frames. Compare the last keyframe of each scene with the first of the next.
