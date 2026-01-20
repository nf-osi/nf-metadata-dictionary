#!/usr/bin/env python3
"""
Fetch species information for model systems from external APIs.

This script queries:
- Cellosaurus API for cell line species (CVCL_ RRIDs)
- Jackson Laboratory / MGI for animal model species (IMSR_JAX, MGI, MMRRC RRIDs)
"""

import requests
import time
import yaml
from typing import Dict, Optional
import re


def fetch_cellosaurus_species(cvcl_id: str) -> Optional[str]:
    """
    Fetch species from Cellosaurus API for a given CVCL ID.

    Args:
        cvcl_id: Cellosaurus ID (e.g., "CVCL_0023" for HEK293)

    Returns:
        Species name (e.g., "Homo sapiens") or None if not found
    """
    # Clean the ID (remove "rrid:" prefix if present)
    cvcl_id = cvcl_id.replace('rrid:', '').replace('CVCL_', 'CVCL-')

    url = f"https://api.cellosaurus.org/cell-line/{cvcl_id}"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # Species is in the "species" field
            species_data = data.get('species', {})
            if isinstance(species_data, dict):
                species_name = species_data.get('name')
                return species_name
            elif isinstance(species_data, list) and len(species_data) > 0:
                # Sometimes it's a list
                return species_data[0].get('name')
        return None
    except Exception as e:
        print(f"  Error fetching {cvcl_id}: {e}")
        return None


def infer_animal_model_species(name: str, rrid: str = None, description: str = None) -> Optional[str]:
    """
    Infer species for animal models from name, RRID, or description.

    Most animal models in NF research are mouse models.
    This function uses heuristics to determine species.

    Args:
        name: Model system name
        rrid: RRID if available
        description: Description if available

    Returns:
        Species name or None
    """
    # Check RRID prefixes
    if rrid:
        rrid_lower = rrid.lower()
        if 'imsr_jax' in rrid_lower or 'mmrrc' in rrid_lower or 'mgi:' in rrid_lower:
            return "Mus musculus"  # Jackson Lab and MMRRC are mouse repositories
        if 'rgd:' in rrid_lower:
            return "Rattus norvegicus"  # Rat Genome Database

    # Check name patterns
    name_lower = name.lower()

    # Mouse indicators
    mouse_indicators = ['b6', 'c57', 'nf1', 'balb/', 'fvb', '129', 'cre', 'flox',
                       'mus musculus', 'mouse', 'knockout', 'transgenic']
    if any(ind in name_lower for ind in mouse_indicators):
        return "Mus musculus"

    # Zebrafish indicators
    zebrafish_indicators = ['zebrafish', 'nf1a', 'nf1b', 'danio']
    if any(ind in name_lower for ind in zebrafish_indicators):
        return "Danio rerio"

    # Drosophila indicators
    fly_indicators = ['drosophila', 'dnf1', 'nf1e1', 'nf1p1']
    if any(ind in name_lower for ind in fly_indicators):
        return "Drosophila melanogaster"

    # Rat indicators
    rat_indicators = ['rattus', 'rat']
    if any(ind in name_lower for ind in rat_indicators):
        return "Rattus norvegicus"

    # Pig indicators
    pig_indicators = ['minipig', 'sus scrofa', 'pig', 'swine']
    if any(ind in name_lower for ind in pig_indicators):
        return "Sus scrofa"

    # Check description if available
    if description:
        desc_lower = description.lower()
        if 'mouse' in desc_lower or 'murine' in desc_lower:
            return "Mus musculus"
        if 'human' in desc_lower:
            return "Homo sapiens"

    # Default for unidentified: assume mouse (most common in NF research)
    return None


