"""Single source for the station layout.

Two kinds of files:
- building.yaml and hub_layout.yaml: maintained by people (decisions, dimensions, proposals with comments). Tools read
  them but never rewrite them line by line.
- station_plan.json: the state of the station planner. The tool owns this file and always writes it as a whole: per module
  its position (cells), start, depth, processes and fixtures, per museum room its fixtures. Like the scene files of Godot
  (TSCN) or Unity: text that works well in Git, but without hand-written comments.

Readers get the layout only from here: load_station() returns the station block of building.yaml with the planner's
values applied on top, load_layout() returns hub_layout.yaml with cells_fixed taken from the planner. This way the
planner, the floor sketches, the slide export and the Blender scene all see the same plan. The planner itself is not
imported, so the other readers keep working without it.

One-off migration of the values from the YAML files into station_plan.json:
    python station_source.py --migrate
Summary without changes:
    python station_source.py
"""
import copy
import json
import os
import re
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE.parents[1] / "_meta" / "Scripts"))
import state_snapshots  # noqa: E402  (snapshots of the previous state before every write)
BUILDING = BASE / "building.yaml"
HUB_LAYOUT = BASE / "hub_layout.yaml"
STATE = BASE / "station_plan.json"
FORMAT = 1
MODULE_FIELDS = ("cells", "start", "depth", "processes", "fixtures")   # owned by the planner, not by building.yaml
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)   # LibYAML, many times faster (PyYAML documentation)


def yaml_load(text: str):
    return yaml.load(text, Loader=_Loader)


def read_yaml(path: Path):
    return yaml_load(path.read_text(encoding="utf-8")) if path.exists() else None


# ================================================================ Planner state

def empty_state() -> dict:
    return {"format": FORMAT, "note": "Zustand des Stationsplaners; vom Werkzeug ganz geschrieben, nicht von Hand "
                                      "bearbeiten. Entscheidungen und Maße: building.yaml.",
            "modules": {}, "rooms": {}, "hub": {}}


class StateMissing(FileNotFoundError):
    """station_plan.json is missing: never carry on silently with an empty state, that would lose the whole plan."""


def load_state(path: Path = None, allow_missing: bool = False) -> dict:
    """Read the state. A missing file is an error (StateMissing); only the one-off migration may start empty."""
    path = path or STATE
    if not path.exists():
        if allow_missing:
            return empty_state()
        raise StateMissing(f"{path.name} fehlt ({path}); Stand aus Git oder einer Sicherung wiederherstellen, nicht leer weiterarbeiten")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("format") != FORMAT:
        raise ValueError(f"{path.name}: format {state.get('format')} unbekannt (erwartet {FORMAT})")
    state.setdefault("modules", {})
    state.setdefault("rooms", {})
    state.setdefault("hub", {})   # hub.corridors.cells: corridors placed by hand
    return state


