#!/usr/bin/env python3

import json
import time
import os
import argparse
from pathlib import Path
import synapseclient

def register_schema(path: Path):
    """Register schema with Synapse API (actual registration)."""
    print(f"\n🚀 Registering: {path.name}")
    try:
        data = json.loads(path.read_text())
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
    parser.add_argument("--exclude",
                       nargs="*",
                       default=[],
                       help="Schema files to exclude from registration (e.g., --exclude Superdataset.json)")
    
    args = parser.parse_args()
    
    # Set up paths
    SCHEMA_DIR = Path(args.schema_dir)
    
    if not SCHEMA_DIR.exists():
        print(f"❌ Schema directory not found: {SCHEMA_DIR}")
        exit(1)
    
    # Get existing schemas from directory
    json_files = [f for f in SCHEMA_DIR.glob('*.json') if f.name not in args.exclude]
    
    if not json_files:
        print(f"❌ No JSON schemas found in {SCHEMA_DIR}")
        return
    
    schema_count = len(json_files)
    excluded_info = f" (excluding {', '.join(args.exclude)})" if args.exclude else ""
    print(f"🚀 Registering {schema_count} existing schemas with Synapse{excluded_info}...")
    
    registration_results = []
    detailed_results = []
    
    for json_file in json_files:
        result = register_schema(json_file)
        registration_results.append(result)
        detailed_results.append((json_file.name, result))
    
    # Summary
    passed = sum(registration_results)
    failed = len(registration_results) - passed
    
    print(f"\n🎉 Registration complete: {passed} registered successfully, {failed} failed")
    
    # Log registration results to markdown file
    log_content = f"""# Schema Registration Report

Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

## Summary
- **Schemas processed:** {schema_count}
- **Registration successful:** {passed}
- **Registration failed:** {failed}
{f"- **Excluded:** {', '.join(args.exclude)}" if args.exclude else ""}

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