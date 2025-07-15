#!/usr/bin/env python3
import yaml
import os
import subprocess
import json
import time
from pathlib import Path
from collections import OrderedDict
import jsonref
import synapseclient

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def run_capture(cmd, **kw):
    print("⟳", " ".join(str(c) for c in cmd))
    try:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True, **kw)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {e}")
        return None


def remove_keys(obj, keys_to_remove):
    """
    Recursively remove any dict entries whose key is in keys_to_remove.
    """
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if k in keys_to_remove:
                obj.pop(k)
            else:
                remove_keys(obj[k], keys_to_remove)
    elif isinstance(obj, list):
        for item in obj:
            remove_keys(item, keys_to_remove)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
SCHEMA_YAML = Path("dist/NF.yaml")
HEADER_YAML = Path("header.yaml")
BUILD_DIR   = Path("modules/Template")
OUT_DIR     = Path("registered-json-schemas")

BUILD_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── LOAD MASTER SCHEMA ───────────────────────────────────────────────────────
master      = yaml.safe_load(SCHEMA_YAML.read_text(encoding="utf-8"))
all_classes = master.get("classes", {})
all_slots   = master.get("slots", {})
all_enums   = master.get("enums", {})

# ─── UTILITIES ────────────────────────────────────────────────────────────────
def collect_hierarchy(cls_name):
    hierarchy = []
    cur = cls_name
    while cur:
        cdef = all_classes.get(cur)
        if not cdef:
            print(f"⚠️ Warning: class '{cur}' not found; skipping")
            break
        hierarchy.append((cur, cdef))
        cur = cdef.get("is_a")
    return hierarchy


def slot_enums(sdef):
    enums = set()
    if "range" in sdef:
        enums.add(sdef["range"])
    if "any_of" in sdef:
        enums.update(alt["range"] for alt in sdef["any_of"] if "range" in alt)
    return enums

# ─── STEP 1: GENERATE CLASS-SPECIFIC YAML ─────────────────────────────────────
for cls_name in all_classes:
    print(f"\n🔨 Generating YAML for class: {cls_name}")
    hierarchy   = collect_hierarchy(cls_name)
    used_slots  = {}
    used_enums  = set()
    for _, cdef in hierarchy:
        for slot in (cdef.get("slots") or []):
            sdef = all_slots.get(slot)
            if sdef:
                used_slots[slot] = sdef
                used_enums |= slot_enums(sdef)
    collected_enums = {nm: all_enums[nm] for nm in used_enums if nm in all_enums}

    header = yaml.safe_load(HEADER_YAML.read_text())
    header.pop("classes", None)

    yaml_content = {
        **header,
        "name": cls_name,
        "classes": {
            nm: {
                "description": cdef.get("description"),
                **({"is_a": cdef["is_a"]} if "is_a" in cdef else {}),
                "slots": cdef.get("slots") or []
            }
            for nm, cdef in hierarchy
        },
        "slots": used_slots,
        "enums": collected_enums
    }

    out_file = BUILD_DIR / f"{cls_name}.yaml"
    out_file.write_text(yaml.safe_dump(yaml_content, sort_keys=False))
    print(f"  • Wrote {out_file}")

# ─── STEP 2 + 3: JSON SCHEMA GENERATION + DEREFERENCE ────────────────────────
for tpl in BUILD_DIR.glob("*.yaml"):
    cls = tpl.stem
    print(f"\n🔨 Generating JSON Schema for {cls}")
    schema_str = run_capture([
        "gen-json-schema",
        "--top-class", cls,
        "--inline", "--no-metadata",
        "--title-from=title",
        "--closed", str(tpl)
    ])
    if not schema_str:
        print(f"⚠️  Skipping {cls}")
        continue

    try:
        raw = json.loads(schema_str)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON for {cls}: {e}")
        continue

    # set ID + title
    raw["$id"]   = (
        f"https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/"
        f"sagedm-{cls.lower()}"
    )
    raw["title"] = cls

    # --- dereference, but leave $refs intact so we can inline enums ourselves
    deref = jsonref.replace_refs(raw, merge_props=False, proxies=False)
    full  = deref

    # pull out all enum definitions
    defs  = full.pop("$defs", {})
    props = full.setdefault("properties", {})

    # walk every property; when we hit a $ref to an enum, inline only its enum list + title
    def resolve(obj):
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref       = obj.pop("$ref")
                enum_name = ref.rsplit("/", 1)[-1]
                enumdef   = defs.get(enum_name)
                if enumdef and "enum" in enumdef:
                    # merge only the enum values
                    obj["enum"] = enumdef["enum"]
                    # bring over human-friendly title if you set one
                    if "title" in enumdef:
                        obj["title"] = enumdef["title"]
                return
            for v in obj.values():
                resolve(v)
        elif isinstance(obj, list):
            for item in obj:
                resolve(item)

    resolve(props)

    # now normalize, order, and write out as before
    def normalize(o):
        if isinstance(o, dict):
            t = o.get("type")
            if isinstance(t, list) and set(t) == {"string","null"}:
                o["type"] = "string"
            for v in o.values():
                normalize(v)
        elif isinstance(o, list):
            for i in o:
                normalize(i)

    normalize(full)

    ordered = OrderedDict()
    for k in ["$id","$schema","title","type","description","properties","required"]:
        if k in full:
            ordered[k] = full[k]
    for k,v in full.items():
        if k not in ordered:
            ordered[k] = v

    remove_keys(ordered, {"additionalProperties","metamodel_version","version"})

    out_json = OUT_DIR / f"{cls}-deref.json"
    out_json.write_text(json.dumps(ordered, indent=2))
    print(f"  ✅ wrote {out_json}")


# ─── STEP 4: VALIDATE AGAINST SYNAPSE (dryRun) ───────────────────────────────
print("\n🔨 Validating all dereferenced schemas…")
syn = synapseclient.Synapse()
syn.login()

def validate_schema(path: Path):
    print(f"\n🔍 Validating: {path.name}")
    data = json.loads(path.read_text())
    remove_keys(data, {"additionalProperties","metamodel_version","version"})
    body = json.dumps({"schema": data, "dryRun": True})
    try:
        resp  = syn.restPOST("/schema/type/create/async/start", body)
        token = resp["token"]
        status= syn.restGET(f"/asynchronous/job/{token}")
        while status["jobState"] == "PROCESSING":
            time.sleep(1)
            status = syn.restGET(f"/asynchronous/job/{token}")
        if status["jobState"] == "FAILED":
            print(f"❌ {path.name} FAILED: {status.get('errorMessage')}")
        else:
            print(f"✅ {path.name} OK")
    except Exception as e:
        print(f"❌ Exception validating {path.name}: {e}")

for f in OUT_DIR.glob("*-deref.json"):
    validate_schema(f)

print("\n🎉 All done!")
