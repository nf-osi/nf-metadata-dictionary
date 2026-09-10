#!/usr/bin/env python3
"""
Guard the label-identity contract between the portal-level ManifestationEnum and the
file-level Tumor enum.

File-level tumorType annotations are rolled up onto dataset- and study-level
manifestation to populate the portal's facet search. That rollup has no vocabulary
crosswalk, so it only works if the two enums spell shared concepts identically. LinkML
cannot express the subset relation, so the value list is duplicated by hand and this
test is what keeps the two copies in agreement.

Both enums are read directly from their hand-edited sources under modules/, not from
dist/NF.yaml, which is generated and deliberately not committed.

Two categories are exempt from label identity: the non-neoplasm phenotype and outcome
values listed in NON_NEOPLASM_EXEMPT, which have no Tumor counterpart; and values
carrying `deprecated:`, which exist precisely because their labels diverge and are
retained only so existing annotations stay valid until they are migrated. Deprecation
status itself is mirrored, though: a label present in both enums carries `deprecated:`
in both or in neither.

The contract is checked in both directions. ManifestationEnum is a curated subset rather
than a mirror of Tumor, so the reverse direction is guarded by INTENTIONALLY_NOT_FACETED:
every Tumor value that is not a facet option has to be listed there with a stated reason,
which forces each new Tumor value into an explicit faceted-or-not decision.

`description:` is deliberately NOT compared between the enums. ManifestationEnum omits
descriptions on purpose, and where it does carry one it may legitimately diverge -
Melanoma carries an NF-contextual description in Portal.yaml that differs from
Tumor.yaml's raw NCIT text, and that difference is correct. Only `meaning:` CURIEs are
required to agree.
"""

import re
from pathlib import Path

import pytest
import yaml

MODULES_DIR = Path(__file__).parent.parent / "modules"
PORTAL_YAML = MODULES_DIR / "DCC" / "Portal.yaml"
TUMOR_YAML = MODULES_DIR / "Sample" / "Tumor.yaml"

# Non-neoplasm phenotype and outcome values that exist only in ManifestationEnum. This
# is an explicit reviewed list, not a heuristic: adding a value here is a deliberate
# statement that the term has no file-level tumorType counterpart.
NON_NEOPLASM_EXEMPT = {
    "Behavioral",
    "Cognition",
    "Hearing Loss",
    "Memory",
    "Pain",
    "Quality of Life",
    "Vision Loss",
}

# Tumor values deliberately left out of ManifestationEnum after a value-by-value review.
# ManifestationEnum is a curated facet vocabulary, not a strict superset of Tumor, so this
# literal is the decision record: Tumor has 61 permissible values, ManifestationEnum
# covers 34 of them as neoplasms (45 values minus 4 deprecated minus the 7 in
# NON_NEOPLASM_EXEMPT), and 61 - 34 = 27 exclusions.
INTENTIONALLY_NOT_FACETED = {
    # bare state descriptors that name no tumor type, so they carry no facet information.
    # A recurrence- or atypia-qualified value that does name a specific type is faceted
    # instead - "Recurrent MPNST" (NCIT:C8823) and "Atypical MPNST" are in
    # ManifestationEnum for that reason (6)
    "tumor",
    "recurrent tumor",
    "metastatic tumor",
    "metastatic/recurrent tumor",
    "Hemorrhagic Neoplasm",
    "Necrotic Neoplasm",
    # placeholders - manifestation is optional, so omit the property instead (2)
    "Unknown",
    "Not Applicable",
    # redundant with the required diseaseFocus field, zero facet information (2)
    "NF1-Associated Tumor",
    "NF2-Associated Tumor",
    # self-declared synonym of Cutaneous Neurofibroma (1)
    "Localized Neurofibroma",
    # retired as distinct entities by the WHO 2021 CNS classification (2)
    "Glioblastoma Multiforme",
    "Oligoastrocytoma",
    # superseded by the non-NOS labels at both levels (2)
    "High-Grade Glioma NOS",
    "Low-Grade Glioma NOS",
    # subsumed by the coarser Breast Cancer for facet purposes (1)
    "Invasive Breast Carcinoma",
    # not NF-spectrum; a one-file signal does not earn a facet option (3)
    "Colorectal Carcinoma",
    "Colorectal Adenocarcinoma",
    "Teratoma",
    # zero usage on either side today; add on demand (8)
    "Anaplastic Ganglioglioma",
    "Ganglioglioma",
    "Anaplastic Pilocytic Astrocytoma",
    "Anaplastic Pleomorphic Xanthoastrocytoma",
    "Cellular Neurofibroma",
    "Fibrosarcoma",
    "Massive Soft Tissue Neurofibroma",
    "Neurofibroma with Degenerative Atypia",
}