def _compact(value, indent: int, level: int) -> str:
    """Indented JSON, but lists of numbers and individual fixtures each on one line (readable diffs)."""
    pad, inner = " " * (indent * level), " " * (indent * (level + 1))
    if isinstance(value, dict) and value and not all(isinstance(v, (dict, list)) for v in value.values()) and level >= 3:
        return json.dumps(value, ensure_ascii=False)   # fixture: one line per element
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {_compact(v, indent, level + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(value, list):
        scalar = lambda v: not isinstance(v, (dict, list))   # noqa: E731
        if all(scalar(v) or (isinstance(v, list) and all(scalar(x) for x in v)) for v in value):
            return json.dumps(value, ensure_ascii=False)   # numbers, process ids, hex cells [q, r]: one line
        items = [f"{inner}{_compact(v, indent, level + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    return json.dumps(value, ensure_ascii=False)


def dumps_state(state: dict) -> str:
    return _compact(state, 2, 0) + "\n"


def snapshots(path: Path = None) -> "state_snapshots.Snapshots":
    """Snapshots of the state: folder planner/data/snapshots next to the state file, so that copies used in tests
    keep their own snapshots."""
    path = path or STATE
    return state_snapshots.Snapshots(path, path.parent / "planner" / "data" / "snapshots")


def save_state(state: dict, path: Path = None, reason: str = "") -> bool:
    """Write the whole state (atomically via a sibling file), only if something changed. Before writing, a snapshot
    of the previous state is taken (with rotation)."""
    path = path or STATE
    if not state.get("hub"):   # an empty hub block (default from load_state) is not written to the file
        state = {k: v for k, v in state.items() if k != "hub"}
    text = dumps_state(state)
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return False
    if old is not None and json.loads(old).get("modules") and not state.get("modules"):
        raise ValueError(f"{path.name}: ein Stand mit Modulen würde durch einen leeren überschrieben; nicht geschrieben")
    snapshots(path).snapshot(reason)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return True


# ================================================================ Reading with the planner state applied

def apply_station(station: dict, state: dict) -> dict:
    """Station block with the planner's values (start, depth, processes, fixtures per module; fixtures per museum room)."""
    station = copy.deepcopy(station)
    # modules removed in the planner (removed) are hidden from all readers; the entry stays in the state and can be restored
    gone = {mid for mid, e in state["modules"].items() if e.get("removed")}
    station["modules"] = [m for m in station.get("modules", []) if m["id"] not in gone]
    for m in station.get("modules", []):
        for key in ("start", "depth", "processes", "fixtures"):
            if key in state["modules"].get(m["id"], {}):
                m[key] = copy.deepcopy(state["modules"][m["id"]][key])
    for room in (station.get("museum") or {}).get("rooms", []):
        if "fixtures" in state["rooms"].get(room["id"], {}):
            room["fixtures"] = copy.deepcopy(state["rooms"][room["id"]]["fixtures"])
    return station


def apply_layout(layout: dict, state: dict) -> dict:
    """hub_layout.yaml with the positions from the planner: a module with cells in the state counts as fixed (cells_fixed)."""
    layout = copy.deepcopy(layout or {})
    gone = {mid for mid, e in state["modules"].items() if e.get("removed")}
    layout["modules"] = [m for m in layout.get("modules", []) if m["id"] not in gone]
    # Corridors are only placed by hand: hex cells from the state, from which the dense layout builds the corridor modules
    layout["corridors_manual"] = [list(c) for c in state.get("hub", {}).get("corridors", {}).get("cells", [])]
    if "requirements" in layout:
        layout["requirements"] = [r for r in layout["requirements"] if r.get("a") not in gone and r.get("b") not in gone]
    for m in layout.get("modules", []):
        cells = state["modules"].get(m["id"], {}).get("cells")
        if cells:
            m["cells_fixed"] = [list(c) for c in cells]
    return layout


def load_station(building: Path = None, state: Path = None) -> dict:
    return apply_station(read_yaml(building or BUILDING)["station"], load_state(state))


def load_layout(layout: Path = None, state: Path = None) -> dict:
    return apply_layout(read_yaml(layout or HUB_LAYOUT), load_state(state))


def set_cells(moves: dict, state_path: Path = None) -> None:
    """Fix the position of several modules ({id: [[q, r], ...]}); used when importing the plan from a slide deck."""
    state = load_state(state_path)
    for mid, cells in moves.items():
        state["modules"].setdefault(mid, {})["cells"] = [list(c) for c in cells]
    save_state(state, state_path, reason="Import aus plan.pptx: " + ", ".join(sorted(moves)))


# ================================================================ One-off migration from the YAML files

def _remove_flow_field(line: str, key: str) -> str:
    return re.sub(rf", {re.escape(key)}: (\[[^\]]*\]|\"[^\"]*\"|'[^']*'|[^,}}]*)", "", line, count=1)


def migrate(building: Path = None, layout: Path = None, state_path: Path = None) -> dict:
    """Move cells_fixed (hub_layout.yaml) and start, depth, processes, fixtures (building.yaml) into the state and remove
    them from the YAML files; comments and all other fields stay. Aborts if the state already has values."""
    building, layout, state_path = building or BUILDING, layout or HUB_LAYOUT, state_path or STATE
    state = load_state(state_path, allow_missing=True)
    if state["modules"] or state["rooms"]:
        raise ValueError(f"{state_path.name} hat schon Werte; Umzug nur einmal")
    station = read_yaml(building)["station"]
    for m in station.get("modules", []):
        entry = {k: copy.deepcopy(m[k]) for k in ("start", "depth", "processes", "fixtures") if k in m}
        if entry:
            state["modules"][m["id"]] = entry
    for room in (station.get("museum") or {}).get("rooms", []):
        if room.get("fixtures"):
            state["rooms"][room["id"]] = {"fixtures": copy.deepcopy(room["fixtures"])}
    for m in (read_yaml(layout) or {}).get("modules", []):
        if "cells_fixed" in m:
            state["modules"].setdefault(m["id"], {})["cells"] = [list(c) for c in m["cells_fixed"]]
    # building.yaml: remove the fields from the flow-style module lines (there were no fixtures there at migration time)
    lines = building.read_text(encoding="utf-8").split("\n")
    if any(re.search(r", fixtures: \[\s*(#.*)?$", line) for line in lines):
        raise ValueError("building.yaml enthält mehrzeilige fixtures; erst von Hand prüfen")
    ids = {m["id"] for m in station.get("modules", [])}
    for i, line in enumerate(lines):
        hit = re.match(r"^\s*- \{id: ([\w\-]+),", line)
        if hit and hit.group(1) in ids:
            for key in ("start", "depth", "processes"):
                line = _remove_flow_field(line, key)
            lines[i] = line
    # hub_layout.yaml: remove the cells_fixed block of each entry
    out, skipping = [], False
    for line in layout.read_text(encoding="utf-8").split("\n"):
        if re.match(r"^  cells_fixed:\s*$", line):
            skipping = True
            continue
        if skipping and re.match(r"^  - \[", line):
            continue
        skipping = False
        out.append(line)
    save_state(state, state_path)
    # Read back: the combined result must match the old values exactly before the YAML files are written
    new_station = apply_station(yaml_load("\n".join(lines))["station"], state)
    new_layout = apply_layout(yaml_load("\n".join(out)), state)
    old_layout = read_yaml(layout)
    for old, new in zip(station.get("modules", []), new_station.get("modules", [])):
        for key in ("start", "depth", "processes", "fixtures"):
            assert old.get(key) == new.get(key), f"Umzug {old['id']}.{key} stimmt nicht"
    for old, new in zip(old_layout.get("modules", []), new_layout.get("modules", [])):
        assert old.get("cells_fixed") == new.get("cells_fixed"), f"Umzug {old['id']}.cells_fixed stimmt nicht"
    building.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    layout.write_text("\n".join(out), encoding="utf-8", newline="\n")
    return state


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--migrate" in sys.argv:
        moved = migrate()
        print(f"umgezogen nach {STATE.name}: {len(moved['modules'])} Module, {len(moved['rooms'])} Räume")
    state = load_state()
    print(f"{STATE.name}: {len(state['modules'])} Module, davon {sum(1 for m in state['modules'].values() if m.get('cells'))} "
          f"mit Lage, {sum(len(m.get('fixtures', [])) for m in state['modules'].values())} Elemente in Modulen, "
          f"{sum(len(r.get('fixtures', [])) for r in state['rooms'].values())} in Museumsräumen")
