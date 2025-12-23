#!/usr/bin/env python3
"""
Scalable template generation with selective rule filtering.

This enhanced version generates LinkML templates with quality-based rule selection,
allowing the approach to scale to thousands of tools across multiple categories.

Usage:
    # Generate with all rules (current approach)
    python scripts/generate_template_scalable.py --template animal

    # Generate with selective filtering (scalable approach)
    python scripts/generate_template_scalable.py --template animal --max-rules 50

    # Generate multiple templates
    python scripts/generate_template_scalable.py --all --max-rules 100
"""

import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Tuple
import yaml


# Template configurations
TEMPLATE_CONFIGS = {
    'animal': {
        'class_name': 'AnimalIndividualTemplate',
        'mappings_file': 'animal_models_mappings.json',
        'description': 'Template for non-human individual-level data',
        'slots': [
            'specimenID', 'individualID', 'sex', 'age', 'ageUnit',
            'diagnosis', 'diagnosisAgeGroup', 'inheritance', 'mosaicism',
            'nf1Genotype', 'nf2Genotype', 'germlineMutation',
            'species', 'genotype', 'backgroundStrain', 'RRID',
            'modelSystemName', 'modelSystemType', 'geneticModification',
            'manifestation', 'institution', 'organism'
        ],
        'key_field': 'modelSystemName'
    },
    'cell_line': {
        'class_name': 'CellLineTemplate',
        'mappings_file': 'cell_lines_mappings.json',
        'description': 'Template for cell line metadata',
        'slots': [
            'specimenID', 'cellLineName', 'species', 'tissue', 'organ',
            'cellType', 'disease', 'RRID', 'institution', 'organism'
        ],
        'key_field': 'cellLineName'
    },
    'antibody': {
        'class_name': 'AntibodyTemplate',
        'mappings_file': 'antibodies_mappings.json',
        'description': 'Template for antibody metadata',
        'slots': [
            'antibodyName', 'targetProtein', 'hostOrganism',
            'reactiveSpecies', 'RRID', 'institution'
        ],
        'key_field': 'antibodyName'
    },
    'reagent': {
        'class_name': 'GeneticReagentTemplate',
        'mappings_file': 'genetic_reagents_mappings.json',
        'description': 'Template for genetic reagent metadata',
        'slots': [
            'reagentName', 'reagentType', 'targetGene',
            'insertSpecies', 'RRID', 'institution'
        ],
        'key_field': 'reagentName'
    }
}


def calculate_quality_score(data: Dict[str, Any]) -> int:
    """
    Calculate quality score for a tool entry.

    Scoring criteria:
    - RRID present: +20 points
    - Description present: +10 points
    - Institution present: +5 points
    - Each other populated field: +1 point
    """
    score = 0

    # High-value fields
    if data.get('RRID'):
        score += 20
    if data.get('description'):
        score += 10
    if data.get('institution'):
        score += 5

    # Count all populated fields
    field_count = sum(1 for v in data.values() if v)
    score += field_count

    return score


def rank_tools_by_quality(tools: Dict[str, Dict[str, Any]]) -> List[Tuple[int, str, Dict]]:
    """
    Rank tools by quality score.

    Returns:
        List of (score, name, data) tuples, sorted by score descending
    """
    scored = []
    for name, data in tools.items():
        score = calculate_quality_score(data)
        scored.append((score, name, data))

    return sorted(scored, reverse=True)


def select_tools_for_rules(
    tools: Dict[str, Dict[str, Any]],
    max_rules: int = None,
    require_rrid: bool = False,
    min_fields: int = 5
) -> List[Tuple[str, Dict]]:
    """
    Select tools for rule generation based on quality criteria.

    Args:
        tools: All available tools
        max_rules: Maximum number of rules to generate (None = all)
        require_rrid: Only generate rules for tools with RRID
        min_fields: Minimum metadata fields required

    Returns:
        List of (name, data) tuples for selected tools
    """
    # Rank by quality
    ranked = rank_tools_by_quality(tools)

    # Apply filters
    selected = []
    for score, name, data in ranked:
        # RRID filter
        if require_rrid and not data.get('RRID'):
            continue

        # Minimum fields filter
        field_count = sum(1 for v in data.values() if v)
        if field_count < min_fields:
            continue

        selected.append((name, data))

        # Max rules limit
        if max_rules and len(selected) >= max_rules:
            break

    return selected


def create_rule_for_tool(
    tool_name: str,
    tool_data: Dict[str, Any],
    key_field: str
) -> Dict[str, Any]:
    """Create a LinkML rule for a single tool."""
    # Define fields to auto-fill
    autofill_fields = [
        'species', 'organism', 'genotype', 'backgroundStrain', 'RRID',
        'modelSystemType', 'geneticModification', 'manifestation',
        'institution', 'description', 'tissue', 'organ', 'cellType',
        'disease', 'targetProtein', 'hostOrganism', 'reactiveSpecies',
        'reagentType', 'targetGene', 'insertSpecies'
    ]

    # Build postconditions
    postconditions = {}
    for field in autofill_fields:
        if field in tool_data and tool_data[field]:
            postconditions[field] = {
                "equals_string": str(tool_data[field])
            }

    if not postconditions:
        return None

    rule = {
        "preconditions": {
            "slot_conditions": {
                key_field: {
                    "any_of": [
                        {"equals_string": tool_name}
                    ]
                }
            }
        },
        "postconditions": {
            "slot_conditions": postconditions
        },
        "description": f"Auto-fill info for {tool_name}"
    }

    return rule


