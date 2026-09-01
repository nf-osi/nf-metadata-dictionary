#!/usr/bin/env python3
"""
Tests for the deterministic release decision fallback used when the AI
evaluation in the Release workflow is unavailable (e.g. Anthropic API outage
or exhausted credits).

The fallback must emit the same JSON contract the AI step produces, so the
rest of the release pipeline stays agnostic about which path decided.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

utils_path = os.path.join(os.path.dirname(__file__), '..', 'utils')
sys.path.insert(0, utils_path)

import decide_release  # noqa: E402  (needs utils on sys.path first)


SCRIPT = Path(__file__).parent.parent / 'utils' / 'decide_release.py'
RS = decide_release.RECORD_SEPARATOR

# The real commit range v11.0.20..v11.1.22, as
# `git log --no-merges --name-only --format='%x1e%h %s'` rendered it (paths
# trimmed to the ones that matter for the decision). Used to confirm the
# fallback reproduces the decision the AI made for that release (MINOR to 11.1).
REAL_RECORDS_11_1 = "".join([
    f"{RS}6448b5e Delete dca-template-config.json\n\ndca-template-config.json\n",
    f"{RS}08e9061 Rebuild all artifacts [skip ci]\n\ndist/NF.ttl\n"
    "registered-json-schemas/RNASeqTemplate.json\n",
    f"{RS}7130246 Point to correct range (#966)\n\nmodules/props.yaml\n"
    "tests/data/ChIPSeqTemplate/valid_geneperturbed_complete.json\n",
    f"{RS}a72d678 Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n",
    f"{RS}fc83fe9 Add controlled schema escape hatches (#960, #961) (#965)\n\n"
    "modules/Template/Template.yaml\nutils/gen-json-schema-class.py\n",
    f"{RS}bc9b9d8 Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n",
    f"{RS}1b4817b fix: expand file format validation (#964)\n\n"
    "modules/Data/FileFormat.yaml\n",
    f"{RS}03aa77b Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n",
    f"{RS}3be8c7b Add .arf file format (hearing test / ABR data) (#956)\n\n"
    "modules/Data/FileFormat.yaml\n",
    f"{RS}da004e4 Update curation task utils, building on new synapseclient "
    "support (#953)\n\nutils/curation_task_utils.py\n",
    f"{RS}9752beb Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n",
    f"{RS}e83152d Address enum gap\n\nmodules/Sample/Sample.yaml\n",
    f"{RS}cad41ba Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n",
    f"{RS}2973bc0 feat: add Sheba Medical Center to Institution enum (#949)\n\n"
    "modules/DCC/DCC.yaml\n",
])


def record(subject: str, *paths: str) -> decide_release.CommitRecord:
    return decide_release.CommitRecord(sha="abc1234", subject=subject, paths=paths)


# ── Version parsing ─────────────────────────────────────────────────

@pytest.mark.parametrize("tag,expected", [
    ("v11.1.22", (11, 1)),
    ("11.1.22", (11, 1)),
    ("v11.1", (11, 1)),
    ("v10.9.15", (10, 9)),
    ("v0.10.3", (0, 10)),
    ("v12.0.0", (12, 0)),
])
def test_parse_major_minor(tag: str, expected: tuple) -> None:
    assert decide_release.parse_major_minor(tag) == expected


@pytest.mark.parametrize("tag", ["", "v11", "11", "vNext", "v11.x.3", "v-1.2.3", "v11..3"])
def test_parse_major_minor_rejects_malformed(tag: str) -> None:
    """A malformed tag must raise, never be silently guessed at."""
    with pytest.raises(ValueError):
        decide_release.parse_major_minor(tag)


@pytest.mark.parametrize("tag,expected", [
    ("v11.1.22", "11.2"),
    ("v11.0.20", "11.1"),
    # Regression guard: naive string bumping turns 10.9 into 10.1, not 10.10.
    ("v10.9.15", "10.10"),
    ("v10.10.1", "10.11"),
    ("v12.0.0", "12.1"),
])
def test_next_minor_version(tag: str, expected: str) -> None:
    assert decide_release.next_minor_version(tag) == expected


def test_next_minor_version_never_bumps_major() -> None:
    """MAJOR bumps require human judgement and manual dispatch."""
    major, _ = decide_release.parse_major_minor("v11.9.30")
    bumped_major, _ = decide_release.parse_major_minor(
        decide_release.next_minor_version("v11.9.30") + ".0"
    )
    assert bumped_major == major


# ── Version acceptability (shape and ordering) ──────────────────────

@pytest.mark.parametrize("version", ["11.2", "12.0", "11.1", "11.10"])
def test_version_error_accepts_forward_versions(version: str) -> None:
    assert decide_release.version_error(version, "v11.1.22") == ""


@pytest.mark.parametrize("version", ["11.1.0", "v11.2", "", "eleven.two", "11", "11.", "01.2"])
def test_version_error_rejects_malformed(version: str) -> None:
    assert "not MAJOR.MINOR" in decide_release.version_error(version, "v11.1.22")


@pytest.mark.parametrize("version", ["10.9", "11.0", "0.1"])
def test_version_error_rejects_backwards(version: str) -> None:
    """A backwards release becomes the baseline for every later decision."""
    assert "behind the last release" in decide_release.version_error(version, "v11.1.22")


def test_version_error_allows_same_major_minor() -> None:
    """A PATCH-only re-release keeps MAJOR.MINOR, so equal must be allowed."""
    assert decide_release.version_error("11.1", "v11.1.22") == ""


def test_fallback_version_always_passes_its_own_check() -> None:
    for tag in ("v11.1.22", "v10.9.15", "v0.10.3", "v12.0.0"):
        version = decide_release.next_minor_version(tag)
        assert decide_release.version_error(version, tag) == ""


# ── Commit record parsing ───────────────────────────────────────────

def test_parse_commit_records_splits_subjects_from_paths() -> None:
    records = decide_release.parse_commit_records(
        f"{RS}abc1234 fix: something\n\nmodules/Data/FileFormat.yaml\ndocs/index.md\n"
        f"{RS}def5678 Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n"
    )

    assert [r.sha for r in records] == ["abc1234", "def5678"]
    assert records[0].subject == "fix: something"
    assert records[0].paths == ("modules/Data/FileFormat.yaml", "docs/index.md")
    assert records[1].paths == ("dist/NF.yaml",)


def test_parse_commit_records_handles_commit_with_no_paths() -> None:
    records = decide_release.parse_commit_records(f"{RS}abc1234 chore: empty commit\n\n")

    assert len(records) == 1
    assert records[0].paths == ()


def test_parse_commit_records_of_empty_input() -> None:
    assert decide_release.parse_commit_records("") == []


def test_parse_commit_records_keeps_subjects_containing_spaces() -> None:
    records = decide_release.parse_commit_records(
        f"{RS}abc1234 feat: add Sheba Medical Center to Institution enum (#949)\n\n"
        "modules/DCC/DCC.yaml\n"
    )

    assert records[0].subject == "feat: add Sheba Medical Center to Institution enum (#949)"


# ── Automated commit filtering ──────────────────────────────────────

@pytest.mark.parametrize("subject", [
    "Rebuild all artifacts [skip ci]",
    "Rebuild all artifacts",
    "chore: tidy up [skip ci]",
    "rebuild all artifacts [SKIP CI]",
])
def test_automated_commits_recognized(subject: str) -> None:
    assert decide_release.is_automated_commit(subject) is True


@pytest.mark.parametrize("subject", [
    "feat: add Sheba Medical Center to Institution enum (#949)",
    "Point to correct range (#966)",
    "Delete dca-template-config.json",
    "fix: expand file format validation (#964)",
])
def test_meaningful_commits_not_treated_as_automated(subject: str) -> None:
    assert decide_release.is_automated_commit(subject) is False


def test_meaningful_records_filters_and_preserves_order() -> None:
    records = decide_release.parse_commit_records(REAL_RECORDS_11_1)
    result = decide_release.meaningful_records(records)

    assert len(records) == 14
    assert all("Rebuild all artifacts" not in r.subject for r in result)
    assert len(result) == 8  # 14 commits in the range, 6 of them automated rebuilds
    assert result[0].subject == "Delete dca-template-config.json"
    assert result[-1].subject.endswith("add Sheba Medical Center to Institution enum (#949)")


def test_blank_lines_ignored() -> None:
    assert decide_release.parse_commit_records("\n   \n\t\n") == []


# ── Schema relevance of changed paths ───────────────────────────────

@pytest.mark.parametrize("path", [
    "modules/Data/FileFormat.yaml",
    "modules/props.yaml",
    "header.yaml",
    "dist/NF.yaml",
    "registered-json-schemas/RNASeqTemplate.json",
    # The generator rewrites every published schema, and rules/ supplies the
    # Superdataset overlay, so both are model input just like modules/.
    "utils/gen-json-schema-class.py",
    "rules/super_rules.json",
])
def test_schema_relevant_paths_recognized(path: str) -> None:
    assert decide_release.is_schema_relevant(path) is True


@pytest.mark.parametrize("path", [
    "utils/curation_task_utils.py",
    "utils/decide_release.py",
    ".github/workflows/release-new-version.yaml",
    "tests/test_decide_release.py",
    "docs/index.md",
    "README.md",
    "dca-template-config.json",
    "config.yml",
    "",
    # Not a directory prefix match: only a leading path segment counts.
    "docs/modules/overview.md",
    "retired-modules/Old.yaml",
])
def test_non_schema_paths_rejected(path: str) -> None:
    assert decide_release.is_schema_relevant(path) is False


def test_schema_relevant_paths_deduplicates_and_sorts() -> None:
    records = [
        record("fix: one", "modules/Data/FileFormat.yaml", "docs/index.md"),
        record("fix: two", "modules/Data/FileFormat.yaml", "dist/NF.yaml"),
    ]

    assert decide_release.schema_relevant_paths(records) == [
        "dist/NF.yaml",
        "modules/Data/FileFormat.yaml",
    ]


# ── Decision logic ──────────────────────────────────────────────────

def test_decide_releases_minor_when_model_changed() -> None:
    decision = decide_release.decide(
        "v11.1.22", [record("fix: correct a range", "modules/props.yaml")]
    )

    assert decision["release"] is True
    assert decision["version"] == "11.2"
    assert decision["reasoning"]


def test_decide_reproduces_the_real_11_1_release() -> None:
    """Same inputs the AI saw for v11.1.22 must yield the same MINOR decision."""
    decision = decide_release.decide(
        "v11.0.20", decide_release.parse_commit_records(REAL_RECORDS_11_1)
    )

    assert decision["release"] is True
    assert decision["version"] == "11.1"


def test_decide_declines_when_no_commit_touches_the_model() -> None:
    """Docs/CI/tooling churn must not burn a Synapse schema version."""
    decision = decide_release.decide("v11.1.22", [
        record("Update curation task utils (#953)", "utils/curation_task_utils.py"),
        record("ci: add a pytest file", ".github/workflows/main-ci.yml"),
        record("docs: fix a typo", "docs/index.md"),
        record("Delete dca-template-config.json", "dca-template-config.json"),
    ])

    assert decision["release"] is False
    assert "version" not in decision
    assert "none touch the data model" in decision["reasoning"]
    assert "modules/" in decision["reasoning"]


def test_decide_releases_when_a_single_commit_touches_the_model() -> None:
    decision = decide_release.decide("v11.1.22", [
        record("docs: fix a typo", "docs/index.md"),
        record("feat: add an enum value", "modules/DCC/DCC.yaml"),
    ])

    assert decision["release"] is True
    assert decision["version"] == "11.2"


def test_decide_releases_on_a_generator_only_cycle() -> None:
    """
    A change to the generator rewrites every published schema, but the rebuilt
    artifacts only land in the filtered-out automated commit, so the generator
    itself has to count as a model change.
    """
    decision = decide_release.decide("v11.1.22", [
        record("Add controlled schema escape hatches", "utils/gen-json-schema-class.py"),
        record("Rebuild all artifacts [skip ci]", "registered-json-schemas/X.json"),
    ])

    assert decision["release"] is True
    assert decision["version"] == "11.2"


def test_decide_releases_on_a_rules_only_cycle() -> None:
    """rules/ is the overlay `make Superdataset` merges into the published schema."""
    decision = decide_release.decide(
        "v11.1.22", [record("feat: relax Superdataset rules", "rules/super_rules.json")]
    )

    assert decision["release"] is True
    assert decision["version"] == "11.2"


def test_decide_ignores_model_paths_touched_only_by_automated_commits() -> None:
    """
    Automated rebuilds always touch dist/ and registered-json-schemas/, so
    attributing their paths to the range would make the gate trivially true.
    """
    decision = decide_release.decide("v11.1.22", [
        record("Rebuild all artifacts [skip ci]", "dist/NF.yaml", "registered-json-schemas/X.json"),
        record("docs: fix a typo", "docs/index.md"),
    ])

    assert decision["release"] is False
    assert "none touch the data model" in decision["reasoning"]


def test_decide_declines_when_only_automated_commits() -> None:
    decision = decide_release.decide("v11.1.22", [
        record("Rebuild all artifacts [skip ci]", "dist/NF.yaml"),
        record("Rebuild all artifacts [skip ci]", "dist/NF.ttl"),
    ])

    assert decision["release"] is False
    assert "version" not in decision
    assert "automated rebuilds" in decision["reasoning"]


def test_decide_declines_on_empty_commit_range() -> None:
    """An empty range must not be reported as 'all automated rebuilds'."""
    decision = decide_release.decide("v11.1.22", [])

    assert decision["release"] is False
    assert "version" not in decision
    assert "range is empty" in decision["reasoning"]
    assert "automated" not in decision["reasoning"]


def test_decide_output_matches_ai_json_contract() -> None:
    """
    Downstream steps read .release, .version, .reasoning and .notes from the
    same JSON regardless of which path produced it.
    """
    decision = decide_release.decide(
        "v11.1.22", [record("fix: something real", "modules/props.yaml")]
    )

    assert set(decision).issubset({"release", "version", "reasoning", "notes"})
    assert isinstance(decision["release"], bool)
    assert isinstance(decision["version"], str)
    assert isinstance(decision["reasoning"], str)
    # Notes are left to GitHub's --generate-notes on the fallback path.
    assert not decision.get("notes")


def test_decide_rejects_malformed_tag() -> None:
    with pytest.raises(ValueError):
        decide_release.decide(
            "not-a-tag", [record("fix: something real", "modules/props.yaml")]
        )


# ── CLI behaviour (how the workflow actually invokes it) ────────────

def _run_cli(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
    )


def _decide_cli(tmp_path: Path, last_tag: str, records_text: str) -> subprocess.CompletedProcess:
    commit_paths = tmp_path / "commit_paths.txt"
    commit_paths.write_text(records_text)
    return _run_cli([
        "decide", "--last-tag", last_tag, "--commit-paths-file", str(commit_paths),
    ])


def test_cli_prints_valid_json_and_exits_zero(tmp_path: Path) -> None:
    result = _decide_cli(tmp_path, "v11.0.20", REAL_RECORDS_11_1)

    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)
    assert decision == {
        "release": True,
        "version": "11.1",
        "reasoning": decision["reasoning"],
    }


def test_cli_declines_with_only_automated_commits(tmp_path: Path) -> None:
    result = _decide_cli(
        tmp_path, "v11.1.22", f"{RS}08e9061 Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n"
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["release"] is False


def test_cli_declines_without_model_changes(tmp_path: Path) -> None:
    result = _decide_cli(
        tmp_path, "v11.1.22", f"{RS}da004e4 Update curation task utils\n\nutils/x.py\n"
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["release"] is False


def test_cli_handles_missing_commit_paths_file_as_empty(tmp_path: Path) -> None:
    """
    The workflow may not have written a records file; that means nothing to
    release, not a crash that blocks the pipeline.
    """
    result = _run_cli([
        "decide",
        "--last-tag", "v11.1.22",
        "--commit-paths-file", str(tmp_path / "absent.txt"),
    ])

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["release"] is False


def test_cli_fails_loudly_on_malformed_tag(tmp_path: Path) -> None:
    result = _decide_cli(tmp_path, "vNope", f"{RS}abc1234 fix: real\n\nmodules/props.yaml\n")

    assert result.returncode != 0
    assert "vNope" in result.stderr
    assert result.stdout.strip() == ""


def test_cli_check_version_accepts_forward_version() -> None:
    result = _run_cli(["check-version", "--last-tag", "v11.1.22", "--version", "11.2"])

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("version,expected", [
    ("11.1.0", "not MAJOR.MINOR"),
    ("v11.2", "not MAJOR.MINOR"),
    ("10.9", "behind the last release"),
])
def test_cli_check_version_rejects_unusable_version(version: str, expected: str) -> None:
    result = _run_cli(["check-version", "--last-tag", "v11.1.22", "--version", version])

    assert result.returncode != 0
    assert expected in result.stderr


def test_cli_check_version_fails_on_malformed_last_tag() -> None:
    result = _run_cli(["check-version", "--last-tag", "vNope", "--version", "11.2"])

    assert result.returncode != 0
    assert "vNope" in result.stderr


def test_cli_requires_a_subcommand() -> None:
    result = _run_cli([])

    assert result.returncode != 0
