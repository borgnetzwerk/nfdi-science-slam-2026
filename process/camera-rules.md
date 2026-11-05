# Camera rules

Rules for camera rides, animation and cuts, collected while building the talk. They are starting values from public sources, not laws: each threshold had to prove itself on test renders. Rules marked "checked automatically" are tested on the camera path by [../scripts/scene/check_motion.py](../scripts/scene/check_motion.py), which reports findings with these ids; the others are checked by looking at a contact sheet and a preview video. If a ride breaks a rule on purpose, the reason goes into the storyboard.

## Movement

**BW-1: Every movement accelerates from rest and slows down before the target (slow in, slow out).** No ride jumps to full speed or stops abruptly. Source: the "slow in and slow out" principle of the twelve basic principles of animation ([Wikipedia](https://en.wikipedia.org/wiki/Twelve_basic_principles_of_animation)); camera moves without easing run at constant speed and stop abruptly ([Toon Boom, add ease](https://docs.toonboom.com/help/storyboard-pro-20/storyboard/camera/add-ease.html)); real cranes and dollies have mass ([Studio Matrx](https://www.studiomatrx.org/students/architectural-visualization-rendering/camera-paths-and-walkthroughs)). Checked automatically: speed near zero at every stop.

**BW-2: A stop (click, slide change, end of a clip) lies only where the camera rests.** A clip that ends in the middle of a move stops the move abruptly, even if the ride in Blender is smooth. In Blender each stop is a timeline marker and a keyframe with flat tangents. Checked automatically.

**BW-3: Pace: brisk, but eased.** Architectural walkthroughs move slowly because the audience studies the rooms ([Studio Matrx](https://www.studiomatrx.org/students/architectural-visualization-rendering/camera-paths-and-walkthroughs); preferred human walking speed is about 1.1 to 1.5 m/s, [Wikipedia](https://en.wikipedia.org/wiki/Preferred_walking_speed)). In a slam the speaker carries the content and the ride connects, so our first full ride was far too slow. Starting values: peak at most 4 m/s indoors and 8 m/s outdoors, with a stated reason for exceptions (for example a drone-like approach from outside). Checked automatically: peak speed per segment.

**BW-4: Pans: the picture moves at most one frame width in seven seconds.** At 24 frames per second with a 180 degree shutter, a pan judders visibly when content crosses the frame faster than that ([RED, camera panning speed](https://www.red.com/red-101/camera-panning-speed)); when the camera follows a subject, more is allowed because the eye rests on the subject ([PremiumBeat](https://www.premiumbeat.com/blog/cinematography-tip-capture-smooth-panning-shots-at-24fps)). Consequence for the room plan: turns cost the most time, so place stops so the camera glides along things instead of turning to face them; where a big turn would be needed, a cut is better (BW-13). Checked automatically: angular speed.

**BW-5: Turn gently and preferably while moving forward; never spin on the spot.** Turning on the spot and whipping round corners cause nausea ([Studio Matrx](https://www.studiomatrx.org/students/architectural-visualization-rendering/camera-paths-and-walkthroughs)); large movements of the whole scene and sudden acceleration are the most common triggers of discomfort, stronger on large screens ([Android XR motion guidelines](https://developer.android.com/design/ui/xr/guides/motion)).

**BW-6: Level horizon, constant eye height.** No unmotivated roll, no bobbing horizon; eye height about 1.5 to 1.6 m and constant during the ride ([Studio Matrx](https://www.studiomatrx.org/students/architectural-visualization-rendering/camera-paths-and-walkthroughs)). Checked automatically: roll angle and height variation.

**BW-7: The camera never passes through walls, pillars, glass or ceilings.** A smooth curve through keyframes can bulge into geometry; check the actual path and correct it with an extra guide keyframe. In Blender, "Automatic" handles overshoot; "Auto Clamped" is the recommended default ([Blender manual, F-Curve properties](https://docs.blender.org/manual/en/latest/editors/graph_editor/fcurves/properties.html)). Glass is easy to miss in an automatic path check; check it explicitly.

**BW-8: Few keyframes, wide arcs.** Few, widely spaced key positions give calm rides; many close ones make the path tremble. Natural movement follows arcs, not zigzags (the "arcs" principle, [Wikipedia](https://en.wikipedia.org/wiki/Twelve_basic_principles_of_animation)). Guide value: one keyframe per stop plus at most one guide keyframe.

## Holding and showing

**BW-9: Let important views land.** Before an important picture the camera slows almost to a standstill and gives the room time ([Studio Matrx](https://www.studiomatrx.org/students/architectural-visualization-rendering/camera-paths-and-walkthroughs)). In a clicked talk every stop is such a hold; content that must be read stays still until the next click.

**BW-10: Every move has a reason and a target.** A motivated move answers what happens and serves the story ([No Film School](https://nofilmschool.com/2018/06/key-good-camera-movement-motivation)); a clear point the camera moves towards gives the eye something to hold, drifting without a target feels vague and makes people sick. The storyboard states where and why for every move.

**BW-11: One focus per stop, with room in the direction of movement.** Make clear what matters most in the shot (staging, [Wikipedia](https://en.wikipedia.org/wiki/Twelve_basic_principles_of_animation)); place the main subject by the [rule of thirds](https://en.wikipedia.org/wiki/Rule_of_thirds) and leave [lead room](https://en.wikipedia.org/wiki/Lead_room) in the direction of gaze or travel. A wall panel that must be read may fill the frame.

**BW-12: A big move announces itself.** Before a big action a small counter-movement prepares the audience (anticipation, [Wikipedia](https://en.wikipedia.org/wiki/Twelve_basic_principles_of_animation)); for the camera, a short slow start before a big pull-back or turn. Optional, by feel.

## Cuts and orientation

**BW-13: Keep orientation.** When the ride enters a new room, show it as a whole before going into detail ([establishing shot](https://en.wikipedia.org/wiki/Establishing_shot)). When cutting between views of the same scene, stay on one side of the line between the main objects ([180-degree rule](https://en.wikipedia.org/wiki/180-degree_rule)). Connect sets through a shared picture element ([match cut](https://en.wikipedia.org/wiki/Match_cut)), for example a slide that becomes a wall.

## Technique

**BW-14: 60 frames per second for fast rides, otherwise 24 with a 180 degree shutter.** At 60 frames per second the judder of fast pans practically disappears ([PremiumBeat](https://www.premiumbeat.com/blog/cinematography-tip-capture-smooth-panning-shots-at-24fps)), so a pan may cross a frame width in 2.5 instead of 7 seconds (BW-4); projectors and PowerPoint play 60 fps. At 24 fps a larger shutter angle makes pans smoother and blurrier, a smaller one sharper and more juddery ([RED](https://www.red.com/red-101/camera-panning-speed)). In Blender: motion blur on, shutter 0.5 (180 degrees); test it on a probe first.

## Further lessons for walking rides

These came later, after the first full ride through the museum felt like being catapulted from stop to stop:

- One walking speed for the whole ride, changed only with a reason (we ended at a brisk 2.2 m/s indoors); never stop in a door frame.
- A very small head bob, only while walking, and smaller while the gaze rests on an exhibit; VR comfort guidelines advise against head bob altogether.
- The gaze holds the target while the body sways beneath it; the gaze leads the path by about 0.5 to 1.5 seconds before a turn, as people look where they will go before they step there.
- Look around like a head: turns ease in and out with a peak of about 120 degrees per second, and straightening the horizon is never faster.
- Walk a museum like a visitor: look at the room on entering, visit the exhibits in one direction, never go back, and let the next door be the last view.
- Against motion sickness: short and rare accelerations, no sideways sliding, one focal length for the whole ride (we used 22 mm) and no zooming while moving, constant frame rate within a clip.

## Storyboard conventions

Panels in the aspect ratio of the film, rendered from the scene rather than drawn; numbered "scene.shot" with letters for inserted panels; shot size and angle named on each panel; the camera move written at the panel; what is seen, heard and how long in the margin; key frames only, one panel per stop. Background: [storyboard](https://en.wikipedia.org/wiki/Storyboard), [shot](https://en.wikipedia.org/wiki/Shot_(filmmaking)), [camera angle](https://en.wikipedia.org/wiki/Camera_angle).
