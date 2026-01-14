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

def load_enum_metadata(schema_yaml_path, cls_name):
    """Load enum metadata (source, description, meaning) from the YAML schema and build property-to-enum mappings."""
    try:
        from yaml import load
        try:
            from yaml import CLoader as Loader
        except ImportError:
            from yaml import Loader

        with open(schema_yaml_path, 'r') as f:
            schema_data = load(f, Loader=Loader)

        # First, load all enum metadata
        enums_data = schema_data.get('enums', {})
        enum_metadata = {}

        for enum_name, enum_def in enums_data.items():
            permissible_values = enum_def.get('permissible_values', {})
            enum_values_metadata = {}

            for value, value_def in permissible_values.items():
                if isinstance(value_def, dict):
                    # Extract metadata fields
                    value_meta = {}
                    if 'source' in value_def:
                        value_meta['source'] = value_def['source']
                    if 'description' in value_def:
                        value_meta['description'] = value_def['description']
                    if 'meaning' in value_def:
                        value_meta['meaning'] = value_def['meaning']

                    if value_meta:  # Only add if there's metadata
                        enum_values_metadata[value] = value_meta

            if enum_values_metadata:
                enum_metadata[enum_name] = enum_values_metadata

        # Now build property-to-enum mapping for this class
        property_enum_map = {}
        classes_data = schema_data.get('classes', {})
        cls_def = classes_data.get(cls_name, {})

        # Collect all slots including inherited ones
        def collect_all_slots(class_name, visited=None):
            """Recursively collect all slots from this class and its parents."""
            if visited is None:
                visited = set()
            if class_name in visited:
                return []
            visited.add(class_name)

            cls = classes_data.get(class_name, {})
            all_slots = []

            # Get parent class slots first
            if 'is_a' in cls:
                parent_name = cls['is_a']
                all_slots.extend(collect_all_slots(parent_name, visited))

            # Get mixin slots
            for mixin in cls.get('mixins', []):
                all_slots.extend(collect_all_slots(mixin, visited))

            # Add this class's slots
            if 'slots' in cls and cls['slots'] is not None:
                all_slots.extend(cls['slots'])
            elif 'attributes' in cls and cls['attributes'] is not None:
                all_slots.extend(cls['attributes'].keys())

            return all_slots

        slots = collect_all_slots(cls_name)

        # For each slot, find its range (which enum it uses)
        slots_data = schema_data.get('slots', {})
        for slot_name in slots:
            slot_def = slots_data.get(slot_name, {})

            # Check for range (single enum)
            if 'range' in slot_def:
                range_name = slot_def['range']
                if range_name in enum_metadata:
                    property_enum_map[slot_name] = [range_name]

            # Check for any_of (multiple possible enums)
            elif 'any_of' in slot_def:
                ranges = []
                for option in slot_def['any_of']:
                    if isinstance(option, dict) and 'range' in option:
                        range_name = option['range']
                        if range_name in enum_metadata:
                            ranges.append(range_name)
                if ranges:
                    property_enum_map[slot_name] = ranges

        return enum_metadata, property_enum_map

    except Exception as e:
        print(f"Warning: Could not load enum metadata: {e}")
        import traceback
        traceback.print_exc()
        return {}, {}

def add_enum_metadata(schema, enum_metadata, property_enum_map):
    """Add x-enum-metadata to properties that have enum values."""
    if 'properties' not in schema:
        return schema

    for prop_name, prop_def in schema['properties'].items():
        if prop_name not in property_enum_map:
            continue

        # Get the enum ranges for this property
        enum_ranges = property_enum_map[prop_name]

        # Collect all enum values and their metadata from all applicable ranges
        combined_metadata = {}
        for enum_range in enum_ranges:
            if enum_range in enum_metadata:
                range_metadata = enum_metadata[enum_range]
                # Merge metadata for this range
                for value, value_meta in range_metadata.items():
                    combined_metadata[value] = value_meta

        if not combined_metadata:
            continue

        # Find where the enum is defined in the property
        # Could be directly in the property or nested in items (for arrays)
        def add_metadata_to_enum(obj):
            if isinstance(obj, dict):
                if 'enum' in obj:
                    # Found an enum - add metadata for its values
                    enum_values = obj['enum']
                    metadata = {}
                    for value in enum_values:
                        if value in combined_metadata:
                            metadata[value] = combined_metadata[value]

                    if metadata:
                        obj['x-enum-metadata'] = metadata
                    return True

                # Recurse into nested structures
                for key, value in obj.items():
                    if key != 'x-enum-metadata':  # Don't recurse into our own metadata
                        add_metadata_to_enum(value)
            elif isinstance(obj, list):
                for item in obj:
                    add_metadata_to_enum(item)

        add_metadata_to_enum(prop_def)

    return schema

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

    # Load enum metadata from YAML if available
    enum_metadata = {}
    property_enum_map = {}
    if schema_yaml_path:
        enum_metadata, property_enum_map = load_enum_metadata(schema_yaml_path, cls_name)

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

    # Add enum metadata as x-enum-metadata
    if enum_metadata and property_enum_map:
        deref = add_enum_metadata(deref, enum_metadata, property_enum_map)

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
    parser.add_argument("--class",
                       dest="class_name",
                       default=None,
                       help="Generate schema for a specific class only (e.g., DataLandscape)")

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

    # Filter to specific class if requested
    if args.class_name:
        if args.class_name not in classes:
            print(f"❌ Class '{args.class_name}' not found in schema")
            print(f"Available classes: {', '.join(sorted(classes.keys()))}")
            exit(1)
        classes = {args.class_name: classes[args.class_name]}
        print(f"🔨 Generating JSON schema for class: {args.class_name}")
    else:
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
    
    # Count only the schemas we generated in this run
    if args.class_name:
        generated_count = 1 if (OUT_DIR / f"{args.class_name}.json").exists() else 0
    else:
        generated_count = len(list(OUT_DIR.glob('*.json')))

    print(f"✅ Generated {generated_count} JSON schema{'s' if generated_count != 1 else ''}")

    if args.skip_validation:
        print("\n⏭️  Skipping validation (--skip-validation flag set)")
        return

    # Only validate the schemas we generated in this run
    if args.class_name:
        schemas_to_validate = [OUT_DIR / f"{args.class_name}.json"]
        print(f"\n🔨 Validating {args.class_name} schema against Synapse...")
    else:
        schemas_to_validate = list(OUT_DIR.glob('*.json'))
        print(f"\n🔨 Validating {len(schemas_to_validate)} schemas against Synapse...")

    validation_results = []

    for json_file in schemas_to_validate:
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

    # Add details for each validated schema
    for json_file, result in zip(schemas_to_validate, validation_results):
        status = "✅ PASSED" if result else "❌ FAILED"
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
