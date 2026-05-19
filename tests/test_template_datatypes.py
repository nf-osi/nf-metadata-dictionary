"""Tests that ensure template classes declare dataType coverage via annotations."""

from pathlib import Path
import re
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "modules" / "Template"
DATA_ENUM_DIR = REPO_ROOT / "modules" / "Data"
DATA_BASE_FILE = DATA_ENUM_DIR / "Data.yaml"
OPTIONAL_DATATYPE_TEMPLATES = {
    "AnimalIndividualTemplate",
    "PortalDataset",
    "PortalStudy",
    "PortalPublication",
    "PublicationTemplate",
    "DataLandscape",
}
DATA_FILE = REPO_ROOT / "modules" / "Data" / "Data.yaml"


def _load_valid_data_types():
    """Return the set of permissible values for Data + Metadata enums."""
    values = set()
    for yaml_path in sorted(DATA_ENUM_DIR.glob("Data*.yaml")):
        parsed = yaml.safe_load(yaml_path.read_text()) or {}
        enums = parsed.get("enums") or {}
        data_enum = enums.get("Data") or {}
        pv = data_enum.get("permissible_values") or {}
        values.update(pv.keys())
    base = yaml.safe_load(DATA_BASE_FILE.read_text())
    values.update(base["enums"]["MetadataEnum"]["permissible_values"].keys())
    return values


def _iter_template_classes():
    """Yield (path, class_name, class_config) for each template class."""
    for yaml_path in sorted(TEMPLATE_DIR.rglob("*.yaml")):
        parsed = yaml.safe_load(yaml_path.read_text())
        classes = parsed.get("classes") or {}
        for name, config in classes.items():
            yield yaml_path, name, config


def test_templates_have_datatype_annotations():
    """All non-abstract template classes should map to at least one dataType."""
    valid_values = _load_valid_data_types()
    missing = []
    invalid = []

    for path, name, config in _iter_template_classes():
        if config.get("abstract"):
            continue
        annotations = config.get("annotations") or {}
        template_for = annotations.get("templateFor") or {}
        data_types = template_for.get("dataType")
        if not data_types:
            if name in OPTIONAL_DATATYPE_TEMPLATES:
                continue
            missing.append((path, name))
            continue
        for value in data_types:
            if value not in valid_values:
                invalid.append((path, name, value))

    assert not missing, (
        "Missing dataType annotation for templates: "
        + ", ".join(f"{name} ({path})" for path, name in missing)
    )
    assert not invalid, (
        "Templates reference undefined dataType values: "
        + ", ".join(
            f"{name} -> {value} ({path})" for path, name, value in invalid
        )
    )


def test_template_datatype_defaults_are_valid():
    """If templates supply default dataType values, ensure they are valid enums."""
    valid_values = _load_valid_data_types()
    bad_defaults = []
    pattern = re.compile(r"^string\((.+)\)$")

    for path, name, config in _iter_template_classes():
        slot_usage = config.get("slot_usage") or {}
        data_usage = slot_usage.get("dataType") or {}
        if "ifabsent" not in data_usage:
            continue
        raw_value = data_usage["ifabsent"]
        match = pattern.match(raw_value)
        value = match.group(1) if match else raw_value
        if value not in valid_values:
            bad_defaults.append((path, name, value))

    assert not bad_defaults, (
        "Templates have invalid dataType defaults: "
        + ", ".join(
            f"{name} -> {value} ({path})" for path, name, value in bad_defaults
        )
    )
