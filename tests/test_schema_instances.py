"""
Validates JSON test instances against registered JSON schemas.

Discovers all YAML fixture files in the tests directory matching *_test_instances.yaml.
Each fixture file contains one or more documents with the structure:

  schema: TemplateName
  instances:
    - file: data/TemplateName/instance.json
      description: What this tests
      expected: valid | invalid

Instances marked expected: valid must pass schema validation.
Instances marked expected: invalid must fail schema validation.

Every test here reads the generated artifacts in registered-json-schemas/, which CI
rebuilds before the pytest job. Locally the committed artifacts come from main, so run
`make -B` followed by `python utils/gen-json-schema-class.py --class <Class>` first.
"""

import json
import os
from pathlib import Path

import jsonschema
import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SCHEMAS_DIR = Path(os.environ.get("SCHEMAS_DIR", REPO_ROOT / "registered-json-schemas"))
PORTAL_MODULE = REPO_ROOT / "modules" / "DCC" / "Portal.yaml"


def _load_cases():
    for fixture in sorted(TESTS_DIR.glob("test_registry*.yaml")):
        for doc in yaml.safe_load_all(fixture.read_text()):
            if not doc:
                continue
            schema_name = doc["schema"]
            for instance in doc["instances"]:
                yield pytest.param(
                    schema_name,
                    instance["file"],
                    instance["expected"],
                    id=f"{schema_name}/{Path(instance['file']).stem}[{instance['expected']}]",
                    marks=pytest.mark.xfail(strict=True, reason=instance.get("reason", "")) if instance["expected"] == "invalid" else [],
                )


@pytest.mark.parametrize("schema_name,file,expected", _load_cases())
def test_instance(schema_name, file, expected):
    schema = json.loads((SCHEMAS_DIR / f"{schema_name}.json").read_text())
    instance = json.loads((TESTS_DIR / file).read_text())
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(instance))
    assert not errors, "\n".join(f"  - {e.message}" for e in errors)


def _deprecated_manifestation_labels():
    enums = yaml.safe_load(PORTAL_MODULE.read_text())["enums"]
    values = enums["ManifestationEnum"]["permissible_values"]
    return sorted(label for label, meta in values.items() if (meta or {}).get("deprecated"))


def test_deprecated_manifestation_values_are_still_emitted():
    deprecated = _deprecated_manifestation_labels()
    assert deprecated, (
        f"No deprecated ManifestationEnum values found in {PORTAL_MODULE.relative_to(REPO_ROOT)}. "
        "Deprecated labels are retained until a major release, so this guard should have values to check."
    )

    schema = json.loads((SCHEMAS_DIR / "PortalDataset.json").read_text())
    emitted = schema["properties"]["manifestation"]["items"]["enum"]
    missing = [label for label in deprecated if label not in emitted]

    assert not missing, (
        "Deprecated ManifestationEnum values are missing from the generated "
        f"PortalDataset.json manifestation enum: {missing}. "
        "Every existing dataset and study annotation using one of these labels becomes "
        "schema-invalid the moment it stops being emitted, so this assertion is what keeps "
        "the release non-breaking. If it starts failing after a linkml upgrade, reconsider "
        "the upgrade rather than dropping the labels."
    )
