"""Tests for concrete-type scoping of file-based template schemas."""

import copy
import importlib.util
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = REPO_ROOT / "utils" / "gen-json-schema-class.py"
SPEC = importlib.util.spec_from_file_location("gen_json_schema_class", GENERATOR_PATH)
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def test_file_based_template_constraints_skip_folders(tmp_path):
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

    validator = jsonschema.Draft7Validator(schema)
    folder_errors = list(validator.iter_errors({
        "concreteType": "org.sagebionetworks.repo.model.Folder"
    }))
    file_errors = list(validator.iter_errors({
        "concreteType": GENERATOR.FILE_ENTITY_CONCRETE_TYPE
    }))
    untyped_errors = list(validator.iter_errors({}))

    assert not folder_errors
    assert any(error.validator == "required" for error in file_errors)
    assert any(error.validator == "required" for error in untyped_errors)
