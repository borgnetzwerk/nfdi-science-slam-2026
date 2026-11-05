# Sun, scattered light, star field

![Dark sky with faint stars](preview.png)

*Preview with simple shading. Grey surfaces on panels mark images that are not included (see below).*

The sun, a soft light from the shadow side and about 1,200 stars around the station. Link it into any scene for the same light and sky.

## Files

- [environment.blend](environment.blend) (0.5 MB): open in Blender 5.2 or newer (files saved in 5.2 do not open in 4.x; use the .glb there). The collection `environment` can be appended or linked into another scene; reuse beyond viewing and study needs the licence, which is still pending (see [LICENSE](../../LICENSE)).
- [environment.glb](environment.glb) (2.5 MB): glTF binary for other tools and game engines; text objects and some materials are simplified by the exporter.

## Using it

- Positions are the station's coordinates in metres, so modules fit together again when you link several of them; [../station.blend](../station.blend) links all of them. Object origins sit at the station centre, not at the room: press Home (View All) to find the module, and use Object > Set Origin > Origin to Geometry before you move a part on its own.
- Light and sky are in [environment](../environment/README.md); link it as well, otherwise the module renders unlit.
- Object names are German, as the scene was built with German names; [manifest.json](../manifest.json) lists every object.

## What is inside

| Collection | Objects |
|---|---|
| `environment.sun` | 2 |
| `environment.stars` | 1207 |
