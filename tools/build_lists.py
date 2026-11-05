"""Build the generated pages of this repository from the talk's source lists and the station manifest.

Usage:
    python tools/build_lists.py --videos videos.yaml --polyhaven polyhaven.yaml --polyhaven-credits credits.yaml --nasa nasa3d.yaml --manifest station/manifest.json

Writes videos/README.md, assets/README.md, station/README.md and station/<module>/README.md. Third-party files are never copied, only linked.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parent.parent


def load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) if path else {}


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def cell_text(text):
    """Text for a Markdown table cell: a bare | would split the row."""
    return str(text).replace("|", "\\|")


def videos_page(videos):
    lines = ["# Recommended videos", "",
             "Videos that shaped this talk or appear as exhibits in the station. We only link to them; no copies are kept here. Excerpts shown in the talk were short quotations with the creator named on screen.", "",
             "| Video | Creator | Year | Topics |", "|---|---|---|---|"]
    for v in videos.get("cited", []):
        year = v.get("year") or str(v.get("published", ""))[:4] or ""
        lines.append(f"| [{cell_text(v['title'])}]({v['url']}) | {cell_text(v['creator'])} | {year} | {', '.join(v.get('keywords', []))} |")
    lines += ["", "## Earlier talks of this series", "", "Recordings of earlier talks by the same speaker, oldest first, as on the timeline in museum room 2.", "",
              "| Date | Talk |", "|---|---|"]
    for t in sorted(videos.get("own_talks", []), key=lambda t: str(t.get("date", ""))):
        title = cell_text(t.get("title", t.get("wall_title", t["id"])))
        cell = f"[{title}]({t['url']})" if t.get("url") else f"{title} (no recording)"
        lines.append(f"| {t.get('date', '')} | {cell} |")
    return lines


def assets_page(polyhaven, ph_credits, nasa, manifest):
    used = {}
    for module in manifest.get("modules", []):
        for p in module.get("polyhaven", []):
            used.setdefault(p["id"].lower(), set()).add(module["id"])
        for image in module.get("images", []):
            if image.get("polyhaven_id"):
                used.setdefault(image["polyhaven_id"].lower(), set()).add(module["id"])
    lines = ["# Third-party assets", "",
             "Assets by others that were used while building the station. None of their files are in this repository; download them from the source. In the Blender files, Poly Haven textures are referenced under `station/textures/polyhaven/<asset>/` and placed Poly Haven models are empties named `PolyHaven <asset>` with the custom properties `url` and `licence`.", "",
             "## Poly Haven (CC0)", "",
             "Thank you, Poly Haven, for making high-quality assets free for everyone. \"Used in\" names the module of the current scene; assets marked \"earlier versions\" were used in the first library version of the scene and are listed for completeness.", "",
             "| Asset | Authors | Resolution | Used in |", "|---|---|---|---|"]
    seen = set()
    for a in polyhaven.get("assets", []):
        if a["id"] in seen:
            continue
        seen.add(a["id"])
        info = ph_credits.get(a["id"], {})
        modules = ", ".join(f"[{m}](../station/{m}/README.md)" for m in sorted(used.get(a["id"].lower(), []))) or "earlier versions"
        lines.append(f"| [{info.get('name', a['id'])}](https://polyhaven.com/a/{a['id']}) | {', '.join(info.get('authors', [])) or 'see source'} | {a.get('resolution', '')} | {modules} |")
    lines += ["", "## NASA 3D Resources (reference only)", "",
              "No NASA model is part of the scene. We looked at these models of the International Space Station as a reference for the modules, radiators and connectors on the hub, which were then built from simple shapes:", ""]
    lines += [f"- [{a['slug']}](https://science.nasa.gov/3d-resources/{a['slug']}/)" for a in nasa.get("assets", [])]
    lines += ["", "## Putting the Poly Haven files back", "",
              "On each asset's page, download the JPG maps (Diffuse, Normal GL, Roughness) at the resolution in the table and put them into `station/textures/polyhaven/<asset>/` with Poly Haven's file names; Blender finds them the next time you open a module. The exact file names each module expects are listed in its README and in `station/manifest.json`.", "",
              "## Font and software", "",
              "- Font: Open Sans by Steve Matteson (SIL Open Font License 1.1) appears in the panel images; 3D text objects use Blender's built-in font.",
              "- [Blender](https://www.blender.org) (GPL): scene and rendering. [FFmpeg](https://ffmpeg.org): video. [yt-dlp](https://github.com/yt-dlp/yt-dlp): video excerpts for the talk."]
    return lines


def size(n):
    return f"{n / 1e6:.1f} MB" if n >= 1e5 else f"{max(n, 1) / 1e3:.0f} kB"


def module_page(m):
    own = sorted({i["file"] for i in m["images"] if i["kind"] == "own"})
    withheld = sorted({(i["file"], i["reason"]) for i in m["images"] if i["kind"] == "withheld"})
    ph_textures = sorted({i["polyhaven_id"] for i in m["images"] if i["kind"] == "polyhaven"})
    ph_places = sorted({p["id"] for p in m.get("polyhaven", [])})
    ph_files = sorted({(i["polyhaven_id"], i["file"]) for i in m["images"] if i["kind"] == "polyhaven"})
    lines = [f"# {m['title']}", "", f"![{m.get('alt') or m['title']}](preview.png)", "",
             "*Preview with simple shading. Grey surfaces on panels mark images that are not included (see below).*", "",
             m.get("description", ""), "",
             "## Files", "",
             f"- [{m['id']}.blend]({m['id']}.blend) ({size(m['bytes'])}): open in Blender 5.2 or newer (files saved in 5.2 do not open in 4.x; use the .glb there). The collection `{m['id']}` can be appended or linked into another scene; reuse beyond viewing and study needs the licence, which is still pending (see [LICENSE](../../LICENSE))."]
    if m.get("glb"):
        lines.append(f"- [{m['id']}.glb]({m['id']}.glb) ({size(m['glb_bytes'])}): glTF binary for other tools and game engines; text objects and some materials are simplified by the exporter.")
    lines += ["", "## Using it", "",
              "- Positions are the station's coordinates in metres, so modules fit together again when you link several of them; [../station.blend](../station.blend) links all of them. Object origins sit at the station centre, not at the room: press Home (View All) to find the module, and use Object > Set Origin > Origin to Geometry before you move a part on its own.",
              "- Light and sky are in [environment](../environment/README.md); link it as well, otherwise the module renders unlit.",
              "- Object names are German, as the scene was built with German names; [manifest.json](../manifest.json) lists every object.", "",
              "## What is inside", "", "| Collection | Objects |", "|---|---|"]
    for eid, names in m["elements"].items():
        lines.append(f"| `{m['id']}.{eid}` | {len(names)} |")
    if own:
        lines += ["", f"{len(own)} {'image is' if len(own) == 1 else 'images are'} packed into the .blend file."]
    if ph_textures or ph_places:
        lines += ["", "## From Poly Haven (not included)", ""]
        if ph_files:
            lines.append("Put these files into `station/textures/polyhaven/<asset>/` (download from the linked page, see [../../assets/README.md](../../assets/README.md)):")
            lines.append("")
            lines += [f"- [{a}](https://polyhaven.com/a/{a}): `{f}`" for a, f in ph_files]
        if ph_places:
            lines += ["", f"{len(m['polyhaven'])} places of Poly Haven models, as empties named `PolyHaven <asset>`: " + ", ".join(f"[{p}](https://polyhaven.com/a/{p})" for p in ph_places) + ". Download the model and parent it to the empty."]
    if withheld or m.get("withheld_objects"):
        lines += ["", "## Left out on purpose", "",
                  "These are works by others or illustrations we cannot license. Materials keep their image slot: a picture saved as `station/withheld/<file name>` appears in place. Left-out objects are empties named `Withheld <name>` at the same place.", ""]
        lines += [f"- `{f}`: {r}" for f, r in withheld]
        reasons = sorted({o["reason"] for o in m.get("withheld_objects", [])})
        for r in reasons:
            count = sum(1 for o in m["withheld_objects"] if o["reason"] == r)
            lines.append(f"- {count} objects: {r}")
    return lines


def station_page(manifest):
    modules = [m for m in manifest["modules"] if m["id"] != "unassigned"]
    total = sum(m["objects"] for m in modules)
    lines = ["# The station", "",
             f"The objects built for the talk, cut into {len(modules)} modules with {total} objects in all. Each module has its own folder with a README, a preview, the Blender file and a glTF file, so you can explore room by room and, once a licence is chosen (see [../LICENSE](../LICENSE)), reuse a single part.", "",
             "Start with [station.blend](station.blend): it links every module as a collection instance and shows the whole station in its starting position. The camera ride of the talk is not included as a camera; it is computed by [../scripts/scene/ride_motion.py](../scripts/scene/ride_motion.py) from the stops in the storyboard.", "",
             "Key numbers: units are metres at scale 1; the origin lies on the rotation axis and z points along the axis to the sun. The ring floor has a radius of 286.5 m and turns at 1.77 revolutions per minute for 1 g; the ring is 150 m deep along the axis. Files were saved with Blender 5.2 (EEVEE).", "",
             "| Module | What it is | Objects |", "|---|---|---|"]
    for m in modules:
        lines.append(f"| [{m['id']}]({m['id']}/README.md) | {m['title']} | {m['objects']} |")
    lines += ["", "## How these files were made", "",
              "The scene is generated by the Python scripts in [../scripts/](../scripts/README.md) inside Blender. The built scene was saved once and cut into modules with [../tools/run_split.py](../tools/run_split.py) (rules in [../tools/modules.yaml](../tools/modules.yaml)); previews come from [../tools/render_previews.py](../tools/render_previews.py). [manifest.json](manifest.json) lists per module its collections, objects, images and what was left out.", "",
              "## What is not included", "",
              "Poly Haven files (see [../assets/README.md](../assets/README.md)), illustrations by Gerrit Hansen (Borgis, logos) and works by others shown on panels (video stills, photos, book covers). Each module README says what is missing there."]
    withheld = manifest.get("withheld_modules", [])
    if withheld:
        lines += ["", "Parts of the station that are left out as a whole for now:", ""]
        lines += [f"- {w.get('title', w['id'])}: {w['reason']}" for w in withheld]
    if manifest.get("note"):
        lines += ["", manifest["note"]]
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--videos", required=True)
    parser.add_argument("--polyhaven", required=True)
    parser.add_argument("--polyhaven-credits", required=True)
    parser.add_argument("--nasa", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    station = Path(args.manifest).resolve().parent
    # titles and texts come from modules.yaml, so a wording change needs no new cut of the scene
    texts = {m["id"]: m for m in load(Path(__file__).with_name("modules.yaml"))["modules"]}
    for m in manifest["modules"]:
        for key in ("title", "description", "alt"):
            if texts.get(m["id"], {}).get(key):
                m[key] = texts[m["id"]][key]
        if m["id"] == "polyhaven_placements":
            kinds = sorted({p["id"] for p in m["polyhaven"]})
            m["title"] = f"Places of {len(m['polyhaven'])} Poly Haven models ({', '.join(kinds)}), markers only"
            m["alt"] = "Orange dots mark where the Poly Haven models stood"
    write(REPO / "videos" / "README.md", videos_page(load(args.videos)))
    write(REPO / "assets" / "README.md", assets_page(load(args.polyhaven), load(args.polyhaven_credits), load(args.nasa), manifest))
    write(station / "README.md", station_page(manifest))
    for m in manifest["modules"]:
        if m["id"] != "unassigned":
            write(station / m["id"] / "README.md", module_page(m))
    print(f"written: videos, assets, station and {len(manifest['modules'])} module pages")


if __name__ == "__main__":
    main()
