# Ring city: streets, houses, trees, people, fields, homes, bar

![Houses and streets standing on the inside of the ring, seen from the axis](preview.png)

*Preview with simple shading. Grey surfaces on panels mark images that are not included (see below).*

The city on the inside of the ring: streets, houses with lit windows, trees, people for scale, fields, terraced homes at the feet of the spokes and a bar.

## Files

- [ring_city.blend](ring_city.blend) (0.4 MB): open in Blender 5.2 or newer (files saved in 5.2 do not open in 4.x; use the .glb there). The collection `ring_city` can be appended or linked into another scene; reuse beyond viewing and study needs the licence, which is still pending (see [LICENSE](../../LICENSE)).
- [ring_city.glb](ring_city.glb) (1.6 MB): glTF binary for other tools and game engines; text objects and some materials are simplified by the exporter.

## Using it

- Positions are the station's coordinates in metres, so modules fit together again when you link several of them; [../station.blend](../station.blend) links all of them. Object origins sit at the station centre, not at the room: press Home (View All) to find the module, and use Object > Set Origin > Origin to Geometry before you move a part on its own.
- Light and sky are in [environment](../environment/README.md); link it as well, otherwise the module renders unlit.
- Object names are German, as the scene was built with German names; [manifest.json](../manifest.json) lists every object.

## What is inside

| Collection | Objects |
|---|---|
| `ring_city.bar` | 2 |
| `ring_city.trees_people` | 2 |
| `ring_city.fields` | 3 |
| `ring_city.houses` | 2 |
| `ring_city.homes` | 2 |
| `ring_city.streets` | 1 |
