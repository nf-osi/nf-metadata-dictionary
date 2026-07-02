"""Tests for deriving RecordSet upsert keys from LinkML ``unique_keys``.

LinkML ``unique_keys`` declare a template's natural key but are not expressed in
the generated JSON Schema, so the Synapse JSON-Schema consumer does not enforce
them. Record uniqueness is instead enforced through RecordSet upsert keys.
``derive_upsert_keys`` bridges the two; these tests pin that behavior and guard
the ``unique_keys`` declarations on the record-based Biosample templates.
"""

import sys
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "utils"))

from create_recordset_task import derive_upsert_keys  # noqa: E402


def _write_model(tmp_path, body: str) -> str:
    model_file = tmp_path / "model.yaml"
    model_file.write_text(textwrap.dedent(body))
    return str(model_file)


def test_derive_compound_unique_key(tmp_path):
    model = _write_model(tmp_path, """
        classes:
          BiospecimenTemplate:
            unique_keys:
              specimen_natural_key:
                unique_key_slots:
                - individualID
                - specimenID
    """)
    assert derive_upsert_keys("BiospecimenTemplate", model) == [
        "individualID",
        "specimenID",
    ]


def test_derive_single_unique_key(tmp_path):
    model = _write_model(tmp_path, """
        classes:
          AnimalIndividualTemplate:
            unique_keys:
              individual_natural_key:
                unique_key_slots:
                - individualID
    """)
    assert derive_upsert_keys("AnimalIndividualTemplate", model) == ["individualID"]


def test_no_unique_keys_returns_none(tmp_path):
    model = _write_model(tmp_path, """
        classes:
          SomeTemplate:
            slots:
            - specimenID
    """)
    assert derive_upsert_keys("SomeTemplate", model) is None


def test_unknown_template_returns_none(tmp_path):
    model = _write_model(tmp_path, """
        classes:
          SomeTemplate:
            unique_keys:
              k:
                unique_key_slots:
                - specimenID
    """)
    assert derive_upsert_keys("DoesNotExist", model) is None


def test_unique_key_inherited_via_is_a(tmp_path):
    model = _write_model(tmp_path, """
        classes:
          BaseRecord:
            unique_keys:
              natural_key:
                unique_key_slots:
                - individualID
          ChildRecord:
            is_a: BaseRecord
    """)
    assert derive_upsert_keys("ChildRecord", model) == ["individualID"]


def test_missing_model_file_returns_none(tmp_path):
    assert derive_upsert_keys("Whatever", str(tmp_path / "nope.yaml")) is None


# --- Guard the actual source declarations on the Biosample record templates ---

EXPECTED_BIOSAMPLE_UNIQUE_KEYS = {
    "AnimalIndividualTemplate": ["individualID"],
    "BiospecimenTemplate": ["individualID", "specimenID"],
    "HumanCohortTemplate": ["individualID"],
}


def test_biosample_templates_declare_expected_unique_keys():
    source = REPO_ROOT / "modules" / "Template" / "Biosample.yaml"
    classes = yaml.safe_load(source.read_text())["classes"]
    for template, expected_slots in EXPECTED_BIOSAMPLE_UNIQUE_KEYS.items():
        unique_keys = classes[template].get("unique_keys")
        assert unique_keys, f"{template} should declare unique_keys"
        first = next(iter(unique_keys.values()))
        assert first["unique_key_slots"] == expected_slots
