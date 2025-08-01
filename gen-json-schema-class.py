#!/usr/bin/env python3

import subprocess
import yaml
import json
import time
import os
from pathlib import Path
import jsonref
import synapseclient

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

def validate_schema(path: Path):
    """Validate schema against Synapse API (dry run)."""
    print(f"\n🔍 Validating: {path.name}")
    try:
        data = json.loads(path.read_text())
        body = json.dumps({"schema": data, "dryRun": True})
        
        # Initialize Synapse client with auth token
        syn = synapseclient.Synapse()
        auth_token = os.environ.get('SYNAPSE_AUTH_TOKEN')
        if not auth_token:
            raise ValueError("SYNAPSE_AUTH_TOKEN environment variable is required for validation")
        syn.login(authToken=auth_token)
        
        # Start validation job
        resp = syn.restPOST("/schema/type/create/async/start", body)
        token = resp["token"]
        
        # Poll for completion
        status = syn.restGET(f"/asynchronous/job/{token}")
        while status["jobState"] == "PROCESSING":
            time.sleep(1)
            status = syn.restGET(f"/asynchronous/job/{token}")
        
        # Check result
        if status["jobState"] == "FAILED":
            print(f"❌ {path.name} FAILED: {status.get('errorMessage')}")
            return False
        else:
            print(f"✅ {path.name} OK")
            return True
            
    except Exception as e:
        print(f"❌ Exception validating {path.name}: {e}")
        return False

def main():
    
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
            "--inline", "--no-metadata", "--not-closed",
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
    
    generated_count = len(list(OUT_DIR.glob('*.json')))
    print(f"✅ Generated {generated_count} JSON schemas")
    
    print(f"\n🔨 Validating {generated_count} schemas against Synapse...")
    validation_results = []
    
    for json_file in OUT_DIR.glob('*.json'):
        result = validate_schema(json_file)
        validation_results.append(result)
    
    # Summary
    passed = sum(validation_results)
    failed = len(validation_results) - passed
    
    print(f"\n🎉 Validation complete: {passed} passed, {failed} failed")

if __name__ == "__main__":
    main()
