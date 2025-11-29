#!/usr/bin/env python3
"""
Compare two Turtle RDF files and report the differences in entities.
"""

from rdflib import Graph, Namespace, RDF, DCTERMS
import sys
import argparse

# Define namespaces
LINKML = Namespace("https://w3id.org/linkml/")
DCTERMS = Namespace("http://purl.org/dc/terms/")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
SYNAPSE = Namespace("https://w3id.org/synapse/nfosi/vocab/")

def load_graph(filepath, format="turtle"):
    """Load an RDF file into a graph."""
    g = Graph()
    g.parse(filepath, format=format)
    return g

def get_entities(graph):
    """Get all unique subjects (entities) from a graph."""
    return set(graph.subjects())

def get_blank_node_properties(graph, subject):
    """Get all properties of a blank node."""
    properties = {}
    for p, o in graph.predicate_objects(subject):
        prop_name = str(p).split('/')[-1]  # Get the last part of the URI
        if prop_name not in properties:
            properties[prop_name] = []
        properties[prop_name].append(str(o))
    return properties

def get_anonymous_slot_signature(graph, anon_expr):
    """Get a signature for an anonymous slot expression based on its properties."""
    # Get all properties that define this anonymous expression
    sig_parts = []

    # Get range
    for o in graph.objects(anon_expr, LINKML.range):
        sig_parts.append(('range', str(o)))

    # Get other relevant properties that might differentiate expressions
    for o in graph.objects(anon_expr, LINKML.slot_uri):
        sig_parts.append(('slot_uri', str(o)))

    # Sort for consistency
    sig_parts.sort()
    return tuple(sig_parts)

def get_slot_anonymous_expressions(graph, slot):
    """Get all anonymous slot expressions for a slot with their signatures."""
    expressions = {}
    for anon_expr in graph.objects(slot, LINKML.any_of):
        sig = get_anonymous_slot_signature(graph, anon_expr)
        if sig not in expressions:
            expressions[sig] = []
        expressions[sig].append(anon_expr)
    return expressions

def get_templates(graph):
    """Get all templates (transitive subclasses of Template using linkml:is_a)."""
    templates = set()
    template_class = SYNAPSE.Template

    # Recursively find all subclasses using is_a (transitive closure)
    def find_subclasses(parent):
        for subclass in graph.subjects(LINKML.is_a, parent):
            if subclass not in templates:
                templates.add(subclass)
                # Recursively find subclasses of this subclass
                find_subclasses(subclass)

    # Start from Template and find all descendants
    find_subclasses(template_class)

    return templates

def get_template_properties(graph, template):
    """Get all properties (triples) associated with a template."""
    properties = set()
    for p, o in graph.predicate_objects(template):
        properties.add((p, o))
    return properties

def compare_templates(g_main, g_current):
    """Compare templates between main and current branches."""
    templates_main = get_templates(g_main)
    templates_current = get_templates(g_current)

    added_templates = templates_current - templates_main
    removed_templates = templates_main - templates_current
    common_templates = templates_main & templates_current

    # Check for modified templates (same template, different properties)
    modified_templates = []
    for template in common_templates:
        props_main = get_template_properties(g_main, template)
        props_current = get_template_properties(g_current, template)

        if props_main != props_current:
            modified_templates.append({
                'template': template,
                'added_props': props_current - props_main,
                'removed_props': props_main - props_current
            })

    return {
        'added': added_templates,
        'removed': removed_templates,
        'modified': modified_templates
    }

