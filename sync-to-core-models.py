import json
import requests
import sys

# ─── CONFIG ───────────────────────────────────────────────────────────────────
API_BASE   = "https://go.coremodels.io/v1"
PROJECT_ID = "4c4485fa8936418b85b96fb113272694"

# load your token from .coreModelsConfig
with open(".coreModelsConfig", "r") as f:
    cfg = json.load(f)
BEARER_TOKEN = cfg["token"].strip()

HEADERS = {
    "Authorization": f"Bearer {BEARER_TOKEN}",
    "Accept":        "application/json",
    "Content-Type":  "application/json",
}

# ─── MERGE FUNCTION ────────────────────────────────────────────────────────────
def merge_json_schema(project_id,
                      space_id,
                      config_type_id,
                      owner,
                      repository,
                      branch,
                      file_path,
                      override_new_props=True,
                      override_diff_source=True,
                      override_overwrite=True,
                      only_add_and_update=True):
    """
    Call GET /v1/{projectId}/mergeJSONSchema
    Returns the merged JSON Schema as a string.
    """
    url = f"{API_BASE}/{project_id}/mergeJSONSchema"
    params = {
        "SpaceId":                         space_id,
        "ConfigTypeId":                    config_type_id,
        "Owner":                           owner,
        "Repository":                      repository,
        "Branch":                          branch,
        "FilePath":                        file_path,
        "OverrideNewPropertiesWarning":    str(override_new_props).lower(),
        "OverrideDifferentSourceWarning":  str(override_diff_source).lower(),
        "OverrideOverwriteWarning":        str(override_overwrite).lower(),
        "OnlyAddAndUpdate":                str(only_add_and_update).lower(),
    }
    resp = requests.get(url, headers=HEADERS, params=params)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        print(f"HTTP Error: {e} — {resp.text}", file=sys.stderr)
        sys.exit(1)

    body = resp.json()
    if not body.get("success", False):
        print(f"API Error: {body.get('error')}", file=sys.stderr)
        sys.exit(1)

    return body["data"]


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # your specific parameters
    SPACE_ID               = "ab341445908b49238ac494d23280626b"
    CONFIG_TYPE_ID         = "2bad95b244884cebb80917b5d809b3a7"
    OWNER                  = "nf-osi"
    REPOSITORY             = "nf-metadata-dictionary"
    BRANCH                 = "batch-convert"
    FILE_PATH              = "registered-json-schemas/BulkSequencingAssayTemplate-deref.json"
    OVERRIDE_NEW_PROPS     = True
    OVERRIDE_DIFF_SOURCE   = True
    OVERRIDE_OVERWRITE     = True
    ONLY_ADD_AND_UPDATE    = True

    merged_schema = merge_json_schema(
        PROJECT_ID,
        SPACE_ID,
        CONFIG_TYPE_ID,
        OWNER,
        REPOSITORY,
        BRANCH,
        FILE_PATH,
        override_new_props=OVERRIDE_NEW_PROPS,
        override_diff_source=OVERRIDE_DIFF_SOURCE,
        override_overwrite=OVERRIDE_OVERWRITE,
        only_add_and_update=ONLY_ADD_AND_UPDATE
    )

    # print the merged schema (or write to file)
    print(merged_schema)
