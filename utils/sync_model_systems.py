#!/usr/bin/env python3
"""
Sync model systems, antibodies, and genetic reagents from NF Tools Database.

This script queries syn51730943 (NF Tools Central) and generates:
1. Base enum files (CellLineModel.yaml, AnimalModel.yaml, Antibody.yaml, GeneticReagent.yaml)
2. Filtered enum subsets for conditional dependencies (species + category + disorder combinations)

The filtered subsets enable JSON schemas to provide <100 enum values per dropdown
based on user's selections in modelSystemType, modelSpecies, cellLineCategory, etc.

This prevents Synapse's 100-value enum limit errors while maintaining full data coverage.
"""

import os
import sys
import yaml
from typing import Dict, List, Any, Tuple
import argparse


def fetch_model_system_data_with_metadata(synapse_id: str = 'syn51730943') -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict]]:
    """
    Fetch cell lines, animal models, antibodies, and genetic reagents with full metadata from NF Tools Database.

    Args:
        synapse_id: Synapse table ID for NF Tools Central (default: syn51730943)

    Returns:
        Tuple of (cell_lines_list, animal_models_list, antibodies_list, genetic_reagents_list) with full metadata
    """
    try:
        import synapseclient
        from synapseclient import Synapse

        syn = Synapse()

        # Try to login - anonymous access should work for public tables
        try:
            if os.getenv('SYNAPSE_AUTH_TOKEN'):
                syn.login(authToken=os.getenv('SYNAPSE_AUTH_TOKEN'), silent=True)
        except:
            pass

        print(f"Fetching resource data from {synapse_id}...")

        # Query for cell lines with all relevant metadata
        cell_query = """
            SELECT resourceName, rrid, description, resourceType, species,
                   cellLineCategory, cellLineGeneticDisorder, resourceId
            FROM {table}
            WHERE resourceType = 'Cell Line'
        """.format(table=synapse_id)

        cell_result = syn.tableQuery(cell_query)
        cell_df = cell_result.asDataFrame()

        print(f"  → Retrieved {len(cell_df)} cell lines")

        # Query for animal models
        animal_query = """
            SELECT resourceName, rrid, description, resourceType, species,
                   animalModelGeneticDisorder, resourceId
            FROM {table}
            WHERE resourceType = 'Animal Model'
        """.format(table=synapse_id)

        animal_result = syn.tableQuery(animal_query)
        animal_df = animal_result.asDataFrame()

        print(f"  → Retrieved {len(animal_df)} animal models")

        # Query for antibodies
        antibody_query = """
            SELECT resourceName, rrid, description, resourceType, resourceId
            FROM {table}
            WHERE resourceType = 'Antibody'
        """.format(table=synapse_id)

        antibody_result = syn.tableQuery(antibody_query)
        antibody_df = antibody_result.asDataFrame()

        print(f"  → Retrieved {len(antibody_df)} antibodies")

        # Query for genetic reagents
        reagent_query = """
            SELECT resourceName, rrid, description, resourceType, resourceId
            FROM {table}
            WHERE resourceType = 'Genetic Reagent'
        """.format(table=synapse_id)

        reagent_result = syn.tableQuery(reagent_query)
        reagent_df = reagent_result.asDataFrame()

        print(f"  → Retrieved {len(reagent_df)} genetic reagents")

        # Convert DataFrames to list of dicts
        cell_lines = cell_df.to_dict('records')
        animal_models = animal_df.to_dict('records')
        antibodies = antibody_df.to_dict('records')
        genetic_reagents = reagent_df.to_dict('records')

        return cell_lines, animal_models, antibodies, genetic_reagents

    except ImportError:
        print("Error: synapseclient not available")
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching data: {e}")
        sys.exit(1)


def format_enum_entry_enhanced(resource: Dict[str, Any]) -> Dict:
    """
    Format a model system entry for YAML enum with full metadata.

    Args:
        resource: Dict with resource metadata from syn51730943

    Returns:
        Dict with formatted enum entry
    """
    import pandas as pd

    name = resource.get('resourceName', '')
    if not name or pd.isna(name):
        return {}

    entry = {}

    # Add description if different from name
    description = resource.get('description', '')
    if description and not pd.isna(description) and description != name:
        entry['description'] = str(description)

    # Add RRID as 'meaning' field
    rrid = resource.get('rrid', '')
    if rrid and not pd.isna(rrid):
        entry['meaning'] = str(rrid)

    # Add source link to NF Tools Central
    resource_id = resource.get('resourceId', '')
    if resource_id and not pd.isna(resource_id):
        entry['source'] = f"https://nf.synapse.org/Explore/Tools/DetailsPage/Details?resourceId={resource_id}"

    return {name: entry} if entry else {name: {}}