# Mirrors LIST_MAX_SIZE in utils/check_schema_limits.py, this repo's own column config:
# utils/json_schema_entity_view.py sets maximum_size = 80 on list columns to keep entity
# view rows under Synapse's 64KB row limit. A Synapse column rejects a value wider than
# its maximum_size, so keeping labels within it leaves the value usable in any entity
# view this tooling builds.
MANIFESTATION_MAX_LABEL_LENGTH = 80

# Matches a trailing parenthesized all-caps abbreviation, e.g. "... Tumor (MPNST)".
ABBREVIATION_SUFFIX_RE = re.compile(r"\([A-Z]{2,}\)\s*$")

QUOTED_LABEL_RE = re.compile(r'"([^"]+)"')


def _load_permissible_values(path, enum_name):
    """Return {label: metadata dict} for one enum, normalizing valueless entries."""
    with open(path) as handle:
        model = yaml.safe_load(handle)
    values = model["enums"][enum_name]["permissible_values"]
    return {label: (metadata or {}) for label, metadata in values.items()}


@pytest.fixture(scope="module")
def manifestation():
    return _load_permissible_values(PORTAL_YAML, "ManifestationEnum")


@pytest.fixture(scope="module")
def tumor():
    return _load_permissible_values(TUMOR_YAML, "Tumor")


@pytest.fixture(scope="module")
def enums(manifestation, tumor):
    return {"ManifestationEnum": manifestation, "Tumor": tumor}


def test_non_deprecated_neoplasm_labels_match_tumor(manifestation, tumor):
    """Every non-deprecated neoplasm manifestation value must exist byte-identically
    in Tumor, so tumorType rolls up without a crosswalk."""
    missing = [
        label
        for label, metadata in manifestation.items()
        if "deprecated" not in metadata
        and label not in NON_NEOPLASM_EXEMPT
        and label not in tumor
    ]
    assert not missing, (
        "ManifestationEnum neoplasm values with no identical Tumor counterpart: "
        f"{sorted(missing)}. Either add the same label to the Tumor enum in "
        f"{TUMOR_YAML.name}, or - if the term is a non-neoplasm phenotype - add it to "
        "NON_NEOPLASM_EXEMPT in this test after review."
    )


def test_shared_labels_agree_on_deprecation(manifestation, tumor):
    """A label present in both enums must carry `deprecated:` in both or in neither.
    Otherwise the portal facet keeps advertising as canonical a label the file level
    already tells curators not to use."""
    divergent = {
        label: {
            "ManifestationEnum": "deprecated" in metadata,
            "Tumor": "deprecated" in tumor[label],
        }
        for label, metadata in manifestation.items()
        if label in tumor and ("deprecated" in metadata) != ("deprecated" in tumor[label])
    }
    assert not divergent, (
        "Shared labels disagree on deprecation status: "
        f"{divergent}. Deprecating a value at one level requires deprecating - or "
        "removing - its counterpart at the other, so both levels steer curators to the "
        "same canonical label."
    )


def test_exempt_values_are_still_present_in_manifestation(manifestation):
    """Keep NON_NEOPLASM_EXEMPT honest: an entry that no longer exists would silently
    widen the exemption."""
    stale = sorted(NON_NEOPLASM_EXEMPT - set(manifestation))
    assert not stale, (
        f"NON_NEOPLASM_EXEMPT lists values absent from ManifestationEnum: {stale}. "
        "Remove them from the exemption set."
    )


