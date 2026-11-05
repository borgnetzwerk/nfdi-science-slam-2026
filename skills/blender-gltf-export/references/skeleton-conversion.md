# Reference: converting node motion to a skeleton

Outline of the conversion used before exporting a single animated piece (for example a book whose pages turn on hinge objects). `root` is the top object of the piece; `first` and `last` are the frame range.

```python
import bpy

scene = bpy.context.scene
members = [root, *root.children_recursive]
movers = [o for o in members if o.animation_data and o.animation_data.action]

# 1. Record world matrices while the old hierarchy still holds
track = {o.name: [] for o in movers}
for frame in range(first, last + 1):
    scene.frame_set(frame)
    for o in movers:
        track[o.name].append(o.matrix_world.copy())
scene.frame_set(first)

# 2. Which mesh belongs to which moving object (nearest moving ancestor)
owner = {}
for o in members:
    if o.type == "MESH":
        p = o.parent
        while p and p not in movers:
            p = p.parent
        if p:
            owner[o] = p
rest = {o.name: o.matrix_world.copy() for o in movers}
world = {m: m.matrix_world.copy() for m in owner}

# 3. Armature with one bone per moving object, at its first-frame pose
arm = bpy.data.objects.new("Skeleton", bpy.data.armatures.new("Skeleton"))
scene.collection.objects.link(arm)
arm.parent = root
arm.matrix_world = root.matrix_world.copy()
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
to_arm = arm.matrix_world.inverted()
for o in movers:
    bone = arm.data.edit_bones.new(o.name)
    bone.head, bone.tail = (0, 0, 0), (0, 0, 0.05)
    bone.matrix = (to_arm @ rest[o.name]).normalized()
bpy.ops.object.mode_set(mode="OBJECT")

# 4. Freeze meshes in place and skin them to their bone
for mesh_obj, mover in owner.items():
    mesh_obj.data = mesh_obj.data.copy()          # linked data must not move twice
    mesh_obj.parent = None
    mesh_obj.data.transform(to_arm @ world[mesh_obj])
    mesh_obj.matrix_world = arm.matrix_world.copy()
    mesh_obj.parent = arm
    mesh_obj.matrix_parent_inverse = arm.matrix_world.inverted()
    group = mesh_obj.vertex_groups.new(name=mover.name)
    group.add(range(len(mesh_obj.data.vertices)), 1.0, "REPLACE")
    mesh_obj.modifiers.new("Skeleton", "ARMATURE").object = arm

# 5. Key the bones, time from 0
arm.animation_data_create()
arm.animation_data.action = bpy.data.actions.new("all")
for o in movers:
    o.animation_data_clear()
    pb = arm.pose.bones[o.name]
    pb.rotation_mode = "QUATERNION"
    for i, m in enumerate(track[o.name]):
        pb.matrix = (to_arm @ m).normalized()
        bpy.context.view_layer.update()
        pb.keyframe_insert("location", frame=i)
        pb.keyframe_insert("rotation_quaternion", frame=i)
scene.frame_start, scene.frame_end = 0, last - first
```

Export with the root, its children and the armature selected:

```python
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True,
                          export_apply=True, export_animations=True,
                          export_force_sampling=True, export_frame_range=True)
```

## Checks

- The GLB has a `skins` entry and the moving meshes carry `skin`.
- Each animation's time starts at 0.
- For several scenes: the last rotation of scene k equals the first of scene k+1 for every bone (treat q and minus q as the same rotation).