def generate_filtered_enum_subsets(cell_lines: List[Dict], animal_models: List[Dict]) -> Dict[str, Dict]:
    """
    Generate filtered enum subsets based on species, category, and genetic disorder.

    Returns:
        Dict mapping enum_name to {permissible_values: {...}}
    """
    from collections import defaultdict
    import pandas as pd

    print("\n" + "="*60)
    print("GENERATING FILTERED ENUM SUBSETS")
    print("="*60)

    # Helper to check if species list contains target
    def has_species(species_list, target):
        if not isinstance(species_list, list):
            return False
        return any(target in str(s) for s in species_list)

    # Group cell lines by species + category + disorder
    cell_grouped = defaultdict(list)

    for cell in cell_lines:
        species_list = cell.get('species', [])
        category = cell.get('cellLineCategory', 'Unknown')
        disorder_list = cell.get('cellLineGeneticDisorder', [])

        # Normalize empty/null values
        if not isinstance(species_list, list) or not species_list:
            species_list = ['Unknown']
        # Handle NaN/None/float values for category
        if pd.isna(category) or not category or category == '' or not isinstance(category, str):
            category = 'Unknown'
        if not isinstance(disorder_list, list) or not disorder_list:
            disorder_list = ['Unknown']

        # Create entries for each species
        for species in species_list:
            # Normalize species name for file naming
            species_short = species.replace(' ', '').replace('.', '')

            # For each disorder combination
            for disorder in disorder_list:
                disorder_short = disorder.replace(' ', '').replace('[', '').replace(']', '').replace("'", '')

                # Create key for this combination
                key = (species_short, category, disorder_short)
                cell_grouped[key].append(cell)

    # Group animal models by species + disorder
    animal_grouped = defaultdict(list)

    for animal in animal_models:
        species_list = animal.get('species', [])
        disorder_list = animal.get('animalModelGeneticDisorder', [])

        if not isinstance(species_list, list) or not species_list:
            species_list = ['Unknown']
        if not isinstance(disorder_list, list) or not disorder_list:
            disorder_list = ['Unknown']

        for species in species_list:
            species_short = species.replace(' ', '').replace('.', '')
            for disorder in disorder_list:
                disorder_short = disorder.replace(' ', '').replace('[', '').replace(']', '').replace("'", '')
                key = (species_short, disorder_short)
                animal_grouped[key].append(animal)

    # Generate enum files for combinations with reasonable counts
    enums = {}

    # Cell line enums
    for (species, category, disorder), cells in cell_grouped.items():
        count = len(cells)

        # Only generate if <100 entries or if it's a major category
        if count > 100 and count < 400:
            # Skip - would need further filtering
            continue

        # Create enum name
        category_safe = category.replace(' ', '').replace('-', '')
        enum_name = f"CellLine{species}{category_safe}{disorder}Enum"

        # Format entries
        entries = {}
        for cell in cells:
            formatted = format_enum_entry_enhanced(cell)
            entries.update(formatted)

        if entries:
            enums[enum_name] = {
                'description': f"Cell lines: {species} + {category} + {disorder} ({count} entries)",
                'permissible_values': entries,
                '_metadata': {
                    'species': species,
                    'category': category,
                    'disorder': disorder,
                    'count': count,
                    'type': 'cell_line'
                }
            }

    # Animal model enums
    for (species, disorder), animals in animal_grouped.items():
        count = len(animals)

        if count > 100:
            continue  # Skip if still too large

        enum_name = f"AnimalModel{species}{disorder}Enum"

        entries = {}
        for animal in animals:
            formatted = format_enum_entry_enhanced(animal)
            entries.update(formatted)

        if entries:
            enums[enum_name] = {
                'description': f"Animal models: {species} + {disorder} ({count} entries)",
                'permissible_values': entries,
                '_metadata': {
                    'species': species,
                    'disorder': disorder,
                    'count': count,
                    'type': 'animal_model'
                }
            }

    # Print summary
    print(f"\nGenerated {len(enums)} filtered enum subsets:")
    for enum_name, data in sorted(enums.items(), key=lambda x: -x[1]['_metadata']['count']):
        meta = data['_metadata']
        count = meta['count']
        status = '✓' if count <= 100 else f'({count} >100)'
        print(f"  {enum_name}: {count} entries {status}")

    return enums


