#!/usr/bin/env python
import json
import jsonref
import sys
from pathlib import Path

if len(sys.argv) != 3:
    print("Usage: python deref.py <input-schema.json> <output-schema.json>")
    sys.exit(1)

src_path = Path(sys.argv[1])
dst_path = Path(sys.argv[2])

# Load and dereference
with src_path.open() as src:
    schema = jsonref.JsonRef.replace_refs(json.load(src))

# Write out the fully-inlined schema
with dst_path.open("w") as dst:
    json.dump(schema, dst, indent=2)

print(f"Dereferenced schema written to {dst_path}")
