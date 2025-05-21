#!/usr/bin/env python3
import yaml
import subprocess
import os
from pathlib import Path
from collections import deque
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
            # pull full slot definition
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
                # we only want name, description, is_a, slots
                "description": cdef.get("description"),
                **({"is_a": cdef["is_a"]} if "is_a" in cdef else {}),
                "slots": cdef.get("slots", []),
            }
            for name, cdef in hierarchy
        }
    }
    out_yaml.write_text(yaml.safe_dump(payload, sort_keys=False))
    print("  • wrote", out_yaml)

# ─── STEP 2: for each small YAML, generate the JSON schema ────────────────────

import json

for tpl in BUILD_DIR.glob("*.yaml"):
    cls = tpl.stem
    print(f"\n🔨 Generating JSON Schema for {cls}")

    out_file = OUT_DIR / f"{cls}.json"

    # 1) Generate JSON Schema for this class as the top‐level
    run([
        "gen-json-schema",
        "--top-class", cls,
        "--inline",
        "--no-metadata",
        "--title-from=title",
        "--not-closed",
        str(tpl)
    ], stdout=out_file.open("w"))

    # 2) Inject our custom $id
    schema = json.loads(out_file.read_text())
    schema["$id"] = (
        "https://repo-prod.prod.sagebase.org/repo/v1/schema/"
        f"type/registered/org.synapse.nf-{cls.lower()}"
    )

    # 3) Overwrite file with pretty‐printed JSON
    out_file.write_text(json.dumps(schema, indent=2))
    print("  ✅ wrote", out_file)

print("\n🎉 All done!")