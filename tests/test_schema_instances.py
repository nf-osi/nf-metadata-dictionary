"""
Validates JSON test instances against registered JSON schemas.

Discovers all YAML fixture files in the tests directory matching test_registry*.yaml.
Each fixture file contains one or more documents with the structure:

  schema: TemplateName
  instances:
    - file: data/TemplateName/instance.json
      description: What this tests
      expected: valid | invalid
      error_path: slotName   # optional, expected: invalid only

Instances marked expected: valid must pass schema validation.
Instances marked expected: invalid must fail schema validation.

An expected: invalid instance may additionally declare error_path: the instance
location that every validation error must point at, so the case proves the rule
it was written for rather than any failure at all. Use the quoted empty string
("") for the document root, which is where whole-object errors such as a missing
required property are reported. error_path must be a string; a bare `error_path:`
(YAML null) is rejected at collection time rather than read as absent or as the
document root.

Cases without error_path are collected as strict xfail. Cases with error_path
are collected as ordinary tests instead, because strict xfail reports any
failure as expected and would silently absorb an error_path mismatch.

`reason` labels the xfail for cases without error_path, and is printed in the
failure message for cases with one.
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
                expected = instance["expected"]
                has_error_path = "error_path" in instance
                error_path = instance["error_path"] if has_error_path else None
                if has_error_path and expected != "invalid":
                    raise ValueError(
                        f"{fixture.name}: {instance['file']} declares error_path but is "
                        f"expected {expected}; error_path applies to expected: invalid only"
                    )
                if has_error_path and not isinstance(error_path, str):
                    raise ValueError(
                        f"{fixture.name}: {instance['file']} declares error_path "
                        f"{error_path!r}; error_path must be a string - quote the empty "
                        f'string ("") for the document root'
                    )
                yield schema_name, instance, expected, has_error_path, error_path


CASES = list(_load_cases())


def _plain_params():
    for schema_name, instance, expected, has_error_path, _ in CASES:
        if has_error_path:
            continue
        yield pytest.param(
            schema_name,
            instance["file"],
            expected,
            id=f"{schema_name}/{Path(instance['file']).stem}[{expected}]",
            marks=pytest.mark.xfail(strict=True, reason=instance.get("reason", "")) if expected == "invalid" else [],
        )


def _error_path_params():
    for schema_name, instance, _expected, has_error_path, error_path in CASES:
        if not has_error_path:
            continue
        yield pytest.param(
            schema_name,
            instance["file"],
            error_path,
            instance.get("reason", ""),
            id=f"{schema_name}/{Path(instance['file']).stem}[invalid@{error_path or '<root>'}]",
        )


def _validation_errors(schema_name, file):
    schema = json.loads((SCHEMAS_DIR / f"{schema_name}.json").read_text())
    instance = json.loads((TESTS_DIR / file).read_text())
    validator = jsonschema.Draft7Validator(schema)
    return list(validator.iter_errors(instance))


def _location(error):
    return "/".join(str(part) for part in error.absolute_path)


def _describe(errors):
    return "\n".join(f"  - at {_location(e) or '<root>'}: {e.message}" for e in errors)


@pytest.mark.parametrize("schema_name,file,expected", list(_plain_params()))
def test_instance(schema_name, file, expected):
    errors = _validation_errors(schema_name, file)
    assert not errors, "\n".join(f"  - {e.message}" for e in errors)


@pytest.mark.parametrize("schema_name,file,error_path,reason", list(_error_path_params()))
def test_invalid_instance_fails_at_error_path(schema_name, file, error_path, reason):
    expectation = f"expected failure: {reason}" if reason else "no reason recorded"
    errors = _validation_errors(schema_name, file)
    assert errors, (
        f"{file} is expected to fail validation but the schema raised no errors "
        f"({expectation})"
    )
    locations = {_location(e) for e in errors}
    assert locations == {error_path}, (
        f"{file} must fail validation at {error_path or '<root>'} and nowhere else "
        f"({expectation}), but the schema raised:\n{_describe(errors)}"
    )
