# Tools

Small Python tools that turned the built scene and the talk's lists into this repository. They need Python 3 with PyYAML and Pillow, and Blender 5.2 for the ones that run inside Blender.

| Tool | What it does |
|---|---|
| [run_split.py](run_split.py) with [split_scene.py](split_scene.py) and [modules.yaml](modules.yaml) | Cuts a built `station.blend` into one folder per module (`.blend` and `.glb`), packs own images, leaves out third-party files and illustrations we may not license, links all modules into `station/station.blend` and writes `station/manifest.json`. Renders nothing. |
| [render_previews.py](render_previews.py) | Renders `preview.png` for every module folder with Blender's Workbench engine. |
| [build_lists.py](build_lists.py) | Writes the generated pages: `videos/`, `assets/`, `station/README.md` and each module's README. |
| [copy_shots.py](copy_shots.py) | Copies the chosen making-of shots into `making-of/images/`, scaled and cropped. |
| [check_paths.py](check_paths.py) | Runs inside Blender and fails if a `.blend` file carries local paths or folder names of the machine it was made on: in file paths, in the paths stored with packed images, and anywhere in the decompressed bytes (for example in saved file-browser settings). |
| [verify_cleanup.py](verify_cleanup.py) | Checks that the published copies of the scripts differ from the originals only in comments, documentation and descriptive notes. A few strings that carried internal notes are replaced the same way in scripts, data and Blender files; that list stays with the working material. |
| [apply_renames.py](apply_renames.py) | Applies that list of replacements to script and data files. |

## Commands

Cut the scene and rebuild the pages (from the repository root):

```
python tools/run_split.py <built station.blend> station --polyhaven <polyhaven.yaml>
python tools/build_lists.py --videos <videos.yaml> --polyhaven <polyhaven.yaml> --polyhaven-credits <credits.yaml> --nasa <nasa3d.yaml> --manifest station/manifest.json
```

Render the previews and check the files for local paths:

```
blender -b --factory-startup -P tools/render_previews.py -- station
blender -b station/station.blend --factory-startup -P tools/check_paths.py
```

The input lists (`videos.yaml`, `polyhaven.yaml` and the Poly Haven credits) are kept with the talk's working material and are not part of this repository; their content is what the generated pages show.

## Render and deck pipeline

These tools rendered the ride through the station, turned it into the PowerPoint deck of the talk and laid the credits for third-party works over the clips. How the steps fit together is described in [../process/pipeline.md](../process/pipeline.md), the credits overlay in [../process/credits-overlay.md](../process/credits-overlay.md).

They are published as they were used. Comments, messages and report fields are translated into English and internal notes are removed; paths of the working repository are replaced by paths relative to this repository's root (settings in `scripts/data/config.yaml`, scene scripts in `scripts/scene/`). Run them from the repository root; working files go to `_scratch/`. Because messages and report fields were translated, these copies are not meant to pass `verify_cleanup.py`.

| Tool | What it does | What it needs |
|---|---|---|
| [blender_run.py](blender_run.py) | Starts Blender without a user interface with a scene script from `scripts/scene/` and passes the settings, the station data and the storyboard to it as JSON, since Blender's Python has no YAML library. | Blender (the newest `Blender X.Y` folder with `blender.exe` under `blender.root` in `config.yaml`, so Windows as written), PyYAML; uses the optional helpers `render_slide_boards` and `gpu_queue` when they can be imported (see below). |
| [night_queue.py](night_queue.py) | Works through a list of long render jobs unattended in a console window, restarts crashed runs, moves half-written images aside, reports progress with an estimate and writes small previews; `clean`, `shutdown` and `status` can be typed in. | A jobs file (`--jobs`, YAML with `out`, `preview`, `parallel`, `retries`, `preview_every` and `jobs` with `name` and `args`), `blender_run.py`, Pillow, PyYAML; stops runs with `taskkill`, so Windows. |
| [build_pptx.py](build_pptx.py) | Builds the deck: one clip per click that starts by itself and holds its last frame, cuts at the stops where the camera rests, pieces taken from several render runs (final where available, preview otherwise), credits burnt in, and the final stop as a loop under the closing slide. | A deck section of `config.yaml`, rendered frames or a master video with `ride_check.json`, the storyboard, the template deck for the closing overlay; ffmpeg, python-pptx, lxml, PyYAML, Pillow, NumPy. |
| [credit_overlay.py](credit_overlay.py) | Draws the credits for third-party works as chat messages in the bottom left corner, as a transparent layer, and can put them on the storyboard panels. | `credits.yaml` (works and style) and `videos.yaml` in `scripts/data/`, `render_log.json` from a storyboard run of `station_scene.py`, `scripts/scene/wkw_palette.py`, Open Sans as `fonts/OpenSans[wdth,wght].ttf` (falls back to Arial); Pillow, PyYAML. |
| [credit_ride.py](credit_ride.py) | Works out when which credit is on screen, from the stops or frame by frame from the visibility of each work, and burns the chat layers into the ride video or into one clip of the deck. | `master.mp4` and `ride_check.json` of a ride, optionally `credit_frames.json` from `station_scene.py --credit-frames`, `credit_overlay.py`; ffmpeg and ffprobe. |
| [check_deck_cuts.py](check_deck_cuts.py) | Checks that every clip of a built deck starts and ends exactly on the frame of its stop and that the slide changes are invisible, and writes `cut_check.json`. | A built deck (`pieces.json`, or the master video for `from_ride`), `config.yaml`, `build_pptx.py`; ffmpeg, ffprobe, NumPy, Pillow, PyYAML. |
| [build_fallbacks.py](build_fallbacks.py) | Writes two fallbacks of a built deck: one video of all clips in order, and a deck with one still image per click. | `pieces.json` and the clips of a deck built from pieces; ffmpeg, python-pptx, Pillow. |
| [rerender_plan.py](rerender_plan.py) | After a change to the scene, plans a frame-exact re-render: reuses finished frames with the same camera pose (renamed when the timeline shifted), lists the frames to render again, and with `--apply` rebuilds the piece folders with hard links and moves the old folders to `segments/_old/`. | A check run of the new scene (`ride_path.json`, `ride_check.json`, optionally `rerender_input.json` from `station_scene.py --changed-frames`), the final render folder (`--final`) with `segments/`, the storyboard; PyYAML. |

Commands (from the repository root):

```
python tools/blender_run.py station_scene.py --building --storyboard scripts/data/storyboard_station.yaml --ride
python tools/night_queue.py --jobs <night_queue.yaml>
python tools/build_pptx.py station_final_deck
python tools/check_deck_cuts.py station_final_deck
python tools/build_fallbacks.py <deck folder> <name>
python tools/rerender_plan.py --new <check run folder> --final <final render folder>
```

Some paths in `scripts/data/config.yaml` still point to the talk's working folders (for example the template deck of the closing slide); the final render is expected under `_scratch/final`. Set them to local folders before running the deck tools.

### To follow

- `credits.yaml`, `videos.yaml` and an example jobs file for `night_queue.py`: the inputs of the credit and queue tools are still kept with the working material.
- `render_slide_boards.py`: renders the slides of a PowerPoint deck onto their panels and is still tied to the working folder layout; `blender_run.py` skips this step without it.
- `gpu_queue`: the shared GPU queue of the working repository, a service of its own; `blender_run.py` starts Blender directly without it.
