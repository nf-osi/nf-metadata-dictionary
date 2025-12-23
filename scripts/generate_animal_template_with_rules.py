#!/usr/bin/env python3
"""
Generate AnimalIndividualTemplate.yaml with LinkML rules for auto-filling fields.

This script reads the animal models mappings from the tools database and generates
a LinkML YAML file with rules that auto-fill metadata fields based on the selected
model system name.

Usage:
    python scripts/generate_animal_template_with_rules.py

Output:
    modules/Template/AnimalIndividualTemplate.yaml
"""

import json
from pathlib import Path
from typing import Dict, Any
import yaml


def load_animal_models(mappings_path: Path) -> Dict[str, Dict[str, Any]]:
    """Load animal models from the mappings JSON file."""
    with open(mappings_path, 'r') as f:
        return json.load(f)


def create_rule_for_model(model_name: str, model_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a LinkML rule for a single animal model.

    Args:
        model_name: The name/identifier of the model
        model_data: Dictionary containing metadata fields for this model

    Returns:
        A LinkML rule dictionary with preconditions and postconditions
    """
    # Define which fields should be auto-filled
    # Only include fields that are present in the model data
    autofill_fields = [
        'species',
        'organism',
        'genotype',
        'backgroundStrain',
        'RRID',
        'modelSystemType',
        'geneticModification',
        'manifestation',
        'institution',
        'description'
    ]

    # Build postconditions for fields that exist in the model data
    postconditions = {}
    for field in autofill_fields:
        if field in model_data and model_data[field]:
            # Use equals_string for the constraint
            postconditions[field] = {
                "equals_string": str(model_data[field])
            }

    # Only create a rule if there are fields to fill
    if not postconditions:
        return None

    rule = {
        "preconditions": {
            "slot_conditions": {
                "modelSystemName": {
                    "any_of": [
                        {"equals_string": model_name}
                    ]
                }
            }
        },
        "postconditions": {
            "slot_conditions": postconditions
        },
        "description": f"Auto-fill info for {model_name}"
    }

    return rule


def generate_animal_template(models: Dict[str, Dict[str, Any]], output_path: Path):
    """
    Generate the complete AnimalIndividualTemplate.yaml with rules.

    Args:
        models: Dictionary of animal models and their metadata
        output_path: Path where the YAML file should be written
    """

    # Define the template structure
    template = {
        "classes": {
            "AnimalIndividualTemplate": {
                "description": (
                    "Template for non-human individual-level data with auto-fill rules "
                    "based on model system selection. Rules are auto-generated from the "
                    "NF research tools database."
                ),
                "annotations": {
                    "required": False,
                    "requiresComponent": ""
                },
                "slots": [
                    "specimenID",
                    "individualID",
                    "sex",
                    "age",
                    "ageUnit",
                    "diagnosis",
                    "diagnosisAgeGroup",
                    "inheritance",
                    "mosaicism",
                    "nf1Genotype",
                    "nf2Genotype",
                    "germlineMutation",
                    "species",
                    "genotype",
                    "backgroundStrain",
                    "RRID",
                    "modelSystemName",
                    "modelSystemType",
                    "geneticModification",
                    "manifestation",
                    "institution",
                    "organism"
                ],
                "rules": []
            }
        }
    }

    # Generate rules for each model
    print(f"Generating rules for {len(models)} animal models...")
    rules_generated = 0

    for model_name, model_data in sorted(models.items()):
        rule = create_rule_for_model(model_name, model_data)
        if rule:
            template["classes"]["AnimalIndividualTemplate"]["rules"].append(rule)
            rules_generated += 1

    print(f"Generated {rules_generated} rules")

    # Write YAML file
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        # Write a comment header
        f.write("# Auto-generated AnimalIndividualTemplate with LinkML rules\n")
        f.write("# DO NOT EDIT MANUALLY - Generated from NF research tools database\n")
        f.write(f"# Total models: {len(models)}\n")
        f.write(f"# Total rules: {rules_generated}\n\n")

        # Write YAML with proper formatting
        yaml.dump(
            template,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120
        )

    print(f"✅ Template written to {output_path}")
    print(f"   Total slots: {len(template['classes']['AnimalIndividualTemplate']['slots'])}")
    print(f"   Total rules: {len(template['classes']['AnimalIndividualTemplate']['rules'])}")


def main():
    """Main entry point."""
    # Set up paths
    repo_root = Path(__file__).parent.parent
    mappings_path = repo_root / "auto-generated" / "mappings" / "animal_models_mappings.json"
    output_path = repo_root / "modules" / "Template" / "AnimalIndividualTemplate.yaml"

    # Verify input file exists
    if not mappings_path.exists():
        print(f"❌ Error: Mappings file not found at {mappings_path}")
        print("   Please run the tool fetching scripts first:")
        print("   1. python scripts/fetch_synapse_tools.py --use-materialized-view")
        print("   2. python scripts/generate_tool_schemas_from_view.py")
        return 1

    # Load models
    print(f"📖 Loading animal models from {mappings_path}")
    models = load_animal_models(mappings_path)
    print(f"   Found {len(models)} models")

    # Generate template
    generate_animal_template(models, output_path)

    print("\n📝 Next steps:")
    print("   1. Install LinkML: pip install linkml")
    print("   2. Build merged schema: make NF.yaml")
    print("   3. Generate JSON schema: python utils/gen-json-schema-class.py --class AnimalIndividualTemplate")
    print("   4. Test with Synapse to verify rule behavior")

    return 0


if __name__ == "__main__":
    exit(main())
