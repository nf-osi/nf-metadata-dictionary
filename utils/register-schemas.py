#!/usr/bin/env python3

import json
import time
import os
import argparse
from pathlib import Path
import synapseclient

# synapseclient's default HTTP timeout (70s) is shorter than some schema
# registration calls take to complete server-side. When a request times out
# client-side, synapseclient's retry wrapper resends the (non-idempotent)
# POST, creating a duplicate async job. The original call often finishes
# successfully anyway, so the duplicate then fails with "already exists"
# even though registration actually succeeded. A longer timeout reduces how
# often this race is hit; parse_schema_org_name/version_already_registered
# below let us detect and recover from it when it still happens.
HTTP_TIMEOUT_SECONDS = 180


def parse_schema_org_name(schema_id: str):
    """Extract (organization, schema_name) from a versioned or unversioned $id."""
    base_id = schema_id.split("/")[-1] if "://" in schema_id else schema_id
    parts = base_id.rsplit("-", 1)
    if len(parts) == 2 and parts[1].replace(".", "").isdigit():
        base_id = parts[0]
    if "-" not in base_id:
        return None
    org, name = base_id.split("-", 1)
    return org, name


def version_already_registered(syn, org: str, name: str, version: str) -> bool:
    """Check Synapse directly for whether `version` is already registered for org/name."""
    try:
        resp = syn.restPOST(
            "/schema/version/list",
            body=json.dumps({"organizationName": org, "schemaName": name}),
        )
        page = resp.get("page", resp.get("results", []))
        return any(r.get("semanticVersion") == version for r in page)
    except Exception:
        return False


def register_schema(path: Path, syn: synapseclient.Synapse):
    """Register schema with Synapse API (actual registration)."""
    print(f"\n🚀 Registering: {path.name}")
    try:
        data = json.loads(path.read_text())
        body = json.dumps({"schema": data, "dryRun": False})  # Changed to False for actual registration

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
            error_message = status.get("errorMessage", "")
            if "already exists" in error_message:
                # Likely the client-timeout/retry race described above: the
                # original request succeeded server-side, and this job is a
                # duplicate that lost the race. Verify against the schema's
                # actual version list before declaring failure.
                parsed = parse_schema_org_name(data.get("$id", ""))
                version = data.get("$id", "").rsplit("-", 1)[-1]
                if parsed and version_already_registered(syn, parsed[0], parsed[1], version):
                    print(f"✅ {path.name} REGISTERED SUCCESSFULLY (confirmed after duplicate-submission conflict: {error_message})")
                    return True
            print(f"❌ {path.name} REGISTRATION FAILED: {error_message}")
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
    parser.add_argument("--exclude",
                       nargs="*",
                       default=[],
                       help="Schema files to exclude from registration (e.g., --exclude Superdataset.json)")
    parser.add_argument("--include",
                       nargs="*",
                       default=[],
                       help="Only register specific schema files (e.g., --include DataLandscape.json). Overrides --exclude.")

    args = parser.parse_args()

    # Set up paths
    SCHEMA_DIR = Path(args.schema_dir)

    if not SCHEMA_DIR.exists():
        print(f"❌ Schema directory not found: {SCHEMA_DIR}")
        exit(1)

    # Get existing schemas from directory
    if args.include:
        # If --include is specified, only register those schemas
        json_files = [SCHEMA_DIR / name for name in args.include if (SCHEMA_DIR / name).exists()]
        missing = [name for name in args.include if not (SCHEMA_DIR / name).exists()]
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
    print(f"🚀 Registering {schema_count} schema(s) with Synapse{filter_info}...")

    # Log in once and reuse the client for every schema, rather than
    # re-authenticating per file.
    auth_token = os.environ.get('SYNAPSE_AUTH_TOKEN')
    if not auth_token:
        print("❌ SYNAPSE_AUTH_TOKEN environment variable is required for registration. Set it with: export SYNAPSE_AUTH_TOKEN=<your_token>")
        exit(1)
    syn = synapseclient.Synapse(http_timeout_seconds=HTTP_TIMEOUT_SECONDS)
    syn.login(authToken=auth_token)

    registration_results = []
    detailed_results = []

    for json_file in json_files:
        result = register_schema(json_file, syn)
        registration_results.append(result)
        detailed_results.append((json_file.name, result))
    
    # Summary
    passed = sum(registration_results)
    failed = len(registration_results) - passed
    
    print(f"\n🎉 Registration complete: {passed} registered successfully, {failed} failed")
    
    # Log registration results to markdown file
    filter_lines = []
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