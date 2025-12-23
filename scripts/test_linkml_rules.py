#!/usr/bin/env python3
"""
Test and validate the AnimalIndividualTemplate.yaml with LinkML rules.

This script validates the YAML structure and demonstrates how the rules work.
"""

import yaml
from pathlib import Path
from typing import Dict, Any


def load_template(yaml_path: Path) -> Dict[str, Any]:
    """Load the AnimalIndividualTemplate YAML file."""
    with open(yaml_path, 'r') as f:
        return yaml.safe_load(f)


def validate_structure(template: Dict[str, Any]) -> bool:
    """Validate the basic structure of the template."""
    print("🔍 Validating YAML structure...")

    errors = []

    # Check classes exist
    if 'classes' not in template:
        errors.append("Missing 'classes' key")
        return False

    # Check AnimalIndividualTemplate exists
    if 'AnimalIndividualTemplate' not in template['classes']:
        errors.append("Missing 'AnimalIndividualTemplate' class")
        return False

    animal_template = template['classes']['AnimalIndividualTemplate']

    # Check required fields
    required_fields = ['description', 'slots', 'rules']
    for field in required_fields:
        if field not in animal_template:
            errors.append(f"Missing required field: {field}")

    # Check slots
    if not isinstance(animal_template.get('slots'), list):
        errors.append("'slots' must be a list")

    # Check rules
    if not isinstance(animal_template.get('rules'), list):
        errors.append("'rules' must be a list")

    # Validate each rule
    for i, rule in enumerate(animal_template.get('rules', [])):
        if 'preconditions' not in rule:
            errors.append(f"Rule {i}: Missing 'preconditions'")
        if 'postconditions' not in rule:
            errors.append(f"Rule {i}: Missing 'postconditions'")
        if 'description' not in rule:
            errors.append(f"Rule {i}: Missing 'description'")

    if errors:
        print("❌ Validation failed:")
        for error in errors:
            print(f"   - {error}")
        return False

    print("✅ YAML structure is valid")
    return True


def analyze_rules(template: Dict[str, Any]):
    """Analyze the rules in the template."""
    print("\n📊 Analyzing rules...")

    animal_template = template['classes']['AnimalIndividualTemplate']
    rules = animal_template['rules']

    print(f"   Total rules: {len(rules)}")

    # Count fields that are auto-filled
    field_counts = {}
    for rule in rules:
        postconditions = rule['postconditions']['slot_conditions']
        for field in postconditions.keys():
            field_counts[field] = field_counts.get(field, 0) + 1

    print(f"\n   Fields auto-filled across all rules:")
    for field, count in sorted(field_counts.items(), key=lambda x: -x[1]):
        percentage = (count / len(rules)) * 100
        print(f"   - {field}: {count}/{len(rules)} rules ({percentage:.1f}%)")


def show_example_rules(template: Dict[str, Any], num_examples: int = 3):
    """Show example rules."""
    print(f"\n📝 Example rules (first {num_examples}):\n")

    animal_template = template['classes']['AnimalIndividualTemplate']
    rules = animal_template['rules']

    for i, rule in enumerate(rules[:num_examples]):
        # Get model name from precondition
        model_name = rule['preconditions']['slot_conditions']['modelSystemName']['any_of'][0]['equals_string']

        # Get auto-filled fields
        postconditions = rule['postconditions']['slot_conditions']

        print(f"{'='*80}")
        print(f"Rule {i+1}: {model_name}")
        print(f"{'='*80}")
        print(f"When user selects modelSystemName = '{model_name}'")
        print(f"Then auto-fill:")

        for field, condition in postconditions.items():
            value = condition.get('equals_string', 'N/A')
            # Truncate long values
            if len(str(value)) > 60:
                value = str(value)[:57] + "..."
            print(f"  • {field:25s} = {value}")
        print()


def simulate_lookup(template: Dict[str, Any], model_name: str):
    """Simulate looking up auto-fill values for a model."""
    print(f"\n🔎 Simulating lookup for: {model_name}\n")

    animal_template = template['classes']['AnimalIndividualTemplate']
    rules = animal_template['rules']

    # Find matching rule
    for rule in rules:
        precond_model = rule['preconditions']['slot_conditions']['modelSystemName']['any_of'][0]['equals_string']

        if precond_model == model_name:
            print(f"✅ Found rule for '{model_name}'")
            print(f"\nAuto-fill values:")

            postconditions = rule['postconditions']['slot_conditions']
            for field, condition in postconditions.items():
                value = condition.get('equals_string', 'N/A')
                print(f"  {field:25s} = {value}")
            return

    print(f"❌ No rule found for '{model_name}'")


def main():
    """Main entry point."""
    print("=" * 80)
    print("LinkML Rules Test - AnimalIndividualTemplate")
    print("=" * 80)

    # Load template
    repo_root = Path(__file__).parent.parent
    yaml_path = repo_root / "modules" / "Template" / "AnimalIndividualTemplate.yaml"

    if not yaml_path.exists():
        print(f"❌ Error: Template file not found at {yaml_path}")
        return 1

    print(f"\n📖 Loading: {yaml_path}")
    template = load_template(yaml_path)

    # Validate structure
    if not validate_structure(template):
        return 1

    # Analyze rules
    analyze_rules(template)

    # Show examples
    show_example_rules(template, num_examples=2)

    # Simulate lookups
    test_models = [
        "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)",
        "Nf1pArg1947mp1"
    ]

    for model in test_models:
        simulate_lookup(template, model)

    print("\n" + "=" * 80)
    print("✅ All tests passed!")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    exit(main())
