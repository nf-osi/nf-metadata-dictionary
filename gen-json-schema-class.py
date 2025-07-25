#!/usr/bin/env python3

import subprocess
import json
from pathlib import Path
import jsonref

# Config
SCHEMA_YAML = Path("dist/NF.yaml")
OUT_DIR = Path("registered-json-schemas")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def run_cmd(cmd):
    """Run command and return output."""
    try:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True)
        return result.stdout
    except subprocess.CalledProcessError:
        return None

def process_schema(raw_schema, cls_name):
    """Process and clean the JSON schema."""
    # Set metadata
    raw_schema["$id"] = f"https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-{cls_name.lower()}"
    raw_schema["title"] = cls_name
    
    # Dereference and inline enums
    deref = jsonref.replace_refs(raw_schema, merge_props=False, proxies=False)
    defs = deref.pop("$defs", {})
    
    def inline_enums(obj):
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref = obj.pop("$ref")
                enum_name = ref.rsplit("/", 1)[-1]
                enum_def = defs.get(enum_name, {})
                if "enum" in enum_def:
                    obj["enum"] = enum_def["enum"]
                    if "title" in enum_def:
                        obj["title"] = enum_def["title"]
                return
            for value in obj.values():
                inline_enums(value)
        elif isinstance(obj, list):
            for item in obj:
                inline_enums(item)
    
    inline_enums(deref.get("properties", {}))
    
    # Remove unwanted metadata
    for key in ["additionalProperties", "metamodel_version", "version"]:
        deref.pop(key, None)
    
    return deref

def main():
    import yaml
    
    # Get class names
    master = yaml.safe_load(SCHEMA_YAML.read_text())
    classes = master.get("classes", {})
    
    print(f"🔨 Generating JSON schemas for {len(classes)} classes...")
    
    for cls_name in classes:
        print(f"  🔨 {cls_name}")
        
        # Generate JSON schema
        schema_str = run_cmd([
            "gen-json-schema",
            "--top-class", cls_name,
            "--inline", "--no-metadata", "--closed",
            str(SCHEMA_YAML)
        ])
        
        if not schema_str:
            continue
        
        try:
            raw_schema = json.loads(schema_str)
            final_schema = process_schema(raw_schema, cls_name)
            
            # Write output
            output_file = OUT_DIR / f"{cls_name}.json"
            output_file.write_text(json.dumps(final_schema, indent=2))
            
        except json.JSONDecodeError:
            continue
    
    print(f"✅ Generated {len(list(OUT_DIR.glob('*.json')))} JSON schemas")

if __name__ == "__main__":
    main()
