# Videos in scripted decks

For decks built with python-pptx. October 2026, PowerPoint for Microsoft 365 on Windows.

## The media node

`slide.shapes.add_movie(...)` writes a `p:timing` block that contains, besides the click sequence, a media node for the video:

```xml
<p:video>
  <p:cMediaNode vol="80000">
    <p:cTn id="20" fill="hold" display="0">
      <p:stCondLst><p:cond delay="indefinite"/></p:stCondLst>
    </p:cTn>
    <p:tgtEl><p:spTgt spid="{shape id of the video}"/></p:tgtEl>
  </p:cMediaNode>
</p:video>
```

`fill="hold"` keeps the last frame after playback. It belongs into the root time node, after the main sequence: `p:timing/p:tnLst/p:par/p:cTn[@nodeType="tmRoot"]/p:childTnLst`, after `p:seq`. The `id` must be unique among the `cTn` ids of the slide.

## Autoplay without losing the node

A common way to make a video start with the slide is to replace the whole `p:timing` with a sequence whose first effect plays the media (`presetClass="mediacall"`, `p:cmd type="call" cmd="playFrom(0.0)"`, start condition `evt="onBegin"`, `nodeType="afterEffect"`). That replacement drops the media node. Append the node again after building the new timing:

```python
from lxml import etree

P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
timing = etree.fromstring(AUTOPLAY.format(spid=movie.shape_id))   # your autoplay timing
root_children = timing.find(".//" + P + "cTn[@nodeType='tmRoot']/" + P + "childTnLst")
root_children.append(etree.fromstring(MEDIA_NODE.format(spid=movie.shape_id)))
```

Place `p:timing` at its fixed position in the slide (after `p:clrMapOvr`, before `p:extLst`); elsewhere the file becomes invalid.

## Findings

### Video jumps back to its first frame

- **Seen:** an autoplaying video returns to its first frame when it ends; PowerPoint reports `PlaySettings.RewindMovie = False`.
- **Why:** the autoplay timing replaced the timing written by python-pptx, and the media node with `fill="hold"` was gone.
- **Helps:** append the media node to the root time node (above). Then the last frame stays.

### Small jerk just before the end

- **Seen:** with the media node in place the video holds a frame slightly before the end (frame 22 of 24, frame 46 of 48). Live it looks as if the clip runs to 100 % and steps back to 99 %.
- **Why:** PowerPoint's player stops a little before the last frame; no setting changes it.
- **Helps:** repeat the last frame for 0.5 s when encoding (`tpad=stop_mode=clone:stop_duration=0.5`), length limited with `trim`, not `-frames:v`.

### A black flash when the slide opens

- **Helps:** put the first frame as a full-slide picture behind the video and pass it as `poster_frame_image` to `add_movie`.
