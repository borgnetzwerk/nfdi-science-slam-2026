---
name: powerpoint-3d-models
description: Embed glTF (GLB) 3D models in PowerPoint, move between views with Morph, and play animated scenes piece by piece, per click or per slide. Use when placing a 3D model on slides by script, when an embedded animation does not play, loops forever, or jumps back to its first frame after a Morph, or when a deck with 3D models grows too large.
license: CC-BY-4.0
compatibility: PowerPoint for Microsoft 365 on Windows; Python with pywin32 for scripting
metadata:
  bnw-scope: public
  bnw-status: draft
  bnw-updated: "2026-11-05"
---

# PowerPoint with 3D models

PowerPoint (Microsoft 365, Windows) embeds `.glb` files as live 3D models. With the rules below, one embedded model can turn from view to view with Morph and play its motion one piece per click or one piece per slide, without jumps. Tested with PowerPoint 16 and Blender 5.2 exports in October 2026.

## By hand in PowerPoint

- **Insert** > **3D Models** > **This Device**, pick the `.glb`. Turn it with the handle in the middle or in the **3D Model** tab.
- **Several views:** duplicate the slide, turn the model on the copy, then **Transitions** > **Morph** on the copy. In the **Selection Pane**, give the model the same name starting with `!!` on every slide.
- **Play the motion:** with a skinned model, **Animations** > **Play 3D** appears; **Effect Options** (or **Scenes** in the 3D Model tab) chooses the scene.
- **Play once and keep the end pose:** **Animation Pane** > right-click the effect > **Timing** > **Repeat: (none)**, and leave **Rewind when done playing** unticked.
- **Not available by hand, as far as we know:** playing only part of a scene per click, and picking a different scene per slide reliably after Morph. Both are done in the slide XML (Rules 5 and 6).

## Rules

1. **Motion must be skeletal.** PowerPoint plays only skinned animation (glTF `skins`). Objects animated by node transforms stay still, even when inserted by hand, and the 3D Model tab shows no "Scenes" menu. Convert moving parts to bones before export (see the `blender-gltf-export` skill).
2. **One model, many slides.** Insert the model once, then duplicate the slide. All slides share one file in the package. Name the shape with a `!!` prefix (for example `!!scene`) on every slide so Morph treats it as the same object.
3. **Morph is code 3954.** `ppEffectMorphByObject` = 3954; 3953 is `ppEffectOrigamiRight`. Look constants up in the type library instead of guessing.
4. **Texture size decides file size.** PowerPoint rewrites the model with its own exporter and stores every texture as PNG; a 66 MB GLB became 169 MB. Shrink textures before export (512 px looked identical on slides). JPEG or Draco do not help. One model per slide is not an option.
5. **A scene is a glTF animation; playing it is an ordinary animation effect.** Loop, pieces per click and the scene per slide are all set in the slide XML. Details and snippets: [references/scene-timing.md](references/scene-timing.md).
6. **After a Morph a slide starts in the rest pose of its chosen scene.** The poster frame attribute has no effect in the slide show. To continue where the previous slide stopped, give each slide its own scene that begins exactly with the end pose of the previous one.
7. **PowerPoint runs once per machine.** A script quits it only when no other presentation is open.

## Choosing a pattern

- **Pieces per click on one slide:** reliable and simple; several click effects, each playing a range of the scene.
- **One scene per slide with Morph in between:** for turning the view while the motion goes on; needs one scene per slide, cut without gaps, each with a short hold at the end.
- **A ride through rooms:** stay with rendered video. PowerPoint shows a model from outside; a cutaway (roof and ceiling removed) works well as an overview.

## Checking

Exported slide images (`Slide.Export`) show a stored preview, not the motion. Check motion by watching the slide show, or without PowerPoint: re-import the GLB in Blender and render several times, compare the seams between scenes numerically, read the slide XML, and reopen every edited file once (PowerPoint rejects invalid values). Details: [references/findings.md](references/findings.md).
