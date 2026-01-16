#!/usr/bin/env python3
"""
Generate a table of FileBasedTemplate subclasses and their relationships
to dataType, assay, and dataGranularity.

Output: docs/template-mapping.md
"""

import yaml
from pathlib import Path
from collections import defaultdict


def load_yaml_files(modules_dir: Path) -> dict:
    """Load and merge all YAML files from modules directory."""
    merged = {"classes": {}, "enums": {}, "slots": {}}

    for yaml_file in modules_dir.rglob("*.yaml"):
        with open(yaml_file) as f:
            try:
                data = yaml.safe_load(f)
                if data:
                    for key in merged:
                        if key in data:
                            merged[key].update(data[key])
            except yaml.YAMLError as e:
                print(f"Error parsing {yaml_file}: {e}")

    return merged


def get_all_subclasses(classes: dict, base_class: str) -> set:
    """Recursively find all subclasses of a base class."""
    subclasses = set()

    for class_name, class_def in classes.items():
        if class_def and class_def.get("is_a") == base_class:
            subclasses.add(class_name)
            subclasses.update(get_all_subclasses(classes, class_name))

    return subclasses


def extract_template_info(classes: dict, template_name: str) -> dict:
    """Extract dataType, assay, and dataGranularity from a template."""
    template = classes.get(template_name, {})
    if not template:
        return {}

    annotations = template.get("annotations", {})
    template_for = annotations.get("templateFor", {})

    info = {
        "name": template_name,
        "description": template.get("description", "").split(".")[0] if template.get("description") else "",
        "is_a": template.get("is_a", ""),
        "abstract": template.get("abstract", False),
        "dataTypes": template_for.get("dataType", []) if isinstance(template_for, dict) else [],
        "assays": template_for.get("assay", []) if isinstance(template_for, dict) else [],
        "dataGranularity": annotations.get("dataGranularity", ""),
    }

    return info


def generate_markdown_table(templates_info: list) -> str:
    """Generate markdown documentation."""
    lines = [
        "# Data Template Mapping",
        "",
        "This maps FileBasedTemplate subclasses to their most supported dataTypes and assays.",
        "",
        "",
        "| Template | Parent | Data Types | Assays |",
        "|----------|--------|------------|--------|",
    ]

    # Filter out abstract templates and sort by name
    concrete_templates = [t for t in templates_info if not t["abstract"]]
    sorted_templates = sorted(concrete_templates, key=lambda x: x["name"])

    for t in sorted_templates:
        data_types = ", ".join(sorted(t["dataTypes"])) if t["dataTypes"] else ""
        assays = ", ".join(sorted(t["assays"])) if t["assays"] else ""
        lines.append(f"| {t['name']} | {t['is_a']} | {data_types} | {assays} |")

    lines.append("")
    return "\n".join(lines)


def main():
    repo_root = Path(__file__).parent.parent
    modules_dir = repo_root / "modules"
    docs_dir = repo_root / "docs"

    print("Loading YAML files...")
    data = load_yaml_files(modules_dir)

    print("Finding FileBasedTemplate subclasses...")
    file_based_templates = get_all_subclasses(data["classes"], "FileBasedTemplate")
    file_based_templates.add("FileBasedTemplate")

    print(f"Found {len(file_based_templates)} templates")

    print("Extracting template information...")
    templates_info = []
    for template_name in file_based_templates:
        info = extract_template_info(data["classes"], template_name)
        if info:
            templates_info.append(info)

    print("Generating markdown...")
    markdown = generate_markdown_table(templates_info)

    output_file = docs_dir / "template-mapping.md"
    docs_dir.mkdir(exist_ok=True)

    with open(output_file, "w") as f:
        f.write(markdown)

    print(f"Written to {output_file}")


if __name__ == "__main__":
    main()
