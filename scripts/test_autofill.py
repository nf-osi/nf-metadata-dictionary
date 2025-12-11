#!/usr/bin/env python3
"""
Test auto-fill functionality with sample data.

This script demonstrates how schematic/DCA can use the auto-generated
mappings to auto-populate metadata fields.
"""

import json
import sys


def load_autofill_config():
    """Load auto-fill configuration."""
    with open('auto-generated/autofill-config.json') as f:
        return json.load(f)


def load_lookup_service():
    """Load unified lookup service."""
    with open('auto-generated/lookup-service.json') as f:
        return json.load(f)


def autofill_fields(schema_name, trigger_field, selected_value, lookup_service, autofill_config):
    """
    Auto-fill metadata fields based on selected tool.

    Args:
        schema_name: Name of the schema (e.g., 'AnimalIndividualTemplate.json')
        trigger_field: Field that triggers auto-fill (e.g., 'modelSystemName')
        selected_value: Value selected by user
        lookup_service: Lookup service data
        autofill_config: Auto-fill configuration

    Returns:
        Dictionary of auto-filled field values
    """
    # Find applicable rule
    for rule in autofill_config['rules']:
        if rule['schema'] == schema_name and rule['triggerField'] == trigger_field:
            # Get tool type from mapping source
            tool_type = rule['mappingSource'].split('/')[-1].replace('_mappings.json', '')

            # Lookup the tool's attributes
            if tool_type in lookup_service['tools']:
                mappings = lookup_service['tools'][tool_type]['mappings']

                if selected_value in mappings:
                    attributes = mappings[selected_value]

                    # Auto-fill fields
                    auto_values = {}
                    for schema_field, mapping_field in rule['autoFields'].items():
                        if mapping_field in attributes:
                            auto_values[schema_field] = attributes[mapping_field]

                    return {
                        'success': True,
                        'values': auto_values,
                        'allAttributes': attributes,
                        'toolType': tool_type
                    }
                else:
                    return {
                        'success': False,
                        'error': f"Tool '{selected_value}' not found in {tool_type} mappings",
                        'suggestion': "Check if tool name matches exactly"
                    }

    return {
        'success': False,
        'error': f"No auto-fill rule found for schema={schema_name}, field={trigger_field}"
    }


def test_animal_model_autofill():
    """Test auto-fill for animal models."""
    print("="*70)
    print("TEST 1: Animal Model Auto-Fill")
    print("="*70)

    lookup = load_lookup_service()
    config = load_autofill_config()

    # Test with a specific model
    test_model = "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"

    print(f"\nScenario: User selects modelSystemName = '{test_model}'")
    print("\nExpected behavior: Auto-fill species, genotype, backgroundStrain")

    result = autofill_fields(
        schema_name='AnimalIndividualTemplate.json',
        trigger_field='modelSystemName',
        selected_value=test_model,
        lookup_service=lookup,
        autofill_config=config
    )

    if result['success']:
        print("\n✓ Auto-fill SUCCESS")
        print("\nFields to auto-populate:")
        for field, value in result['values'].items():
            print(f"  {field:20} = {value}")

        print("\nAll available attributes for this tool:")
        for field, value in result['allAttributes'].items():
            if field not in result['values']:
                print(f"  {field:20} = {value}")
    else:
        print(f"\n✗ Auto-fill FAILED: {result['error']}")


def test_cell_line_autofill():
    """Test auto-fill for cell lines."""
    print("\n" + "="*70)
    print("TEST 2: Cell Line Auto-Fill")
    print("="*70)

    lookup = load_lookup_service()
    config = load_autofill_config()

    # Get first cell line from lookup
    cell_lines = lookup['tools']['cell_lines']['mappings']
    test_cell_line = list(cell_lines.keys())[0]

    print(f"\nScenario: User selects a cell line = '{test_cell_line}'")
    print("\nNote: BiospecimenTemplate integration pending (needs field mapping)")

    # Show what attributes are available
    print("\nAvailable attributes for this cell line:")
    for field, value in cell_lines[test_cell_line].items():
        print(f"  {field:20} = {value}")


def test_validation_with_autofill():
    """Test validation when auto-filled values don't match user input."""
    print("\n" + "="*70)
    print("TEST 3: Validation with Auto-Fill")
    print("="*70)

    lookup = load_lookup_service()
    config = load_autofill_config()

    test_model = "B6.129(Cg)-Nf1tm1Par/J (rrid:IMSR_JAX:017640)"

    print(f"\nScenario: User manually enters data that conflicts with auto-fill")
    print(f"  modelSystemName = '{test_model}'")
    print(f"  species (user entered) = 'Rattus norvegicus'")

    # Get expected values
    result = autofill_fields(
        'AnimalIndividualTemplate.json',
        'modelSystemName',
        test_model,
        lookup,
        config
    )

    if result['success']:
        expected_species = result['values'].get('species')
        user_species = 'Rattus norvegicus'

        print(f"\n  Expected species (from mapping) = '{expected_species}'")

        if user_species != expected_species:
            print(f"\n⚠️  VALIDATION WARNING:")
            print(f"     Species '{user_species}' doesn't match expected '{expected_species}'")
            print(f"     for model '{test_model}'")
            print(f"\n  Suggestion: Update species to '{expected_species}' or verify model selection")


def test_lookup_by_rrid():
    """Test looking up tools by RRID."""
    print("\n" + "="*70)
    print("TEST 4: Lookup Tool by RRID")
    print("="*70)

    lookup = load_lookup_service()

    # Search for tools with a specific RRID
    search_rrid = "IMSR_JAX:017640"

    print(f"\nScenario: Search for tool with RRID containing '{search_rrid}'")

    found_tools = []
    for tool_type, data in lookup['tools'].items():
        for tool_name, attributes in data['mappings'].items():
            rrid = attributes.get('RRID', '')
            if search_rrid in rrid or search_rrid in tool_name:
                found_tools.append({
                    'type': tool_type,
                    'name': tool_name,
                    'rrid': rrid
                })

    if found_tools:
        print(f"\n✓ Found {len(found_tools)} tool(s):")
        for tool in found_tools:
            print(f"\n  {tool['type']}:")
            print(f"    Name: {tool['name']}")
            print(f"    RRID: {tool['rrid']}")
    else:
        print(f"\n✗ No tools found with RRID '{search_rrid}'")


def main():
    """Run all tests."""
    try:
        test_animal_model_autofill()
        test_cell_line_autofill()
        test_validation_with_autofill()
        test_lookup_by_rrid()

        print("\n" + "="*70)
        print("ALL TESTS COMPLETED")
        print("="*70)
        print("\nNext steps:")
        print("1. Integrate these patterns into schematic/DCA")
        print("2. Test with real manifests")
        print("3. Gather user feedback on auto-fill behavior")
        print("="*70)

        return 0

    except FileNotFoundError as e:
        print(f"\n✗ Error: Required file not found")
        print(f"  {e}")
        print("\nRun the following first:")
        print("  python scripts/generate_tool_schemas_from_view.py")
        print("  python scripts/integrate_tool_mappings.py")
        return 1


if __name__ == '__main__':
    sys.exit(main())
