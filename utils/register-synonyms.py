#!/usr/bin/env python3
"""Register or update a Synapse SynonymSet (search-management resource).

A SynonymSet feeds OpenSearch analyzers in Synapse. Unlike JSON schemas, a
SynonymSet is mutable: creation is a POST, but updating an existing set is a
PUT to /search/synonym/set/{id} that requires the current id + etag. This
script handles that round-trip for you:

  1. List existing sets in the org (public read).
  2. Match the set by name (or an explicit --synonym-set-id).
  3. PUT the new definition with the resolved id + etag (re-register), or
     POST a brand-new set when no match exists.

See dev/SYNAPSE_SEARCH.md for the canonical example and fixtures in
tests/search/.

Auth: set SYNAPSE_AUTH_TOKEN to a personal access token with the `modify`
scope. Example:

    export SYNAPSE_AUTH_TOKEN=<token>
    python utils/register-synonyms.py --file tests/search/synonym_set_nf_domain.json
"""

import json
import os
import argparse
from pathlib import Path

import synapseclient


def get_token() -> str:
    token = os.environ.get("SYNAPSE_AUTH_TOKEN")
    if not token:
        raise ValueError(
            "SYNAPSE_AUTH_TOKEN is required. Set it to a personal access token "
            "with the `modify` scope."
        )
    return token


def find_existing(syn, organization_name: str, name: str, synonym_set_id: str = None):
    """Return the existing SynonymSet matching id or (org, name), else None."""
    body = json.dumps({"organizationName": organization_name})
    resp = syn.restPOST("/search/synonym/set/list", body)
    results = resp.get("results", [])
    for s in results:
        if synonym_set_id is not None:
            if str(s.get("id")) == str(synonym_set_id):
                return s
        elif s.get("name") == name:
            return s
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Register or update a Synapse SynonymSet."
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Path to the SynonymSet JSON (e.g. tests/search/synonym_set_nf_domain.json)",
    )
    parser.add_argument(
        "--synonym-set-id",
        default=None,
        help="Explicit SynonymSet id to update (e.g. 16). If omitted, the set "
        "is matched by `name` within its organization.",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="Allow creating a new set (POST) when no existing match is found. "
        "Without this flag, a missing set is an error.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and print the request without writing to Synapse.",
    )
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"❌ File not found: {path}")
        raise SystemExit(1)

    data = json.loads(path.read_text())
    org = data.get("organizationName")
    name = data.get("name")
    if not org or not name:
        print("❌ File must include `organizationName` and `name`.")
        raise SystemExit(1)

    syn = synapseclient.Synapse()
    syn.login(authToken=get_token())

    existing = find_existing(syn, org, name, args.synonym_set_id)

    if existing:
        set_id = str(existing["id"])
        # `organizationName` and `name` are immutable; carry the live id + etag.
        body_obj = {
            **data,
            "id": set_id,
            "etag": existing["etag"],
            "organizationName": existing["organizationName"],
            "name": existing["name"],
        }
        print(
            f"🔁 Updating SynonymSet id={set_id} "
            f"({org}-{name}) — etag {existing['etag']}"
        )
        if args.dry_run:
            print("🔎 DRY RUN — would PUT:")
            print(json.dumps(body_obj, indent=2))
            return
        resp = syn.restPUT(f"/search/synonym/set/{set_id}", json.dumps(body_obj))
    else:
        if args.synonym_set_id is not None:
            print(f"❌ No SynonymSet found with id={args.synonym_set_id} in {org}.")
            raise SystemExit(1)
        if not args.create:
            print(
                f"❌ No SynonymSet named '{name}' found in {org}. "
                f"Re-run with --create to make a new one."
            )
            raise SystemExit(1)
        print(f"🆕 Creating new SynonymSet ({org}-{name})")
        if args.dry_run:
            print("🔎 DRY RUN — would POST:")
            print(json.dumps(data, indent=2))
            return
        resp = syn.restPOST("/search/synonym/set", json.dumps(data))

    n = len(resp.get("definition", {}).get("synonyms", []))
    print(
        f"✅ Done. id={resp.get('id')} etag={resp.get('etag')} "
        f"synonyms={n}"
    )


if __name__ == "__main__":
    main()
