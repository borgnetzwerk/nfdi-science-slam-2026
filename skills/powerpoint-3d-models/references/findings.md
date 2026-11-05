# Findings: PowerPoint with 3D models

Each finding: what was seen, why, what helps. October 2026, PowerPoint for Microsoft 365 on Windows, models exported from Blender 5.2.

## Animation lies still, no "Scenes" menu

- **Seen:** an animated GLB (pages of a book turning) shows no motion, also when inserted by drag and drop; the 3D Model tab has no Scenes menu.
- **Why:** PowerPoint plays only skinned animation; node transform animation is ignored. A member of Microsoft's glTF team said so in the Babylon.js forum (thread "GLTFExporter: Generated .glb doesn't animate in Powerpoint", 2021); still true in 2026.
- **Helps:** bind moving parts to bones before export. After that, "Play 3D" and "Scenes" appear.

## Deck far larger than the model

- **Seen:** 4 slides with one 66 MB GLB give a 169 MB deck; copying a slide does not add size.
- **Why:** the package holds one model (`ppt/media/model3d1.glb`) that all slides reference, but PowerPoint rewrites it ("Microsoft GLTF Exporter") and stores each texture as PNG (27 JPEG and 33 PNG became 102 PNG).
- **Helps:** limit texture edges before export; 512 px gave a 9.7 MB model and a 22 MB deck with no visible loss.

## Origami instead of Morph

- **Seen:** the transition folds the slide away instead of morphing.
- **Why:** `EntryEffect = 3953` is `ppEffectOrigamiRight`; Morph by object is 3954.
- **Helps:** read constants from the type library (`win32com.client.gencache.EnsureDispatch`, then `win32com.client.constants`).

## Jump back to the first frame after Morph

- **Seen:** after each Morph the model shows its first frame again, then plays.
- **Why:** each slide holds its own instance of the model, which starts in the rest pose of its scene; the poster frame attribute does not change that in the slide show.
- **Helps:** one scene per slide, each starting with the end pose of the previous slide, and on each slide set `animId`, `embedded<n>` and the scene length (see [scene-timing.md](scene-timing.md)).

## Small jumps at the seams

- **Seen:** at each slide change the motion steps back a little, or begins with the last bit of the previous motion.
- **Why:** scenes overlapped by a few frames, and PowerPoint stops slightly before the last frame.
- **Helps:** cut scenes without gaps or overlap and hold the end pose for about 0.2 s.

## COM refuses a rotation right after inserting

- **Seen:** setting `Model3D.RotationX` fails with "Operation is not supported" directly after `Shapes.Add3DModel`, works on a second try.
- **Helps:** retry a few times with a short pause.

## What COM offers

`Shapes.Add3DModel(path, LinkToFile, SaveWithDocument, Left, Top, Width, Height)`; on `Shape.Model3D`: `RotationX/Y/Z`, `CameraPositionX/Y/Z`, `LookAtPointX/Y/Z`, `FieldOfView`, `ResetModel`, `IncrementRotationX/Y/Z`. The camera can be placed inside the model (units are normalized to the model size). There is no member for scenes or playback.
