#!/usr/bin/env python3

import json
import time
import os
import argparse
from pathlib import Path
import synapseclient

def register_schema(path: Path, version: str = None):
    """Register schema with Synapse API (actual registration).

    Args:
        path: Path to the schema file
        version: Optional version string to append to the schema $id
    """
    print(f"\n🚀 Registering: {path.name}")
    try:
        data = json.loads(path.read_text())

        # If version is provided, append it to the $id
        if version:
            if "$id" in data:
                original_id = data["$id"]
                data["$id"] = f"{original_id}-{version}"
                print(f"   Versioned: {original_id} → {data['$id']}")
            else:
                print(f"   ⚠️  Warning: No $id found in schema, skipping versioning")

        body = json.dumps({"schema": data, "dryRun": False})  # Changed to False for actual registration
        
        # Initialize Synapse client with auth token
        syn = synapseclient.Synapse()
        auth_token = os.environ.get('SYNAPSE_AUTH_TOKEN')
        if not auth_token:
            raise ValueError("SYNAPSE_AUTH_TOKEN environment variable is required for registration. Set it with: export SYNAPSE_AUTH_TOKEN=<your_token>")
        syn.login(authToken=auth_token)
        
        # Start registration job
        resp = syn.restPOST("/schema/type/create/async/start", body)
        token = resp["token"]
        
        # Poll for completion
        status = syn.restGET(f"/asynchronous/job/{token}")
        while status["jobState"] == "PROCESSING":
            time.sleep(1)
            status = syn.restGET(f"/asynchronous/job/{token}")
        
        # Check result
        if status["jobState"] == "FAILED":
            print(f"❌ {path.name} REGISTRATION FAILED: {status.get('errorMessage')}")
            return False
        else:
            print(f"✅ {path.name} REGISTERED SUCCESSFULLY")
            return True
            
    except Exception as e:
        print(f"❌ Exception registering {path.name}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Register JSON schemas with Synapse")
    parser.add_argument("--schema-dir",
                       default="registered-json-schemas",
                       help="Directory containing JSON schemas to register (default: registered-json-schemas)")
    parser.add_argument("--log-file",
                       default="schema-registration-log.md",
                       help="Path to registration log file (default: schema-registration-log.md)")
    parser.add_argument("--version",
                       default=None,
                       help="Version string to append to schema $id (e.g., 0.0.123 or 1.0.0). Used for preview/testing builds.")
    parser.add_argument("--exclude",
                       nargs="*",
                       default=[],
                       help="Schema files to exclude from registration (e.g., --exclude Superdataset)")
    parser.add_argument("--include",
                       nargs="*",
                       default=[],
                       help="Only register specific schema files (e.g., --include DataLandscape or DataLandscape.json). Overrides --exclude.")

    args = parser.parse_args()

    # Set up paths
    SCHEMA_DIR = Path(args.schema_dir)

    if not SCHEMA_DIR.exists():
        print(f"❌ Schema directory not found: {SCHEMA_DIR}")
        exit(1)

    # Get existing schemas from directory
    if args.include:
        # If --include is specified, only register those schemas
        # Automatically add .json extension if not present
        normalized_names = []
        for name in args.include:
            if not name.endswith('.json'):
                normalized_names.append(f"{name}.json")
            else:
                normalized_names.append(name)

        json_files = [SCHEMA_DIR / name for name in normalized_names if (SCHEMA_DIR / name).exists()]
        missing = [name for name in normalized_names if not (SCHEMA_DIR / name).exists()]
        if missing:
            print(f"⚠️  Warning: Specified schemas not found: {', '.join(missing)}")
    else:
        # Otherwise, register all except excluded ones
        # Automatically add .json extension to excluded names if not present
        normalized_exclude = []
        for name in args.exclude:
            if not name.endswith('.json'):
                normalized_exclude.append(f"{name}.json")
            else:
                normalized_exclude.append(name)
        json_files = [f for f in SCHEMA_DIR.glob('*.json') if f.name not in normalized_exclude]
    
    if not json_files:
        print(f"❌ No JSON schemas found in {SCHEMA_DIR}")
        return
    
    schema_count = len(json_files)
    if args.include:
        filter_info = f" (only: {', '.join(args.include)})"
    elif args.exclude:
        filter_info = f" (excluding: {', '.join(args.exclude)})"
    else:
        filter_info = ""

    version_info = f" with version {args.version}" if args.version else ""
    print(f"🚀 Registering {schema_count} schema(s) with Synapse{filter_info}{version_info}...")

    if args.version:
        if args.version.startswith("0.0."):
            print(f"⚠️  Preview/unstable version detected ({args.version}) - schemas are for testing only")
        else:
            print(f"📦 Stable version: {args.version}")

    registration_results = []
    detailed_results = []

    for json_file in json_files:
        result = register_schema(json_file, version=args.version)
        registration_results.append(result)
        detailed_results.append((json_file.name, result))
    
    # Summary
    passed = sum(registration_results)
    failed = len(registration_results) - passed
    
    print(f"\n🎉 Registration complete: {passed} registered successfully, {failed} failed")
    
    # Log registration results to markdown file
    filter_lines = []
    if args.version:
        version_type = "Preview/Unstable" if args.version.startswith("0.0.") else "Stable"
        filter_lines.append(f"- **Version:** {args.version} ({version_type})")
    if args.include:
        filter_lines.append(f"- **Included:** {', '.join(args.include)}")
    if args.exclude:
        filter_lines.append(f"- **Excluded:** {', '.join(args.exclude)}")
    filter_text = "\n".join(filter_lines) if filter_lines else ""

    log_content = f"""# Schema Registration Report

Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

## Summary
- **Schemas processed:** {schema_count}
- **Registration successful:** {passed}
- **Registration failed:** {failed}
{filter_text}

## Details
"""
    
    # Add details for each schema
    for schema_name, success in detailed_results:
        status = "✅ REGISTERED" if success else "❌ FAILED"
        log_content += f"- `{schema_name}`: {status}\n"
    
    # Write log file
    log_file = Path(args.log_file)
    log_file.write_text(log_content)
    print(f"\n📝 Registration report written to {log_file}")
    
    # Exit with error code if any registrations failed
    if failed > 0:
        exit(1)

if __name__ == "__main__":
    main()