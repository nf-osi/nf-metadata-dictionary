#!/usr/bin/env python3

import subprocess
import yaml
import json
import time
import os
import argparse
from pathlib import Path
import jsonref
import synapseclient
from collections import OrderedDict

def run_cmd(cmd):
    """Run command and return output."""
    try:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True)
        return result.stdout
    except subprocess.CalledProcessError:
        return None

def get_class_property_order(schema_yaml_path, cls_name):
    """Get the property order from the original YAML schema."""
    try:
        # Use a custom YAML loader that preserves order
        from yaml import load
        try:
            from yaml import CLoader as Loader
        except ImportError:
            from yaml import Loader

        with open(schema_yaml_path, 'r') as f:
            # Load YAML while preserving key order
            schema_data = load(f, Loader=Loader)

        cls_def = schema_data.get('classes', {}).get(cls_name, {})

        # Check if properties are defined in 'attributes' (PortalDataset style)
        if 'attributes' in cls_def:
            return list(cls_def['attributes'].keys())
        # Otherwise check for 'slots' (Template style)
        elif 'slots' in cls_def:
            return cls_def['slots']

        return []
    except Exception as e:
        print(f"Warning: Could not determine property order for {cls_name}: {e}")
        return []

def reorder_properties(properties, property_order):
    """Reorder properties dict based on specified order."""
    if not property_order or not properties:
        return properties

    ordered = OrderedDict()

    # First add properties in the specified order
    for prop in property_order:
        if prop in properties:
            ordered[prop] = properties[prop]

    # Then add any remaining properties not in the order list (alphabetically)
    for prop in sorted(properties.keys()):
        if prop not in ordered:
            ordered[prop] = properties[prop]

    return dict(ordered)

def process_schema(raw_schema, cls_name, version=None, schema_yaml_path=None):
    """Process and clean the JSON schema."""
    # Set metadata with optional version
    if version:
        raw_schema["$id"] = f"https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-{cls_name.lower()}-{version}"
    else:
        raw_schema["$id"] = f"https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-{cls_name.lower()}"
    raw_schema["title"] = cls_name

    # Force JSON Schema Draft 7
    raw_schema["$schema"] = "http://json-schema.org/draft-07/schema#"

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

    # Combine anyOf enums into single enum for efficiency
    def combine_anyof_enums(obj):
        if isinstance(obj, dict):
            # Check if this is an anyOf with multiple enum options
            if "anyOf" in obj and isinstance(obj["anyOf"], list):
                # Check if all items in anyOf are enums
                all_enums = all(
                    isinstance(item, dict) and "enum" in item
                    for item in obj["anyOf"]
                )

                if all_enums:
                    # Save anyOf items before deleting
                    anyof_items = obj["anyOf"]

                    # Combine all enum values into a single list
                    combined_enums = []
                    for item in anyof_items:
                        combined_enums.extend(item["enum"])

                    # Replace anyOf with single enum
                    obj["enum"] = combined_enums
                    del obj["anyOf"]

                    # Keep the description if not already present
                    if "description" not in obj and any("description" in item for item in anyof_items):
                        # Use first non-empty description
                        for item in anyof_items:
                            if "description" in item and item["description"]:
                                obj["description"] = item["description"]
                                break

            # Recurse into nested objects
            for value in obj.values():
                combine_anyof_enums(value)
        elif isinstance(obj, list):
            for item in obj:
                combine_anyof_enums(item)

    combine_anyof_enums(deref.get("properties", {}))

    # Set title to match property key name
    if "properties" in deref:
        for prop_name, prop_schema in deref["properties"].items():
            if isinstance(prop_schema, dict):
                prop_schema["title"] = prop_name

    # Remove unwanted metadata
    for key in ["additionalProperties", "metamodel_version", "version"]:
        deref.pop(key, None)

    # Remove Filename and Component properties (issue #708)
    if "properties" in deref:
        for field in ["Filename", "Component"]:
            deref["properties"].pop(field, None)

    # Also remove from required array if present
    if "required" in deref:
        deref["required"] = [r for r in deref["required"] if r not in ["Filename", "Component"]]

    # Reorder properties to match YAML order
    if schema_yaml_path and "properties" in deref:
        property_order = get_class_property_order(schema_yaml_path, cls_name)
        deref["properties"] = reorder_properties(deref["properties"], property_order)

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
    parser = argparse.ArgumentParser(description="Generate and validate JSON schemas from LinkML")
    parser.add_argument("--schema-yaml",
                       default="dist/NF.yaml",
                       help="Path to LinkML YAML schema file (default: dist/NF.yaml)")
    parser.add_argument("--output-dir",
                       default="registered-json-schemas",
                       help="Output directory for JSON schemas (default: registered-json-schemas)")
    parser.add_argument("--log-file",
                       default="schema-validation-log.md",
                       help="Path to validation log file (default: schema-validation-log.md)")
    parser.add_argument("--version",
                       default=None,
                       help="Semantic version to include in schema URIs (e.g., 9.9.0)")
    parser.add_argument("--skip-validation",
                       action="store_true",
                       help="Skip validation step and only generate JSON schemas")

    args = parser.parse_args()
    
    # Set up paths
    SCHEMA_YAML = Path(args.schema_yaml)
    OUT_DIR = Path(args.output_dir)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    if not SCHEMA_YAML.exists():
        print(f"❌ Schema file not found: {SCHEMA_YAML}")
        exit(1)
    
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
            final_schema = process_schema(raw_schema, cls_name, args.version, SCHEMA_YAML)

            # Write output
            output_file = OUT_DIR / f"{cls_name}.json"
            output_file.write_text(json.dumps(final_schema, indent=2))
            
        except json.JSONDecodeError:
            continue
    
    generated_count = len(list(OUT_DIR.glob('*.json')))
    print(f"✅ Generated {generated_count} JSON schemas")

    if args.skip_validation:
        print("\n⏭️  Skipping validation (--skip-validation flag set)")
        return

    print(f"\n🔨 Validating {generated_count} schemas against Synapse...")
    validation_results = []

    for json_file in OUT_DIR.glob('*.json'):
        result = validate_schema(json_file)
        validation_results.append(result)

    # Summary
    passed = sum(validation_results)
    failed = len(validation_results) - passed

    print(f"\n🎉 Validation complete: {passed} passed, {failed} failed")

    # Log validation results to markdown file
    log_content = f"""# Schema Validation Report

Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

## Summary
- **Generated schemas:** {generated_count}
- **Validation passed:** {passed}
- **Validation failed:** {failed}

## Details
"""

    # Add details for each schema
    for json_file in OUT_DIR.glob('*.json'):
        status = "✅ PASSED" if json_file in [f for f, r in zip(OUT_DIR.glob('*.json'), validation_results) if r] else "❌ FAILED"
        log_content += f"- `{json_file.name}`: {status}\n"

    # Write log file
    log_file = Path(args.log_file)
    log_file.write_text(log_content)
    print(f"\n📝 Validation report written to {log_file}")

    # Exit with error code if any validations failed
    if failed > 0:
        print(f"\n❌ {failed} schema(s) failed validation. Please fix and try again.")
        exit(1)
    else:
        print(f"\n✅ All {passed} schemas passed validation!")

if __name__ == "__main__":
    main()
