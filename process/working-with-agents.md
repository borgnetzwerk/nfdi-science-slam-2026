# Working with an AI agent

The station was built by an AI agent (Claude) writing Blender scripts, under the direction of one person who described, sketched, marked up renders and decided. Over nine days that meant 64 rounds of dictated feedback. Looking back over all of it, about half of the 309 individual requests had been fully met by the eve of the talk; much of the rest was "done in code" but never seen in a picture. These are the working rules we would start with next time.

## Rough first, then detail

- **Variants A to G before any detail.** Every design question starts with several clearly different rough variants: a concept in one sentence, a sketch in seconds, a small probe scene instead of the whole station. Agree on one, then work it out and render it well.
- **At most ten minutes per iteration.** If one round of change, render and look takes longer, the probe is too big. Render a small test scene, not the whole station.
- **Concept graphics before Blender.** Floor plans, diagrams and flat images settle layout and story much faster than 3D renders.
- **Compare everything with the visual designer's template.** When a part is based on a designer's illustration, put the render next to the template and check shapes, colours and line style against it, not against memory.
- **Short iterations of the whole ride.** A rough version of the complete ride, early and often, shows the overall impression; depth in one room does not.

## Nothing is done until it is seen

- **Done means seen in the picture.** A change that exists only in code is not done. It is done when it has been rendered and looked at, in a still for content and in a video for movement.
- **The agent looks at every image before a human does,** and checks it critically: cut-off exhibits, the camera passing through glass or doors, flickering where two surfaces overlap, stops without a reason. If the human finds such errors first, the check failed.
- **Check in numbers, look selectively.** Automatic checks run on every panel; afterwards only panels that were flagged or whose image visibly changed are looked at, together on one contact sheet. This keeps the review cheap without letting errors through.
- **Movement only as video.** Stills cannot show whether a move feels right. Agents check content at about one frame per second; the human gets every movement as a video.
- **Recurring errors need a check, not another fix.** The same classes of error came back again and again (flickering seams, the camera clipping through glass, exhibits cut off at the frame edge, stops without reason) because each was fixed only where it was reported. A class of error that appears twice deserves an automatic test.

## Write requirements down

- **Every request becomes a file.** Spoken or dictated feedback is recorded word for word, and each requirement gets its own short file with a test that says when it is met. A requirement that lives only in a chat is lost when the session ends.
- **Check the register regularly against the whole.** Distributing feedback into many small tasks loses the overview; from time to time, read all feedback again and compare it with what is actually in the picture.
- **Lessons belong in the tools.** A lesson written in a document but not built into the pipeline is forgotten under time pressure. The rule "do not render still holds frame by frame" stayed a note for a day and cost hours of GPU time.

## One coordinating session, parallel strands

The last days ran as several agent sessions in parallel, each on one strand (a room, the hub, the deck, the render, this repository), with one central session coordinating: it owned the render queue and the GPU, collected questions for the human, and decided the order. Each strand asked the coordinator before using the GPU and reported its state in a file, not only in its chat. Questions for the human were collected and asked one at a time, with the files to look at.

## Further safeguards

- Never let an agent delete files; it moves them to a folder for a human to clear.
- Network access only after asking, and never with personal data.
- External sources are stored raw in the working repository before they are used, and every claim on a slide has a source.
- Long renders run in their own queue, independent of any agent session, so they survive a closed chat.
