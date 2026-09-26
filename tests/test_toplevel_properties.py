"""Generated schemas must expose their properties at the top level.

Synapse requires top-level `properties`, and consumers such as 
file-view column generation and the curator grid both depend on finding them at the top level.

Only `required` and the other requirement-bearing keywords are exempted; see
`GUARDED_KEYWORDS` in `utils/gen-json-schema-class.py`.
"""

import copy
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "registered-json-schemas"
GENERATOR_PATH = REPO_ROOT / "utils" / "gen-json-schema-class.py"
SPEC = importlib.util.spec_from_file_location("gen_json_schema_class", GENERATOR_PATH)
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)

SCHEMA_FILES = sorted(SCHEMA_DIR.glob("*.json"))

# Superdataset is not generator output: the `Superdataset` Makefile target composes
# it from PortalDataset.json plus rules/super_rules.json, and it is excluded from
# Synapse registration. Its nested `then.properties.contentType: {"const": "dataset"}`
# materializes a value on matching folders rather than declaring a field, so the
# "every property is declared at the top level" invariant does not apply.
NOT_GENERATOR_OUTPUT = {"Superdataset"}

# Subschema keywords that describe the same entity. `if` is excluded: its
# `properties` are match conditions (the folder exemption), not fields.
_APPLICATOR_LISTS = ("allOf", "anyOf", "oneOf")
_APPLICATOR_BRANCHES = ("then", "else")


def nested_property_paths(schema):
    """Yield (json_pointer, property_name) for properties below the top level."""
    def visit(node, path):
        if not isinstance(node, dict):
            return
        if path and isinstance(node.get("properties"), dict):
            for name in node["properties"]:
                yield f"{path}.properties", name
        for keyword in _APPLICATOR_LISTS:
            if isinstance(node.get(keyword), list):
                for index, branch in enumerate(node[keyword]):
                    yield from visit(branch, f"{path}.{keyword}[{index}]")
        for keyword in _APPLICATOR_BRANCHES:
            if keyword in node:
                yield from visit(node[keyword], f"{path}.{keyword}")

    yield from visit(schema, "")


@pytest.mark.parametrize("schema_file", SCHEMA_FILES, ids=lambda p: p.stem)
def test_properties_are_declared_at_top_level(schema_file):
    """Every property a template defines must be declared in top-level `properties`.

    Property-less abstract templates (Template, FileBasedTemplate, ...) pass
    trivially -- they declare no properties anywhere, which is not the failure
    this guards against.
    """
    if schema_file.stem in NOT_GENERATOR_OUTPUT:
        pytest.skip(f"{schema_file.stem} is composed by the Makefile, not the generator")

    schema = json.loads(schema_file.read_text())
    top_level = set(schema.get("properties", {}))

    hidden = {
        name: path
        for path, name in nested_property_paths(schema)
        if name not in top_level
    }

    assert not hidden, (
        f"{schema_file.name} declares properties that never appear in top-level "
        f"'properties': {sorted(hidden)}. Synapse requires top-level properties, and "
        f"file-view column generation reads them there. Found at: "
        f"{sorted(set(hidden.values()))}"
    )


@pytest.mark.parametrize("schema_file", SCHEMA_FILES, ids=lambda p: p.stem)
def test_top_level_properties_present_when_schema_has_fields(schema_file):
    """A schema with any validation content must expose top-level `properties`.

    Catches the inverse of the above: a schema whose entire body sits under the
    folder exemption, leaving the top level empty.
    """
    schema = json.loads(schema_file.read_text())
    if not schema.get("allOf"):
        pytest.skip("no folder exemption to hide properties behind")

    guarded_required = [
        name
        for path, name in nested_property_paths(schema)
    ]
    if not guarded_required:
        pytest.skip("guard carries no properties")

    assert schema.get("properties"), (
        f"{schema_file.name} has all of its properties under the folder exemption "
        "and none at the top level. `exempt_folders` must leave "
        "`properties` in place and guard only GUARDED_KEYWORDS."
    )


def test_generator_keeps_properties_at_top_level(tmp_path):
    """`exempt_folders` guards requirements, not field declarations."""
    schema_yaml = tmp_path / "schema.yaml"
    schema_yaml.write_text(
        "classes:\n"
        "  FileBasedTemplate:\n"
        "    abstract: true\n"
        "  FileTemplate:\n"
        "    is_a: FileBasedTemplate\n"
    )
    raw_schema = {
        "type": "object",
        "properties": {"fileFormat": {"type": "string"}},
        "required": ["fileFormat"],
    }

    schema = GENERATOR.process_schema(
        copy.deepcopy(raw_schema), "FileTemplate", schema_yaml_path=schema_yaml
    )

    assert "fileFormat" in schema.get("properties", {})
    # ...while the requirement stays behind the guard, so folders stay valid.
    assert "required" not in schema
    assert schema["allOf"][0]["then"]["required"] == ["fileFormat"]

    validator = jsonschema.Draft7Validator(schema)
    assert not list(validator.iter_errors({
        "concreteType": GENERATOR.FOLDER_CONCRETE_TYPE
    }))
    assert any(
        error.validator == "required"
        for error in validator.iter_errors({
            "concreteType": GENERATOR.FILE_ENTITY_CONCRETE_TYPE
        })
    )
