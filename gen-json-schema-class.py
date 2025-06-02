#!/usr/bin/env python3
import yaml
import os
from pathlib import Path
import subprocess
import json
from collections import OrderedDict
import jsonref

# ─── HELPER FUNCTIONS ───────────────────────────────────────────────────────────────────

def run(cmd, **kw):
    print("⟳", " ".join(str(c) for c in cmd))
    try:
        subprocess.run(cmd, check=True, **kw)
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {e}")
        return False
    return True


# ─── CONFIG ───────────────────────────────────────────────────────────────────
SCHEMA_YAML = Path("dist/NF.yaml")
HEADER_YAML = Path("header.yaml")
BUILD_DIR = Path("modules/Template")
BUILD_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR = Path("registered-json-schemas")

# ─── LOAD MASTER SCHEMA ───────────────────────────────────────────────────────

master = yaml.safe_load(SCHEMA_YAML.read_text(encoding="utf-8"))
all_classes = master.get("classes", {})
all_slots = master.get("slots", {})
all_enums = master.get("enums", {})

# ─── UTILS ────────────────────────────────────────────────────────────────────

def collect_hierarchy(cls_name):
    """Collect class and its ancestors in order from child to topmost parent"""
    hierarchy = []
    cur = cls_name
    while cur:
        cdef = all_classes.get(cur)
        if not cdef:
            print(f"⚠️  Warning: class '{cur}' not found in master schema. Skipping.")
            break  # Do NOT append None
        hierarchy.append((cur, cdef))
        cur = cdef.get("is_a")
    return hierarchy

def slot_enums(slot_def):
    """Find enum ranges in a slot definition"""
    enums = set()
    if "range" in slot_def:
        enums.add(slot_def["range"])
    if "any_of" in slot_def:
        enums.update(alt["range"] for alt in slot_def["any_of"] if "range" in alt)
    return enums

# ─── STEP: GENERATE INDIVIDUAL CLASS YAML FILES ──────────────────────────────

for cls_name in all_classes:
    print(f"\n🔨 Generating YAML for class: {cls_name}")
    
    # 1. Get class + ancestors
    hierarchy = collect_hierarchy(cls_name)

    # 2. Get relevant slots and their enums
    used_slots = {}
    used_enums = set()

    for _, cdef in hierarchy:
        if not cdef:
            continue  # Defensive check in case of missing class
        slots = cdef.get("slots") or []  # Ensure it's always iterable
        for slot in slots:
            sdef = all_slots.get(slot)
            if sdef:
                used_slots[slot] = sdef
                used_enums |= slot_enums(sdef)

    # 3. Collect enums used
    collected_enums = {
        name: all_enums[name]
        for name in used_enums
        if name in all_enums
    }

    # 4. Construct new YAML
    header = yaml.safe_load(HEADER_YAML.read_text())
    header.pop("classes", None)  # Prevent unwanted injection

    yaml_content = {
        **header,
        "name": cls_name,
        "classes": {
            name: {
                "description": cdef.get("description"),
                **({"is_a": cdef["is_a"]} if "is_a" in cdef else {}),
                "slots": cdef.get("slots") or []  # Always output a list
            }
            for name, cdef in hierarchy if cdef  # Skip any None values
        },
        "slots": used_slots,
        "enums": collected_enums
    }

    out_file = BUILD_DIR / f"{cls_name}.yaml"
    out_file.write_text(yaml.safe_dump(yaml_content, sort_keys=False))
    print(f"  • Included classes: {[name for name, _ in hierarchy if _]}")
    print(f"  • Wrote: {out_file}")

# ─── STEP 2: generate JSON schemas ────────────────────────────────────────────
for tpl in BUILD_DIR.glob("*.yaml"):
    cls = tpl.stem
    print(f"\n🔨 Generating JSON Schema for {cls}")

    out_file = OUT_DIR / f"{cls}.json"
    success = run([
        "gen-json-schema",
        "--top-class", cls,
        "--inline",
        "--no-metadata",
        "--title-from=title",
        "--closed",
        str(tpl)
    ], stdout=out_file.open("w"))

    if not success:
        print(f"⚠️ Skipping {cls} due to schema generation error.")
        continue

    schema = json.loads(out_file.read_text())
    schema["$id"] = (
        "https://repo-prod.prod.sagebase.org/repo/v1/schema/"
        f"type/registered/org.synapse.nf-{cls.lower()}"
    )
    schema["title"] = cls

    out_file.write_text(json.dumps(schema, indent=2))
    print("  ✅ wrote", out_file)

# ─── STEP 3: dereference and reorder keys ────────────────────────────────────
print("\n🔨 Dereferencing all JSON schemas...")
for json_file in OUT_DIR.glob("*.json"):
    if json_file.stem.endswith("-deref"):
        continue

    if json_file.stat().st_size == 0:
        print(f"⚠️ Skipping empty file: {json_file.name}")
        continue

    deref_file = OUT_DIR / f"{json_file.stem}-deref.json"
    print(f"🔨 Dereferencing {json_file.name}")

    try:
        with json_file.open() as src:
            raw = json.load(src)
    except json.JSONDecodeError as e:
        print(f"❌ Skipping {json_file.name}: invalid JSON — {e}")
        continue

    # replace refs
    deref_schema = jsonref.JsonRef.replace_refs(raw)
    schema_str = jsonref.dumps(deref_schema)
    schema = json.loads(schema_str)

    defs = schema.pop("$defs", {})
    props = schema.setdefault("properties", {})

    for name, definition in defs.items():
        if definition.get("enum"):
            props[name] = definition

    def resolve_refs(obj):
        if isinstance(obj, dict):
            if '$ref' in obj:
                ref = obj.pop('$ref')
                name = ref.split('/')[-1]
                enum_def = defs.get(name)
                if enum_def:
                    obj.clear()
                    obj.update(enum_def)
                return
            for v in obj.values():
                resolve_refs(v)
        elif isinstance(obj, list):
            for item in obj:
                resolve_refs(item)
    resolve_refs(props)

    def normalize_types(obj):
        if isinstance(obj, dict):
            if 'type' in obj and isinstance(obj['type'], list):
                types = obj['type']
                if 'string' in types and 'null' in types and len(types) == 2:
                    obj['type'] = 'string'
            for v in obj.values():
                normalize_types(v)
        elif isinstance(obj, list):
            for item in obj:
                normalize_types(item)
    normalize_types(schema)

    ordered = OrderedDict()
    for key in ["$id", "$schema", "title", "type", "description", "properties", "required"]:
        if key in schema:
            ordered[key] = schema[key]
    for k, v in schema.items():
        if k not in ordered:
            ordered[k] = v

    with deref_file.open("w") as dst:
        json.dump(ordered, dst, indent=2)
    print("  ✅ wrote", deref_file)

print("🎉 All done!")