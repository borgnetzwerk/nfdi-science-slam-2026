# Places of 80 Poly Haven models (potted_plant_02), markers only

![Orange dots mark where the Poly Haven models stood](preview.png)

*Preview with simple shading. Grey surfaces on panels mark images that are not included (see below).*

Where furniture and plants from Poly Haven stood. Each place is an empty named after the asset, with its link; download the asset and parent it to the empty.

## Files

- [polyhaven_placements.blend](polyhaven_placements.blend) (0.1 MB): open in Blender 5.2 or newer (files saved in 5.2 do not open in 4.x; use the .glb there). The collection `polyhaven_placements` can be appended or linked into another scene; reuse beyond viewing and study needs the licence, which is still pending (see [LICENSE](../../LICENSE)).
- [polyhaven_placements.glb](polyhaven_placements.glb) (26 kB): glTF binary for other tools and game engines; text objects and some materials are simplified by the exporter.

## Using it

- Positions are the station's coordinates in metres, so modules fit together again when you link several of them; [../station.blend](../station.blend) links all of them. Object origins sit at the station centre, not at the room: press Home (View All) to find the module, and use Object > Set Origin > Origin to Geometry before you move a part on its own.
- Light and sky are in [environment](../environment/README.md); link it as well, otherwise the module renders unlit.
- Object names are German, as the scene was built with German names; [manifest.json](../manifest.json) lists every object.

## What is inside

| Collection | Objects |
|---|---|
| `polyhaven_placements.polyhaven_markers` | 80 |

## From Poly Haven (not included)


80 places of Poly Haven models, as empties named `PolyHaven <asset>`: [potted_plant_02](https://polyhaven.com/a/potted_plant_02). Download the model and parent it to the empty.