def fetch_all_species_info() -> Dict[str, Dict]:
    """
    Fetch species information for all model systems.

    Returns:
        Dict mapping model system name to metadata including species
    """
    # Load existing model system data
    with open('modules/Sample/CellLineModel.yaml') as f:
        cell_data = yaml.safe_load(f)

    with open('modules/Sample/AnimalModel.yaml') as f:
        animal_data = yaml.safe_load(f)

    cell_lines = cell_data['enums']['CellLineModel']['permissible_values']
    animal_models = animal_data['enums']['AnimalModel']['permissible_values']

    results = {}

    # Process cell lines
    print(f"Processing {len(cell_lines)} cell lines...")
    for i, (name, meta) in enumerate(cell_lines.items()):
        if i > 0 and i % 50 == 0:
            print(f"  Processed {i}/{len(cell_lines)} cell lines...")
            time.sleep(1)  # Rate limiting

        species = None
        rrid = meta.get('meaning', '')

        if 'CVCL' in rrid or 'cvcl' in rrid.lower():
            # Query Cellosaurus
            species = fetch_cellosaurus_species(rrid)
            if species:
                print(f"  {name}: {species} (from Cellosaurus)")

        # Fallback to inference
        if not species:
            # Try to infer from name
            if any(pattern in name.upper() for pattern in ['GM', 'HEK', 'HeLa', 'MCF', 'SK-MEL', 'MPNST', 'iPSC', 'hiPSC']):
                species = "Homo sapiens"
            elif 'ES cell' in name or 'MEF' in name:
                species = "Mus musculus"

        results[name] = {
            **meta,
            'species': species,
            'system_type': 'cell line'
        }

    # Process animal models
    print(f"\nProcessing {len(animal_models)} animal models...")
    for name, meta in animal_models.items():
        rrid = meta.get('meaning', '')
        description = meta.get('description', '')
        species = infer_animal_model_species(name, rrid, description)

        results[name] = {
            **meta,
            'species': species,
            'system_type': 'animal model'
        }

    return results


def generate_species_filtered_enums(species_data: Dict[str, Dict]):
    """
    Generate species-filtered enum files.

    Creates separate enum files for each combination of:
    - system_type (cell line vs animal model)
    - species
    """
    # Group by system_type and species
    grouped = {}
    for name, data in species_data.items():
        system_type = data.get('system_type', 'unknown')
        species = data.get('species', 'Unknown')

        if species is None:
            species = 'Unknown'

        key = (system_type, species)
        if key not in grouped:
            grouped[key] = {}
        grouped[key][name] = {k: v for k, v in data.items() if k not in ['species', 'system_type']}

    # Print summary
    print("\n" + "="*60)
    print("SPECIES DISTRIBUTION")
    print("="*60)
    for (system_type, species), items in sorted(grouped.items(), key=lambda x: -len(x[1])):
        print(f"{system_type} + {species}: {len(items)} entries")

    # Save filtered files
    print("\n" + "="*60)
    print("SAVING SPECIES-FILTERED ENUM FILES")
    print("="*60)

    output_dir = 'modules/Sample/generated/'
    import os
    os.makedirs(output_dir, exist_ok=True)

    for (system_type, species), items in grouped.items():
        # Create safe filename
        type_name = system_type.replace(' ', '')
        species_name = species.replace(' ', '').replace('.', '')
        filename = f"{type_name}_{species_name}.yaml"
        enum_name = f"{type_name.capitalize()}{species_name}Enum"

        filepath = os.path.join(output_dir, filename)

        content = f"""# Auto-generated species-filtered model system enum
# System type: {system_type}
# Species: {species}
# Count: {len(items)} entries

enums:
  {enum_name}:
    permissible_values:
"""

        for name, meta in sorted(items.items()):
            content += f'      "{name}":\n'
            for key, value in meta.items():
                if isinstance(value, str) and len(value) > 200:
                    value = value[:200] + "..."
                content += f'        {key}: {repr(value)}\n'

        with open(filepath, 'w') as f:
            f.write(content)

        print(f"  Created: {filepath} ({len(items)} entries)")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Fetch species info for model systems')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--cache', default='species_cache.yaml', help='Cache file for species data')

    args = parser.parse_args()

    # Check if cache exists
    import os
    if os.path.exists(args.cache):
        print(f"Loading species data from cache: {args.cache}")
        with open(args.cache) as f:
            species_data = yaml.safe_load(f)
    else:
        print("Fetching species data from APIs...")
        species_data = fetch_all_species_info()

        # Save cache
        with open(args.cache, 'w') as f:
            yaml.dump(species_data, f, default_flow_style=False, sort_keys=False)
        print(f"Saved species data to cache: {args.cache}")

    # Generate filtered enums
    generate_species_filtered_enums(species_data)

    print("\nDone!")
