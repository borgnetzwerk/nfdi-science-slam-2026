---
name: powerpoint-video-playback
description: Make videos in PowerPoint start on their own and stop on their last frame instead of jumping back to the first frame or stepping back a little just before the end. Use when a slide video rewinds after playing, when it seems to jump from 100 % back to 99 % at the end, when a video must start automatically with the slide, or when videos are added to slides by script (python-pptx) and lose their playback settings.
license: CC-BY-4.0
compatibility: PowerPoint for Microsoft 365 on Windows; ffmpeg to prepare video files; python-pptx and pywin32 only for scripting
metadata:
  bnw-scope: public
  bnw-status: draft
  bnw-updated: "2026-11-05"
---

# PowerPoint videos that stop on the last frame

A slide video should start with the slide and then stand still on its last frame, so the next slide can pick up from there (for example a rendered camera ride or a page turning). Two separate effects get in the way: the video jumps back to its first frame, or it stops a frame or two before the end, which looks like a small jerk backwards. Tested with PowerPoint for Microsoft 365 (version 16) on Windows in October 2026.

## By hand in PowerPoint

1. **Insert** > **Video** > **This Device**, pick the file.
2. Select the video, open the **Playback** tab:
   - **Start:** *Automatically* (plays as soon as the slide appears) or *When Clicked On*.
   - **Rewind after Playing:** leave it **unticked**. Then the video stays on its last frame.
   - **Hide While Not Playing:** unticked, otherwise the video disappears when it ends.
3. Optional: **Video Format** > **Poster Frame** sets the picture shown *before* playback. It does not change what is shown after the end.
4. **Prepare the file so the last frame lasts a moment** (see Rule 2). PowerPoint has no setting for this; it is fixed in the video file before inserting.

## Rules

1. **Rewind off is necessary, not sufficient, when slides are built by script.** A video inserted by hand gets a hidden media node in the slide timing. Scripts that replace the slide timing (for example to make the video start automatically) drop that node; the video then jumps back to its first frame even though PowerPoint reports *Rewind after Playing* as off. Put the node back. Details and XML: [references/scripted-decks.md](references/scripted-decks.md).
2. **PowerPoint stops slightly before the last frame.** Measured: it holds frame 22 of 24 and frame 46 of 48. Repeat the last frame for about half a second when encoding, then the frame PowerPoint holds equals the last one:

   ```
   ffmpeg -i ride.mp4 -vf "tpad=stop_mode=clone:stop_duration=0.5" -c:v libx264 -pix_fmt yuv420p -crf 16 -movflags +faststart ride_hold.mp4
   ```

   When cutting a clip at the same time, limit its length inside the filter (`trim=end_frame=N,setpts=PTS-STARTPTS,tpad=...`), not with `-frames:v`: that option counts output frames and cuts the repeated frames off again.
3. **Fallback without touching the video:** place a picture of the last frame on top of the video and let it appear after the clip length (**Animations** > **Appear**, *With Previous*, delay = clip length). This matches pixel for pixel but cuts off the end of the motion if the video starts late. Get the picture with `ffmpeg -sseof -0.1 -i ride.mp4 -frames:v 1 last.png`.
4. **The same early stop applies to 3D model animations**; see the `powerpoint-3d-models` skill (hold the end pose for about 0.2 s).

## Checking

- **Final check:** run the slide show and watch the end of each video. Nothing else covers the live player completely.
- **Without clicking through:** let PowerPoint render the deck to a video by COM (`Presentation.CreateVideo(target, True, 3, 720, 24, 85)`; `CreateVideoStatus` 1 and 2 mean running or queued, 3 done), then compare frames after the clip end with the first and last frame of the clip. The export matches the slide show in this respect but not in everything.

## References

- [references/scripted-decks.md](references/scripted-decks.md): read when adding videos with python-pptx or editing slide timing XML: the media node, an autoplay timing that keeps it, and findings.