def test_every_tumor_value_is_faceted_or_explicitly_excluded(manifestation, tumor):
    """The reverse direction: a neoplasm added to Tumor but not to ManifestationEnum
    silently never becomes a dataset facet, so every exclusion must be a stated choice."""
    excluded = set(tumor) - set(manifestation)

    unreviewed = sorted(excluded - INTENTIONALLY_NOT_FACETED)
    assert not unreviewed, (
        f"Tumor values absent from ManifestationEnum with no recorded decision: "
        f"{unreviewed}. A new Tumor value must either be added to ManifestationEnum so "
        "it can become a dataset facet, or be added to INTENTIONALLY_NOT_FACETED in "
        "this test under a group comment stating why it is not faceted. Making that "
        "choice explicit is the point of this check."
    )

    stale = sorted(INTENTIONALLY_NOT_FACETED - excluded)
    assert not stale, (
        f"INTENTIONALLY_NOT_FACETED lists values that are no longer excluded: {stale}. "
        "They are either now present in ManifestationEnum or gone from Tumor - remove "
        "them from the exclusion set."
    )


def test_shared_labels_agree_on_meaning(manifestation, tumor):
    """Where both enums map the same label to an ontology term, the CURIEs must match.
    `description:` is intentionally not compared - see this module's docstring."""
    conflicts = {
        label: (metadata["meaning"], tumor[label]["meaning"])
        for label, metadata in manifestation.items()
        if "meaning" in metadata
        and label in tumor
        and "meaning" in tumor[label]
        and metadata["meaning"] != tumor[label]["meaning"]
    }
    assert not conflicts, (
        "Shared labels map to different CURIEs (ManifestationEnum, Tumor): "
        f"{conflicts}. Copy the meaning verbatim rather than re-deriving it."
    )


@pytest.mark.parametrize("enum_name", ["ManifestationEnum", "Tumor"])
def test_abbreviation_suffix_only_on_deprecated_values(enums, enum_name):
    """The parenthetical-abbreviation label pattern was harmonized away. New values
    must not reintroduce it; the retained deprecated ones are grandfathered."""
    offenders = [
        label
        for label, metadata in enums[enum_name].items()
        if ABBREVIATION_SUFFIX_RE.search(label) and "deprecated" not in metadata
    ]
    assert not offenders, (
        f"{enum_name} values end in a parenthesized abbreviation but are not "
        f"deprecated: {sorted(offenders)}. Spell the term out and keep the label "
        "identical across both enums."
    )


@pytest.mark.parametrize("enum_name", ["ManifestationEnum", "Tumor"])
def test_deprecated_values_name_a_valid_replacement(enums, enum_name):
    """Each `deprecated:` note must quote a currently-valid value of the same enum, so
    the migration map stays derivable from the model itself."""
    values = enums[enum_name]
    live = {label for label, metadata in values.items() if "deprecated" not in metadata}

    unresolved = {}
    for label, metadata in values.items():
        note = metadata.get("deprecated")
        if note is None:
            continue
        quoted = set(QUOTED_LABEL_RE.findall(note))
        if not quoted & live:
            unresolved[label] = note

    assert not unresolved, (
        f"{enum_name} deprecated values whose note does not quote a currently-valid "
        f"replacement in the same enum: {unresolved}. Name the replacement label in "
        'double quotes, e.g. \'Use "Glioblastoma".\''
    )


def test_manifestation_labels_fit_configured_list_column_width(manifestation):
    """Entity views built by this repo's tooling configure list columns with an item
    width of LIST_MAX_SIZE, and a Synapse column rejects a wider value."""
    too_long = {
        label: len(label)
        for label in manifestation
        if len(label) > MANIFESTATION_MAX_LABEL_LENGTH
    }
    assert not too_long, (
        "ManifestationEnum labels exceed the "
        f"{MANIFESTATION_MAX_LABEL_LENGTH}-character list column item width this repo "
        "configures (LIST_MAX_SIZE in utils/check_schema_limits.py) "
        f"(label: length): {too_long}."
    )
