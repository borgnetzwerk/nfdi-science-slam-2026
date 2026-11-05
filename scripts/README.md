# Scripts

The whole station was generated from these Python scripts inside Blender; nothing was modelled by hand. They are published as they were used for the talk, with the comments translated into English and internal notes removed. The code itself is unchanged, which is why object names and messages are still German.

| Folder | What is in it |
|---|---|
| [scene/](scene/README.md) | The scripts that build the scene: station, museum, hub, materials, camera moves and motion checks |
| [data/](data/README.md) | Their inputs: settings, the station's dimensions and design, the exhibits and camera stops, the module plan of the hub |

## Can I rebuild the scene from here?

Not yet out of the box. The scripts are the exact code that built the station, so you can read how every part is made, but they still expect the folder layout of the talk's working repository:

- They are started by a small runner that reads the YAML settings and passes them to Blender as JSON (Blender's own Python has no YAML library): [../tools/blender_run.py](../tools/blender_run.py). Its optional GPU queue and panel-image helpers are not included.
- `station_source.py` loads the hub layout from `hub_layout.yaml` and keeps snapshots with a helper that is not part of this repository.
- Some paths point to working folders (`_scratch/...`, `media/polyhaven`, the font file); the pictures on panels and walls were made by further scripts from the talk's material and are not all included.
- The globe in the museum's centre room and in the map room is left out of this repository for now, together with its script. `station_scene.py` still imports that script (`from datenbaum import ...`), so it stops at that line until the globe part is removed or replaced.
- `check_motion.py` labels its findings with short rule ids (`BW-1` to `BW-14`); the rules are listed with their sources in [../process/camera-rules.md](../process/camera-rules.md).

To look at or study the station, start from the Blender files in [../station/](../station/README.md). Reuse beyond that needs the licence, which is still pending (see [../LICENSE](../LICENSE)).
