# PowerPoint: videos that hold their last frame, and 3D models

The whole talk is video clips in a PowerPoint deck. The slide change is invisible only if each clip stops exactly on its last frame, because the next clip starts with that same frame. Two things got in the way, and here is how to fix them, first by hand, then by script. The full write-up is in the skills [powerpoint-video-playback](../skills/powerpoint-video-playback/SKILL.md) and [powerpoint-3d-models](../skills/powerpoint-3d-models/SKILL.md).

## Video stays on its last frame

**By hand in PowerPoint:**

1. **Insert** > **Video** > **This Device**.
2. Select the video, **Playback** tab:
   - **Start:** *Automatically*
   - **Rewind after Playing:** unticked
   - **Hide While Not Playing:** unticked

**If the deck is built by script (python-pptx):** replacing the slide timing to make the video start by itself drops a hidden media node with `fill="hold"`. The video then jumps back to its first frame even though *Rewind after Playing* reports off. Put the node back into the slide timing; [../tools/build_pptx.py](../tools/build_pptx.py) does this (`MEDIA_NODE`).

## The small jerk just before the end

PowerPoint stops a frame or two before the end of a clip (we measured frame 22 of 24). It looks as if the clip runs to 100 % and steps back to 99 %. There is no setting for it. Repeat the last frame for half a second in the video file before inserting it:

```
ffmpeg -i clip.mp4 -vf "tpad=stop_mode=clone:stop_duration=0.5" -c:v libx264 -pix_fmt yuv420p -crf 16 -movflags +faststart clip_hold.mp4
```

## The turning book: an animated 3D model

**By hand in PowerPoint:**

- **Insert** > **3D Models** > **This Device**, pick the `.glb`.
- The animation plays only if it is skeletal (bones). Then **Animations** > **Play 3D** appears; **Effect Options** chooses the scene.
- Play once and keep the end pose: **Animation Pane** > right-click the effect > **Timing** > **Repeat: (none)**.
- Several views: duplicate the slide, turn the model, **Transitions** > **Morph**; give the model the same name starting with `!!` on every slide (**Selection Pane**).

Playing one page per click or one page per slide was set in the slide XML; details in [powerpoint-3d-models](../skills/powerpoint-3d-models/SKILL.md). Like videos, 3D scenes stop just before their end, so each scene holds its end pose for about 0.2 s.
