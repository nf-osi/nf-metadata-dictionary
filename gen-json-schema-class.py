#!/usr/bin/env python3
import yaml
import subprocess
import os
from pathlib import Path
from collections import deque, OrderedDict
# Add JSON and jsonref for dereferencing
import json
import jsonref

NPX = "npx.cmd" if os.name == "nt" else "npx"

# ─── CONFIG ───────────────────────────────────────────────────────────────────
SCHEMA_YAML   = Path("dist/NF.yaml")
BUILD_DIR     = Path("build/templates")
OUT_DIR       = Path("registered-json-schemas")
HEADER_YAML   = Path("header.yaml")

# common “global” enums you always want to include:
COMMON_ENUM_MODULES = [
    Path("modules/Data/Data.yaml"),
    Path("modules/Assay/Assay.yaml"),
    Path("modules/Sample/Species.yaml"),
]
# where DCC‑specific enums live:
DCC_ENUM_DIR   = Path("modules/DCC")

BUILD_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def run(cmd, **kw):
    print("⟳", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)

# load the master LinkML
master = yaml.safe_load(SCHEMA_YAML.read_text(encoding="utf-8"))
all_classes = master.get("classes", {})
all_slots   = master.get("slots", {})
all_enums   = master.get("enums", {})

# walk inheritance to collect class + ancestors
def collect_hierarchy(cls_name):
    hierarchy = []
    cur = cls_name
    while cur:
        cdef = all_classes[cur]
        hierarchy.append((cur, cdef))
        parent = cdef.get("is_a")
        if not parent or parent not in all_classes:
            break
        cur = parent
    return hierarchy

# find enums referenced by a slot definition
def slot_enums(slot_def):
    out = set()
    if "range" in slot_def:
        out.add(slot_def["range"])
    if "any_of" in slot_def:
        for alt in slot_def["any_of"]:
            if "range" in alt:
                out.add(alt["range"])
    return out

# ─── STEP 1: generate per‑class YAMLs ─────────────────────────────────────────

for cls_name, cls_def in all_classes.items():
    print(f"\n🔨 Building template YAML for {cls_name}")
    hierarchy = collect_hierarchy(cls_name)

    # collect all slot defs & enum names
    collected_slots = {}
    needed_enums    = set()
    for _, cdef in hierarchy:
        for slot in (cdef.get("slots") or []):
            sdef = all_slots.get(slot)
            if sdef:
                collected_slots[slot] = sdef
                needed_enums |= slot_enums(sdef)

    # pull full enum definitions from master + any DCC file
    collected_enums = { name: all_enums[name] for name in needed_enums if name in all_enums }
    dcc_yaml = DCC_ENUM_DIR / f"{cls_name}.yaml"
    enum_sources = COMMON_ENUM_MODULES + ([dcc_yaml] if dcc_yaml.exists() else [])

    # write small YAML
    out_yaml = BUILD_DIR / f"{cls_name}.yaml"
    payload = {
        **yaml.safe_load(HEADER_YAML.read_text()),
        "slots": collected_slots,
        "enums":  collected_enums,
        "classes": {
            name: {
                **cdef,
                "description": cdef.get("description"),
                **({"is_a": cdef["is_a"]} if "is_a" in cdef else {}),
                "slots": cdef.get("slots", []),
            }
            for name, cdef in hierarchy
        }
    }
    out_yaml.write_text(yaml.safe_dump(payload, sort_keys=False))
    print("  • wrote", out_yaml)

# ─── STEP 2: generate JSON schemas ────────────────────────────────────────────
for tpl in BUILD_DIR.glob("*.yaml"):
    cls = tpl.stem
    print(f"\n🔨 Generating JSON Schema for {cls}")

    out_file = OUT_DIR / f"{cls}.json"
    run([
        "gen-json-schema",
        "--top-class", cls,
        "--inline",
        "--no-metadata",
        "--title-from=title",
        "--not-closed",
        str(tpl)
    ], stdout=out_file.open("w"))

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
    deref_file = OUT_DIR / f"{json_file.stem}-deref.json"
    print(f"🔨 Dereferencing {json_file.name}")

    # load each schema file
    with json_file.open() as src:
        raw = json.load(src)
        # replace refs
        deref_schema = jsonref.JsonRef.replace_refs(raw)
    # serialize via jsonref.dumps to materialize proxy objects
    schema_str = jsonref.dumps(deref_schema)
    # load into python dicts
    schema = json.loads(schema_str)

    # extract and remove defs
    defs = schema.pop("$defs", {})
    # ensure properties exists
    props = schema.setdefault("properties", {})
        # merge enums into properties
    props.update(defs)

    # Recursively replace any remaining $ref entries in properties
    def resolve_refs(obj):
        if isinstance(obj, dict):
            if '$ref' in obj:
                ref = obj.pop('$ref')
                # Expect format '#/$defs/EnumName'
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

        # Normalize nullable types: convert ["string","null"] to "string"
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

    # reorder keys
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