def save_filtered_enum_files(enums: Dict[str, Dict], output_dir: str = 'modules/Sample/generated'):
    """
    Save filtered enum files to disk.

    Args:
        enums: Dict of enum_name -> enum_data
        output_dir: Directory to save files
    """
    os.makedirs(output_dir, exist_ok=True)

    print(f"\nSaving filtered enum files to {output_dir}/...")

    for enum_name, enum_data in enums.items():
        # Remove metadata before saving
        meta = enum_data.pop('_metadata')

        # Create filename from enum name
        filename = f"{enum_name}.yaml"
        filepath = os.path.join(output_dir, filename)

        # Write file
        content = {
            'enums': {
                enum_name: {
                    'description': enum_data['description'],
                    'permissible_values': enum_data['permissible_values']
                }
            }
        }

        with open(filepath, 'w') as f:
            f.write(f"# Auto-generated filtered enum subset\n")
            f.write(f"# Type: {meta['type']}\n")
            f.write(f"# Count: {meta['count']} entries\n")
            if meta['type'] == 'cell_line':
                f.write(f"# Filters: species={meta['species']}, category={meta['category']}, disorder={meta['disorder']}\n")
            else:
                f.write(f"# Filters: species={meta['species']}, disorder={meta['disorder']}\n")
            f.write(f"\n")
            yaml.dump(content, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        print(f"  ✓ {filename}")


def generate_base_enums(cell_lines: List[Dict], animal_models: List[Dict]) -> Tuple[Dict, Dict]:
    """
    Generate base CellLineModel and AnimalModel enums for backward compatibility.

    Returns:
        Tuple of (cell_line_enum, animal_model_enum)
    """
    print("\nGenerating base enum files for backward compatibility...")

    # Cell lines
    cell_entries = {}
    for cell in cell_lines:
        formatted = format_enum_entry_enhanced(cell)
        cell_entries.update(formatted)

    cell_enum = {
        'CellLineModel': {
            'permissible_values': cell_entries
        }
    }

    # Animal models
    animal_entries = {}
    for animal in animal_models:
        formatted = format_enum_entry_enhanced(animal)
        animal_entries.update(formatted)

    animal_enum = {
        'AnimalModel': {
            'permissible_values': animal_entries
        }
    }

    print(f"  → CellLineModel: {len(cell_entries)} entries")
    print(f"  → AnimalModel: {len(animal_entries)} entries")

    return cell_enum, animal_enum


def save_base_enum_file(enum_data: Dict, filepath: str, enum_type: str):
    """Save base enum file with header."""
    with open(filepath, 'w') as f:
        f.write(f"# WARNING: This file is auto-generated from Synapse table syn51730943\n")
        f.write(f"# DO NOT EDIT DIRECTLY - changes will be overwritten\n")
        f.write(f"# For manual entries, use the corresponding *Manual.yaml file\n")
        f.write(f"# Generated by utils/sync_model_systems_enhanced.py\n")
        f.write(f"\n")
        # Wrap enum_data in proper structure with correct indentation
        content = {'enums': enum_data}
        yaml.dump(content, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"  ✓ Saved {filepath}")


def main():
    parser = argparse.ArgumentParser(description='Sync model systems with conditional filtering')
    parser.add_argument('--synapse-id', default='syn51730943',
                       help='Synapse table ID (default: syn51730943 - NF Tools Database)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')

    args = parser.parse_args()

    print("="*60)
    print("ENHANCED MODEL SYSTEM SYNC WITH CONDITIONAL FILTERING")
    print("="*60)
    print(f"Source: {args.synapse_id}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Fetch data
    cell_lines, animal_models, antibodies, genetic_reagents = fetch_model_system_data_with_metadata(args.synapse_id)

    # Generate filtered enum subsets
    filtered_enums = generate_filtered_enum_subsets(cell_lines, animal_models)

    # Generate base enums for backward compatibility
    cell_enum, animal_enum = generate_base_enums(cell_lines, animal_models)

    # Generate antibody and genetic reagent enums
    antibody_entries = {}
    for antibody in antibodies:
        formatted = format_enum_entry_enhanced(antibody)
        antibody_entries.update(formatted)

    antibody_enum = {
        'AntibodyEnum': {
            'permissible_values': antibody_entries
        }
    }

    reagent_entries = {}
    for reagent in genetic_reagents:
        formatted = format_enum_entry_enhanced(reagent)
        reagent_entries.update(formatted)

    reagent_enum = {
        'GeneticReagentEnum': {
            'permissible_values': reagent_entries
        }
    }

    if not args.dry_run:
        # Save filtered enums
        save_filtered_enum_files(filtered_enums)

        # Save base enums
        save_base_enum_file(cell_enum, 'modules/Sample/CellLineModel.yaml', 'cell_line')
        save_base_enum_file(animal_enum, 'modules/Sample/AnimalModel.yaml', 'animal_model')

        # Save antibody and genetic reagent enums
        save_base_enum_file(antibody_enum, 'modules/Experiment/Antibody.yaml', 'antibody')
        save_base_enum_file(reagent_enum, 'modules/Experiment/GeneticReagent.yaml', 'genetic_reagent')

        print("\n" + "="*60)
        print("SYNC COMPLETED SUCCESSFULLY")
        print("="*60)
        print(f"✓ Generated {len(filtered_enums)} filtered enum subsets")
        print(f"✓ Updated base enum files (CellLineModel.yaml, AnimalModel.yaml)")
        print(f"✓ Updated Antibody.yaml ({len(antibody_entries)} entries)")
        print(f"✓ Updated GeneticReagent.yaml ({len(reagent_entries)} entries)")
        print("\nNext steps:")
        print("  1. Rebuild data model: make NF.yaml")
        print("  2. Regenerate JSON schemas: python utils/gen-json-schema-class.py")
    else:
        print("\n" + "="*60)
        print("DRY RUN - NO FILES MODIFIED")
        print("="*60)
        print(f"Would generate {len(filtered_enums)} filtered enum subsets")
        print(f"Would update base enum files")
        print(f"Would update Antibody.yaml ({len(antibody_entries)} entries)")
        print(f"Would update GeneticReagent.yaml ({len(reagent_entries)} entries)")


if __name__ == '__main__':
    main()