def generate_template(
    config: Dict[str, Any],
    all_tools: Dict[str, Dict[str, Any]],
    selected_tools: List[Tuple[str, Dict]],
    output_path: Path
):
    """Generate LinkML template with rules."""

    # Create rules
    rules = []
    for tool_name, tool_data in selected_tools:
        rule = create_rule_for_tool(tool_name, tool_data, config['key_field'])
        if rule:
            rules.append(rule)

    # Build template
    template = {
        "classes": {
            config['class_name']: {
                "description": f"{config['description']} with auto-fill rules based on tool selection. "
                               f"Rules are auto-generated from the NF research tools database.",
                "annotations": {
                    "required": False,
                    "requiresComponent": ""
                },
                "slots": config['slots'],
                "rules": rules
            }
        }
    }

    # Write YAML
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        # Header comments
        f.write(f"# Auto-generated {config['class_name']} with LinkML rules\n")
        f.write("# DO NOT EDIT MANUALLY - Generated from NF research tools database\n")
        f.write(f"# Total tools in database: {len(all_tools)}\n")
        f.write(f"# Tools with rules: {len(selected_tools)}\n")
        f.write(f"# Rules generated: {len(rules)}\n")
        f.write(f"# Coverage: {len(rules)/len(all_tools)*100:.1f}%\n\n")

        # YAML content
        yaml.dump(
            template,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120
        )


def print_statistics(
    template_name: str,
    all_tools: Dict,
    selected_tools: List,
    rules_generated: int
):
    """Print generation statistics."""
    print(f"\n{'='*70}")
    print(f"Template: {template_name}")
    print(f"{'='*70}")
    print(f"Total tools in database:  {len(all_tools)}")
    print(f"Tools selected for rules: {len(selected_tools)}")
    print(f"Rules generated:          {rules_generated}")
    print(f"Coverage:                 {rules_generated/len(all_tools)*100:.1f}%")

    # Show quality distribution
    if selected_tools:
        scores = [calculate_quality_score(data) for _, data in selected_tools]
        print(f"\nQuality scores of selected tools:")
        print(f"  Min:    {min(scores)}")
        print(f"  Max:    {max(scores)}")
        print(f"  Median: {sorted(scores)[len(scores)//2]}")

    # Show which tools have RRIDs
    with_rrid = sum(1 for _, data in selected_tools if data.get('RRID'))
    print(f"\nTools with RRID: {with_rrid}/{len(selected_tools)} ({with_rrid/len(selected_tools)*100:.1f}%)")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate scalable LinkML templates with selective rules"
    )
    parser.add_argument(
        '--template',
        choices=['animal', 'cell_line', 'antibody', 'reagent'],
        help='Template to generate'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Generate all templates'
    )
    parser.add_argument(
        '--max-rules',
        type=int,
        default=None,
        help='Maximum number of rules to generate (default: unlimited)'
    )
    parser.add_argument(
        '--require-rrid',
        action='store_true',
        help='Only generate rules for tools with RRID'
    )
    parser.add_argument(
        '--min-fields',
        type=int,
        default=5,
        help='Minimum metadata fields required (default: 5)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('modules/Template'),
        help='Output directory for templates'
    )

    args = parser.parse_args()

    # Determine which templates to generate
    if args.all:
        templates = list(TEMPLATE_CONFIGS.keys())
    elif args.template:
        templates = [args.template]
    else:
        parser.error("Must specify --template or --all")

    # Repository root
    repo_root = Path(__file__).parent.parent
    mappings_dir = repo_root / "auto-generated" / "mappings"

    print("="*70)
    print("Scalable LinkML Template Generator")
    print("="*70)
    print(f"Max rules per template: {args.max_rules or 'unlimited'}")
    print(f"Require RRID: {args.require_rrid}")
    print(f"Min fields: {args.min_fields}")
    print(f"Templates: {', '.join(templates)}")

    # Generate each template
    for template_name in templates:
        config = TEMPLATE_CONFIGS[template_name]

        # Load mappings
        mappings_path = mappings_dir / config['mappings_file']
        if not mappings_path.exists():
            print(f"\n⚠️  Skipping {template_name}: {mappings_path} not found")
            continue

        with open(mappings_path, 'r') as f:
            all_tools = json.load(f)

        # Select tools for rules
        selected_tools = select_tools_for_rules(
            all_tools,
            max_rules=args.max_rules,
            require_rrid=args.require_rrid,
            min_fields=args.min_fields
        )

        # Generate template
        output_path = args.output_dir / f"{config['class_name']}.yaml"
        generate_template(config, all_tools, selected_tools, output_path)

        # Print statistics
        print_statistics(
            config['class_name'],
            all_tools,
            selected_tools,
            len(selected_tools)
        )

        print(f"\n✅ Generated: {output_path}")

    print("\n" + "="*70)
    print("✅ Generation complete!")
    print("="*70)

    print("\n📝 Next steps:")
    print("   1. Review generated templates")
    print("   2. Run tests: python scripts/test_linkml_rules.py")
    print("   3. Build schema: make NF.yaml")
    print("   4. Generate JSON: python utils/gen-json-schema-class.py")

    return 0


if __name__ == "__main__":
    exit(main())
