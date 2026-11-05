# Skills: tool knowledge for people and AI agents

What we learned about PowerPoint and Blender while building this talk, written down so that both people and AI agents can use it. Each folder is one skill in the [Agent Skills](https://agentskills.io) format: `SKILL.md` says when it applies and gives the essential rules (the PowerPoint skills start with the steps by hand in PowerPoint); `references/` holds findings and details.

| Skill | Answers questions like |
|---|---|
| [powerpoint-video-playback](powerpoint-video-playback/SKILL.md) | How does a slide video start by itself and stay on its last frame instead of jumping back to the start? Why does it jerk back a little just before the end? |
| [powerpoint-3d-models](powerpoint-3d-models/SKILL.md) | How do I put an animated 3D model (the turning book) on slides, morph between views, and play it piece by piece, per click or per slide? |
| [blender-gltf-export](blender-gltf-export/SKILL.md) | How do I export a Blender object to glTF (GLB) so that PowerPoint plays its animation and the file stays small? |

To use them with an agent such as Claude Code, copy a folder into `.claude/skills/` of your project. Status: drafts, tested on this talk in October and November 2026 with PowerPoint for Microsoft 365 on Windows and Blender 5.2.
