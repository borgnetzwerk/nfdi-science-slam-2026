# Scene scripts

| Script | What it does |
|---|---|
| [station_scene.py](station_scene.py) | Builds the whole station: ring with city and museum, spokes and lifts, collector, hub with lobby, map room, modules and tube railway, ships; places the exhibits and panels from the storyboard; saves the scene or renders stills and the camera ride. |
| [szene_bausteine.py](szene_bausteine.py) | Building blocks shared by the scripts: materials (solid, glowing, textured), simple models, render settings. |
| [camera_moves.py](camera_moves.py) | Camera paths and easing for the ride. |
| [ride_motion.py](ride_motion.py) | A walking camera: pace, head movement and where the eye looks along the path. |
| [check_motion.py](check_motion.py) | Checks a camera ride against film-craft rules (speed, pans, rest at stops, level horizon). |
| [wkw_palette.py](wkw_palette.py) | The colour palette of the scene (house colours and the Okabe-Ito palette for categories). |
| [station_source.py](station_source.py) | Loads the station layout (dimensions, module plan) from the files in [../data/](../data/README.md). |
