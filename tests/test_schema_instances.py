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
"""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SCHEMAS_DIR = REPO_ROOT / "registered-json-schemas"


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
