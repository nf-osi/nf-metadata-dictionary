"""Regression tests for controlled schema escape hatches."""

import json
import os
from pathlib import Path

import jsonschema
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = Path(os.environ.get("SCHEMAS_DIR", REPO_ROOT / "registered-json-schemas"))


def _property_schema(template_name, property_name):
    schema = json.loads((SCHEMAS_DIR / f"{template_name}.json").read_text())
    return schema["allOf"][0]["then"]["properties"][property_name]


def _compound_dose_unit_rule(template_name):
    schema = json.loads((SCHEMAS_DIR / f"{template_name}.json").read_text())
    rules = schema["allOf"][0]["then"].get("allOf", [])
    return next(rule for rule in rules if "compoundDoseUnit" in rule.get("then", {}).get("required", []))


@pytest.mark.parametrize("template_name", ["FlowCytometryTemplate", "PlateBasedReporterAssayTemplate"])
def test_platform_accepts_other_platform(template_name):
    platform_schema = _property_schema(template_name, "platform")

    jsonschema.Draft7Validator(platform_schema).validate("Other Platform")


@pytest.mark.parametrize("compound_dose", [12.5, "Not Applicable", "Not Available", "Multiple Doses"])
def test_compound_dose_accepts_numeric_and_controlled_escape_hatches(compound_dose):
    compound_dose_schema = _property_schema("ClinicalAssayTemplate", "compoundDose")

    jsonschema.Draft7Validator(compound_dose_schema).validate(compound_dose)


@pytest.mark.parametrize("compound_dose", ["NA", "Unspecified dose"])
def test_compound_dose_rejects_uncontrolled_text(compound_dose):
    compound_dose_schema = _property_schema("ClinicalAssayTemplate", "compoundDose")

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(compound_dose_schema).validate(compound_dose)


@pytest.mark.parametrize(
    "template_name",
    [
        "ClinicalAssayTemplate",
        "BehavioralAssayTemplate",
        "CellTissuePhenotypingTemplate",
        "PlateBasedReporterAssayTemplate",
    ],
)
def test_compound_dose_categories_do_not_require_a_unit(template_name):
    rule = _compound_dose_unit_rule(template_name)

    jsonschema.Draft7Validator(rule).validate({"compoundDose": "Not Applicable"})


@pytest.mark.parametrize(
    "template_name",
    [
        "ClinicalAssayTemplate",
        "BehavioralAssayTemplate",
        "CellTissuePhenotypingTemplate",
        "PlateBasedReporterAssayTemplate",
    ],
)
def test_numeric_compound_dose_requires_a_unit(template_name):
    rule = _compound_dose_unit_rule(template_name)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(rule).validate({"compoundDose": 12.5})


def test_plate_based_experimental_data_does_not_require_a_unit_for_dose_categories():
    schema = json.loads((SCHEMAS_DIR / "PlateBasedReporterAssayTemplate.json").read_text())
    rules = schema["allOf"][0]["then"].get("allOf", [])
    experimental_data_rule = next(
        rule
        for rule in rules
        if rule.get("if", {}).get("properties", {}).get("resourceType", {}).get("const") == "experimentalData"
    )

    assert "compoundDoseUnit" not in experimental_data_rule["then"]["required"]
