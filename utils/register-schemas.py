#!/usr/bin/env python3

import json
import time
import os
import argparse
from pathlib import Path
import synapseclient

def rewrite_id_for_preview(data: dict, build: str) -> dict:
    """Rewrite $id to use a distinct preview schema name with 0.0.<build> semver.

    Transforms e.g. 'org.synapse.nf-wgstemplate' →
    'org.synapse.nf-wgstemplatedev-0.0.<build>' in the $id URL.

    The 'dev' suffix is appended to the schema id (not added as a version of
    the production schema) so that preview registrations never become the
    latest version seen by production entities.
    The file on disk is not modified.
    """
    import copy
    data = copy.deepcopy(data)
    if "$id" in data:
        base_url, schema_name = data["$id"].rsplit("/", 1)
        data["$id"] = f"{base_url}/{schema_name}dev-0.0.{build}"
    return data


def register_schema(path: Path, preview_build: str | None = None):
    """Register schema with Synapse API (actual registration).

    Args:
        path: Path to the JSON schema file.
        preview_build: If set, rewrites $id to use 0.0.<preview_build> versioning
            before registration. The file on disk is not modified.
    """
    label = f"{path.name} (preview 0.0.{preview_build})" if preview_build else path.name
    print(f"\n🚀 Registering: {label}")
    try:
        data = json.loads(path.read_text())
        if preview_build:
            data = rewrite_id_for_preview(data, preview_build)
        body = json.dumps({"schema": data, "dryRun": False})
        
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
            print(f"❌ {label} REGISTRATION FAILED: {status.get('errorMessage')}")
            return False
        else:
            print(f"✅ {label} REGISTERED SUCCESSFULLY")
            if preview_build:
                registered_id = data["$id"].rsplit("/", 1)[-1]
                print(f"   Preview schema ID: {registered_id}")
            return True
            
    except Exception as e:
        print(f"❌ Exception registering {label}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Register JSON schemas with Synapse")
    parser.add_argument("--schema-dir",
                       default="registered-json-schemas",
                       help="Directory containing JSON schemas to register (default: registered-json-schemas)")
    parser.add_argument("--log-file",
                       default="schema-registration-log.md",
                       help="Path to registration log file (default: schema-registration-log.md)")
    parser.add_argument("--exclude",
                       nargs="*",
                       default=[],
                       help="Schema files to exclude from registration (e.g., --exclude Superdataset.json)")
    parser.add_argument("--include",
                       nargs="*",
                       default=[],
                       help="Only register specific schema files (e.g., --include DataLandscape.json). Overrides --exclude.")
    parser.add_argument("--preview",
                       action="store_true",
                       help="Register as preview schemas using 0.0.<build> versioning. Requires --build.")
    parser.add_argument("--build",
                       default=None,
                       help="Build identifier appended as 0.0.<build> to schema $id when --preview is set (e.g. github.run_number).")

    args = parser.parse_args()

    if args.preview and not args.build:
        args.build = time.strftime('%Y%m%d%H%M%S', time.gmtime())
        print(f"ℹ️  No --build given; using timestamp: {args.build}")

    # Set up paths
    SCHEMA_DIR = Path(args.schema_dir)

    if not SCHEMA_DIR.exists():
        print(f"❌ Schema directory not found: {SCHEMA_DIR}")
        exit(1)

    # Get existing schemas from directory
    if args.include:
        # Normalise: accept both "WGSTemplate" and "WGSTemplate.json"
        normalised = [n if n.endswith(".json") else f"{n}.json" for n in args.include]
        json_files = [SCHEMA_DIR / name for name in normalised if (SCHEMA_DIR / name).exists()]
        missing = [name for name in normalised if not (SCHEMA_DIR / name).exists()]
        if missing:
            print(f"⚠️  Warning: Specified schemas not found: {', '.join(missing)}")
    else:
        # Otherwise, register all except excluded ones
        json_files = [f for f in SCHEMA_DIR.glob('*.json') if f.name not in args.exclude]
    
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
    if args.preview:
        print(f"🚀 Registering {schema_count} PREVIEW schema(s) with Synapse (0.0.{args.build}){filter_info}...")
    else:
        print(f"🚀 Registering {schema_count} schema(s) with Synapse{filter_info}...")

    registration_results = []
    detailed_results = []

    for json_file in json_files:
        result = register_schema(json_file, preview_build=args.build if args.preview else None)
        registration_results.append(result)
        detailed_results.append((json_file.name, result))
    
    # Summary
    passed = sum(registration_results)
    failed = len(registration_results) - passed
    
    print(f"\n🎉 Registration complete: {passed} registered successfully, {failed} failed")
    
    # Log registration results to markdown file
    filter_lines = []
    if args.preview:
        filter_lines.append(f"- **Mode:** preview (0.0.{args.build})")
    if args.include:
        filter_lines.append(f"- **Included:** {', '.join(args.include)}")
    if args.exclude:
        filter_lines.append(f"- **Excluded:** {', '.join(args.exclude)}")
    filter_text = "\n".join(filter_lines)

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