def get_range_changes(g_main, g_current):
    """Find slots where linkml:range has semantically changed."""
    range_changes = []

    # Get all slots (subjects) that have any_of in either graph
    slots_with_any_of = set()
    for s, p, o in g_main.triples((None, LINKML.any_of, None)):
        slots_with_any_of.add(s)
    for s, p, o in g_current.triples((None, LINKML.any_of, None)):
        slots_with_any_of.add(s)

    # Compare anonymous expressions for each slot by signature
    for slot in slots_with_any_of:
        main_exprs = get_slot_anonymous_expressions(g_main, slot)
        current_exprs = get_slot_anonymous_expressions(g_current, slot)

        main_sigs = set(main_exprs.keys())
        current_sigs = set(current_exprs.keys())

        # Check if there are semantic differences
        added_sigs = current_sigs - main_sigs
        removed_sigs = main_sigs - current_sigs

        if added_sigs or removed_sigs:
            range_changes.append({
                'slot': slot,
                'added': added_sigs,
                'removed': removed_sigs
            })

    # Also check for direct range changes (non-anonymous)
    subjects_with_direct_range = set()
    for s, p, o in g_main.triples((None, LINKML.range, None)):
        # Skip if this is part of any_of
        is_anonymous = False
        for _ in g_main.subjects(LINKML.any_of, s):
            is_anonymous = True
            break
        if not is_anonymous:
            subjects_with_direct_range.add(s)

    for s, p, o in g_current.triples((None, LINKML.range, None)):
        # Skip if this is part of any_of
        is_anonymous = False
        for _ in g_current.subjects(LINKML.any_of, s):
            is_anonymous = True
            break
        if not is_anonymous:
            subjects_with_direct_range.add(s)

    # Compare direct ranges
    for subject in subjects_with_direct_range:
        ranges_main = set(g_main.objects(subject, LINKML.range))
        ranges_current = set(g_current.objects(subject, LINKML.range))

        if ranges_main != ranges_current:
            range_changes.append({
                'slot': subject,
                'main_ranges': ranges_main,
                'current_ranges': ranges_current,
                'direct': True
            })

    return range_changes

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Compare two Turtle RDF files and report differences')
    parser.add_argument('--show-range-details', action='store_true',
                        help='Show detailed information for all range changes (default: summary only)')
    args = parser.parse_args()

    # Load both graphs
    print("Loading graphs...")
    g_main = load_graph("dist/NF_main.ttl")
    g_current = load_graph("dist/NF.ttl")

    # Get entities
    entities_main = get_entities(g_main)
    entities_current = get_entities(g_current)

    # Categorize entities by type
    def categorize_entities(graph, entities):
        classes = set()
        slots = set()
        enums = set()
        anonymous = set()
        other = set()

        for entity in entities:
            # Check for ClassDefinition
            if (entity, RDF.type, LINKML.ClassDefinition) in graph:
                classes.add(entity)
            # Check for SlotDefinition
            elif (entity, RDF.type, LINKML.SlotDefinition) in graph:
                slots.add(entity)
            # Check for AnonymousSlotExpression
            elif (entity, RDF.type, LINKML.AnonymousSlotExpression) in graph:
                anonymous.add(entity)
            # Check for permissible_values (enums)
            elif list(graph.objects(entity, LINKML.permissible_values)):
                enums.add(entity)
            else:
                other.add(entity)

        return {
            'classes': classes,
            'slots': slots,
            'enums': enums,
            'anonymous': anonymous,
            'other': other
        }

    main_categories = categorize_entities(g_main, entities_main)
    current_categories = categorize_entities(g_current, entities_current)

    # Compare counts
    print(f"\n=== Entity Counts ===")
    print(f"Main branch:    {len(entities_main)} entities")
    print(f"  Classes:      {len(main_categories['classes'])}")
    print(f"  Slots:        {len(main_categories['slots'])}")
    print(f"  Enums:        {len(main_categories['enums'])}")
    print(f"  Anonymous:    {len(main_categories['anonymous'])}")
    print(f"  Other:        {len(main_categories['other'])}")

    print(f"\nCurrent branch: {len(entities_current)} entities")
    print(f"  Classes:      {len(current_categories['classes'])}")
    print(f"  Slots:        {len(current_categories['slots'])}")
    print(f"  Enums:        {len(current_categories['enums'])}")
    print(f"  Anonymous:    {len(current_categories['anonymous'])}")
    print(f"  Other:        {len(current_categories['other'])}")

    print(f"\nDifference:     {len(entities_current) - len(entities_main):+d} entities")

    # Find differences by category
    for cat_name, cat_label in [
        ('classes', 'Classes'),
        ('slots', 'Slots'),
        ('enums', 'Enums')
    ]:
        added = current_categories[cat_name] - main_categories[cat_name]
        removed = main_categories[cat_name] - current_categories[cat_name]

        if added or removed:
            print(f"\n=== {cat_label} ===")
            if added:
                print(f"Added ({len(added)}):")
                for entity in sorted(added):
                    entity_name = str(entity).split('/')[-1]
                    title = g_current.value(entity, DCTERMS.title)
                    if title:
                        print(f"  + {entity_name} ({title})")
                    else:
                        print(f"  + {entity_name}")

            if removed:
                print(f"Removed ({len(removed)}):")
                for entity in sorted(removed):
                    entity_name = str(entity).split('/')[-1]
                    title = g_main.value(entity, DCTERMS.title)
                    if title:
                        print(f"  - {entity_name} ({title})")
                    else:
                        print(f"  - {entity_name}")

    # Compare triple counts
    print(f"\n=== Triple Counts ===")
    print(f"Main branch:    {len(g_main)} triples")
    print(f"Current branch: {len(g_current)} triples")
    print(f"Difference:     {len(g_current) - len(g_main):+d} triples")

    # Find triple differences
    triples_only_current = g_current - g_main
    triples_only_main = g_main - g_current

    if len(triples_only_current) > 0:
        print(f"\n=== New triples in current branch ({len(triples_only_current)}) ===")
        if len(triples_only_current) <= 20:
            for s, p, o in sorted(triples_only_current):
                print(f"  + {s} {p} {o}")
        else:
            print(f"  (Too many to display - {len(triples_only_current)} new triples)")

    if len(triples_only_main) > 0:
        print(f"\n=== Triples removed from main branch ({len(triples_only_main)}) ===")
        if len(triples_only_main) <= 20:
            for s, p, o in sorted(triples_only_main):
                print(f"  - {s} {p} {o}")
        else:
            print(f"  (Too many to display - {len(triples_only_main)} removed triples)")

    # Analyze template changes
    print("\n=== Template Changes ===")
    template_changes = compare_templates(g_main, g_current)

    # Get total template counts for summary
    templates_main = get_templates(g_main)
    templates_current = get_templates(g_current)
    total_templates = len(templates_current)
    modified_count = len(template_changes['modified'])
    added_count = len(template_changes['added'])
    removed_count = len(template_changes['removed'])

    # Print summary
    print(f"Modified: {modified_count}/{total_templates} templates")
    if added_count > 0:
        print(f"Added: {added_count} templates")
    if removed_count > 0:
        print(f"Removed: {removed_count} templates")

    if template_changes['added'] or template_changes['removed'] or template_changes['modified']:
        if template_changes['added']:
            print(f"\nAdded templates ({len(template_changes['added'])}):")
            for template in sorted(template_changes['added']):
                template_name = str(template).split('/')[-1]
                title = g_current.value(template, DCTERMS.title)
                if title:
                    print(f"  + {template_name} ({title})")
                else:
                    print(f"  + {template_name}")

        if template_changes['removed']:
            print(f"\nRemoved templates ({len(template_changes['removed'])}):")
            for template in sorted(template_changes['removed']):
                template_name = str(template).split('/')[-1]
                title = g_main.value(template, DCTERMS.title)
                if title:
                    print(f"  - {template_name} ({title})")
                else:
                    print(f"  - {template_name}")

        if template_changes['modified']:
            print(f"\nModified templates ({len(template_changes['modified'])}):")
            for change in sorted(template_changes['modified'], key=lambda x: str(x['template'])):
                template = change['template']
                template_name = str(template).split('/')[-1]
                title = g_current.value(template, DCTERMS.title)
                if title:
                    print(f"  * {template_name} ({title})")
                else:
                    print(f"  * {template_name}")

                added_props = change['added_props']
                removed_props = change['removed_props']

                if added_props:
                    print(f"    Added {len(added_props)} properties")
                if removed_props:
                    print(f"    Removed {len(removed_props)} properties")
    else:
        print("No template changes detected.")

    # Analyze range changes
    print("\n=== Analyzing linkml:range changes ===")
    range_changes = get_range_changes(g_main, g_current)

    if range_changes:
        print(f"Found {len(range_changes)} slots with semantic range changes")

        if args.show_range_details:
            print()
            for change in sorted(range_changes, key=lambda x: str(x['slot'])):
                slot = change['slot']

                # Get slot name and title
                slot_name = str(slot).split('/')[-1]
                slot_title = g_current.value(slot, DCTERMS.title)
                if not slot_title:
                    slot_title = g_main.value(slot, DCTERMS.title)

                print(f"Slot: {slot_name}", end='')
                if slot_title:
                    print(f" ({slot_title})")
                else:
                    print()

                # Handle direct range changes
                if change.get('direct'):
                    removed = change.get('main_ranges', set()) - change.get('current_ranges', set())
                    added = change.get('current_ranges', set()) - change.get('main_ranges', set())

                    if removed:
                        for r in sorted(removed):
                            range_name = str(r).split('/')[-1]
                            print(f"  - Removed: {range_name}")
                    if added:
                        for r in sorted(added):
                            range_name = str(r).split('/')[-1]
                            print(f"  + Added: {range_name}")
                else:
                    # Handle contextual range changes
                    removed_sigs = change.get('removed', set())
                    added_sigs = change.get('added', set())

                    if removed_sigs:
                        print(f"  Removed contextual ranges:")
                        for sig in sorted(removed_sigs):
                            for prop, val in sig:
                                if prop == 'range':
                                    range_name = val.split('/')[-1]
                                    print(f"    - {range_name}")

                    if added_sigs:
                        print(f"  Added contextual ranges:")
                        for sig in sorted(added_sigs):
                            for prop, val in sig:
                                if prop == 'range':
                                    range_name = val.split('/')[-1]
                                    print(f"    + {range_name}")

                print()
        else:
            print("(Use --show-range-details to see all affected slots)")
    else:
        print("No semantic range changes detected.")

if __name__ == "__main__":
    main()
