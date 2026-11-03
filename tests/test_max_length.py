"""`annotations.maxLength` must reach the generated schemas as JSON Schema `maxLength`.

LinkML has no string-length metaslot, so the Portal* classes carry their Synapse
column sizes as `annotations.maxLength`. The Makefile keeps that one annotation in
dist/NF.yaml and `utils/gen-json-schema-class.py` emits it, on `items` for list
fields since a list column's maximumSize limits each value.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "registered-json-schemas"
TEMPLATE_DIR = REPO_ROOT / "modules" / "Template"
GENERATOR_PATH = REPO_ROOT / "utils" / "gen-json-schema-class.py"
SPEC = importlib.util.spec_from_file_location("gen_json_schema_class_maxlength", GENERATOR_PATH)
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


@pytest.fixture
def fresh_yaml_cache(monkeypatch):
    """The generator caches the parsed model; give each test its own."""
    monkeypatch.setattr(GENERATOR, "_SHARED_YAML", None)


def _write(tmp_path, text):
    path = tmp_path / "schema.yaml"
    path.write_text(text)
    return path


def test_scalar_and_list_placement(tmp_path, fresh_yaml_cache):
    schema_yaml = _write(tmp_path, """
classes:
  Thing:
    attributes:
      name:
        annotations:
          maxLength: 20
      tags:
        multivalued: true
        annotations:
          maxLength: 5
      count:
        range: integer
""")
    raw = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "count": {"type": "integer"},
        },
    }
    schema = GENERATOR.process_schema(copy.deepcopy(raw), "Thing", schema_yaml_path=schema_yaml)
    props = schema["properties"]
    assert props["name"]["maxLength"] == 20
    assert props["tags"]["items"]["maxLength"] == 5
    assert "maxLength" not in props["tags"]
    assert "maxLength" not in props["count"]


def test_inheritance_and_slot_fallback(tmp_path, fresh_yaml_cache):
    schema_yaml = _write(tmp_path, """
slots:
  shared:
    annotations:
      maxLength: 99
classes:
  Parent:
    attributes:
      title:
        annotations:
          maxLength: 100
      note:
        annotations:
          maxLength: 10
  Child:
    is_a: Parent
    slots:
    - shared
    slot_usage:
      note:
        annotations:
          maxLength: 30
""")
    lengths = GENERATOR.get_class_max_lengths(schema_yaml, "Child")
    assert lengths == {"shared": 99, "title": 100, "note": 30}


def test_expanded_annotation_form(tmp_path, fresh_yaml_cache):
    schema_yaml = _write(tmp_path, """
classes:
  Thing:
    attributes:
      name:
        annotations:
          maxLength:
            tag: maxLength
            value: 12
""")
    assert GENERATOR.get_class_max_lengths(schema_yaml, "Thing") == {"name": 12}


def _module_max_lengths():
    """(class, attribute, maxLength) for every annotated attribute in modules/Template."""
    found = []
    for path in sorted(TEMPLATE_DIR.glob("*.yaml")):
        classes = (yaml.safe_load(path.read_text()) or {}).get("classes") or {}
        for cls_name, cls_def in classes.items():
            for attr, attr_def in ((cls_def or {}).get("attributes") or {}).items():
                value = GENERATOR._annotation_value(attr_def, "maxLength")
                if value is not None:
                    found.append((cls_name, attr, int(value)))
    return found


MODULE_MAX_LENGTHS = _module_max_lengths()


def test_model_declares_max_lengths():
    assert MODULE_MAX_LENGTHS, "expected maxLength annotations in modules/Template"


@pytest.mark.parametrize(
    "cls_name,attr,max_length",
    MODULE_MAX_LENGTHS,
    ids=[f"{c}.{a}" for c, a, _ in MODULE_MAX_LENGTHS],
)
def test_registered_schema_carries_max_length(cls_name, attr, max_length):
    """Reads the generated schemas: regenerate after editing modules/ (see CLAUDE.md)."""
    schema = json.loads((SCHEMA_DIR / f"{cls_name}.json").read_text())
    prop = schema["properties"][attr]
    target = prop["items"] if isinstance(prop.get("items"), dict) else prop
    assert target.get("maxLength") == max_length
