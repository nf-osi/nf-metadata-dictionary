"""Tests for the folder exemption on file-based template schemas."""

import copy
import importlib.util
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = REPO_ROOT / "utils" / "gen-json-schema-class.py"
SPEC = importlib.util.spec_from_file_location("gen_json_schema_class", GENERATOR_PATH)
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def _file_template_schema(tmp_path):
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

    return GENERATOR.process_schema(
        copy.deepcopy(raw_schema), "FileTemplate", schema_yaml_path=schema_yaml
    )


def test_folders_are_not_required_to_carry_file_metadata(tmp_path):
    validator = jsonschema.Draft7Validator(_file_template_schema(tmp_path))

    assert not list(validator.iter_errors({
        "concreteType": GENERATOR.FOLDER_CONCRETE_TYPE
    }))


def test_files_still_carry_file_metadata(tmp_path):
    validator = jsonschema.Draft7Validator(_file_template_schema(tmp_path))

    errors = validator.iter_errors({"concreteType": GENERATOR.FILE_ENTITY_CONCRETE_TYPE})

    assert any(error.validator == "required" for error in errors)


def test_untyped_records_still_carry_file_metadata(tmp_path):
    """A manifest row or in-flight upload has no ``concreteType`` to match on.

    The guard asks "not a folder" rather than "is a FileEntity" precisely so
    these keep validating; an `is a FileEntity` test would exempt them too.
    """
    validator = jsonschema.Draft7Validator(_file_template_schema(tmp_path))

    errors = validator.iter_errors({})

    assert any(error.validator == "required" for error in errors)


def test_other_entity_types_are_not_exempt(tmp_path):
    """Only folders are excused. A Link sitting in a bound folder is not."""
    validator = jsonschema.Draft7Validator(_file_template_schema(tmp_path))

    errors = validator.iter_errors({"concreteType": "org.sagebionetworks.repo.model.Link"})

    assert any(error.validator == "required" for error in errors)
