# Credits overlay

Whenever a work by someone else is visible in the ride (a video on a screen, a photo, a book cover, a quotation on a wall), it is credited on screen while it is visible. The credit looks like a message in a live-stream chat: a small grey date as timestamp, the creator's name in bold and colour followed by a colon, then the title of the work.

## Behaviour

- **Chat style, newest on top.** A new credit is added on top and the block grows; the older messages stay where they are. A message appears at once (pop), without fading in, and is never re-packed or cross-faded with the others. At most three messages are shown.
- **From the first visible frame.** A credit starts in the first frame in which the work can be seen, not when the camera arrives at the panel; four seconds late is clearly noticeable. It ends when the work leaves the picture; very short gaps (a pillar or frame passing in front) count as continuously visible, and a work visible for less than half a second does not count.
- **What counts as visible.** For every frame, a grid of points on the work is tested against the camera: is the point inside the frame, and is the line of sight to it free? A work counts as visible when at least 25 % of its points are seen. A screen seen from behind does not count: only its front side carries the work.
- **Own works are not credited.** The speaker's own earlier talks shown in the station need no credit; the chat stays empty there.
- **Credits set by hand.** Some works cannot be tested geometrically, for example a photo printed on a book page. Such credits are assigned to a stop by hand and apply only during that stop's hold, from arrival to departure.
- **Readability.** The box sits inside the graphics safe area (5 % margin on each side, [EBU R 95](https://tech.ebu.ch/docs/r/r095.pdf)); the font is at least 1/40 of the picture height; every text colour reaches a contrast of at least 4.5:1 against the box over pure white ([WCAG 2.2, contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)), stricter than needed for large text because projectors lose contrast. Text never stands on its own in front of the scene. With no third-party work in view, the layer is empty, background included.

There is no standard for stream chat overlays; common chat widgets offer the same settings (name and message in one line, adjustable fade time, dark or transparent background, optional timestamp). Our timing is driven by visibility, because a message here names a work rather than showing a conversation.

## How it is built

1. The scene script computes the visibility of every credited work per frame during a check run and writes it to a file (`credit_frames.json`).
2. The works, their creators, dates and titles, and the flag for own works are kept in a credits list; each placeholder in the storyboard names the work it shows.
3. [../tools/credit_overlay.py](../tools/credit_overlay.py) draws the chat box as a transparent image (rounded corners drawn at four times the size and scaled down for clean edges).
4. [../tools/credit_ride.py](../tools/credit_ride.py) turns the visibility into time spans and burns the layers into the clips with ffmpeg. Frame numbers of the check run are mapped onto the rendered run via the stops, so the overlay stays frame-exact even if the timing of the render differs.

Because the overlay is applied after rendering, a wrong or late credit is fixed in minutes without touching the 3D scene.
