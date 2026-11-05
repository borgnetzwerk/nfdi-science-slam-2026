"""Check that a cleaned-up copy of a script or data file changes only comments and documentation.

Usage:
    python tools/verify_cleanup.py <original folder> <cleaned folder>

Python: the syntax tree without docstrings must be identical (code, names and every other string literal unchanged).
YAML and JSON: the parsed data must be identical, except values under keys listed in NOTE_KEYS (free-text notes),
which may be shortened or translated. Prints one line per file and exits with 1 if any file differs.
"""
import ast
import json
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")
# free-text keys that only describe things for people; the scene code never reads them for geometry or materials
# (max_speed_reason is only copied into the motion check report)
NOTE_KEYS = {"note", "notes", "comment", "source", "section_source", "title_history", "reason", "why", "todo", "decision", "answer",
             "quote", "beleg", "anlass", "shows", "speech", "missing", "max_speed_reason", "role", "purpose", "story", "verdict",
             "feasibility", "variants_superseded", "game", "stage", "comparison", "terms", "place", "feeling", "overlay", "reference"}
# keys that are notes only in one file (in the storyboard, "via" holds camera waypoints and must not change)
NOTE_KEYS_PER_FILE = {"station_plan.json": {"via", "by", "when"}, "building.yaml": {"label"}}


def strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


def without_notes(data, keys=NOTE_KEYS):
    if isinstance(data, dict):
        return {k: without_notes(v, keys) for k, v in data.items() if k not in keys}
    if isinstance(data, list):
        return [without_notes(v, keys) for v in data]
    return data


def first_difference(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: type {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                return f"{path}.{k}: only in {'original' if k in a else 'cleaned'}"
            d = first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {str(a)[:60]!r} vs {str(b)[:60]!r}"


def load(path, rename=False):
    text = path.read_text(encoding="utf-8")
    text = renamed(text) if rename else text
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


RENAMES = yaml.safe_load((Path(__file__).parent / "_work" / "public_renames.yaml").read_text(encoding="utf-8"))["renames"]


def renamed(text):
    """The original with the published object renames applied (see public_renames.yaml)."""
    for r in RENAMES:
        text = text.replace(r["old"], r["new"])
    return text


def main():
    original, cleaned = Path(sys.argv[1]), Path(sys.argv[2])
    failed = False
    for new in sorted(cleaned.iterdir()):
        old = original / new.name
        if not old.exists() or new.suffix not in (".py", ".yaml", ".json"):
            continue
        if new.suffix == ".py":
            same = strip_docstrings(ast.parse(renamed(old.read_text(encoding="utf-8")))) == strip_docstrings(ast.parse(new.read_text(encoding="utf-8")))
            detail = "" if same else "code differs (beyond comments and docstrings)"
        else:
            keys = NOTE_KEYS | NOTE_KEYS_PER_FILE.get(new.name, set())
            detail = first_difference(without_notes(load(old, rename=True), keys), without_notes(load(new), keys)) or ""
            same = not detail
        failed |= not same
        print(f"{'ok  ' if same else 'DIFF'} {new.name} {detail}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
