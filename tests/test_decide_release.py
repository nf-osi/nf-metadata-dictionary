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

# The real commit range v11.0.20..v11.1.22, as `git log --oneline --no-merges`
# rendered it. Used to confirm the fallback reproduces the decision the AI
# made for that release (MINOR bump to 11.1).
REAL_COMMITS_11_1 = """6448b5e Delete dca-template-config.json
08e9061 Rebuild all artifacts [skip ci]
7130246 Point to correct range (#966)
a72d678 Rebuild all artifacts [skip ci]
fc83fe9 Add controlled schema escape hatches (#960, #961) (#965)
bc9b9d8 Rebuild all artifacts [skip ci]
1b4817b fix: expand file format validation (#964)
03aa77b Rebuild all artifacts [skip ci]
3be8c7b Add .arf file format (hearing test / ABR data) (#956)
da004e4 Update curation task utils, building on new synapseclient support (#953)
9752beb Rebuild all artifacts [skip ci]
e83152d Address enum gap
cad41ba Rebuild all artifacts [skip ci]
2973bc0 feat: add Sheba Medical Center to Institution enum (#949)""".splitlines()


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


# ── Automated commit filtering ──────────────────────────────────────

@pytest.mark.parametrize("subject", [
    "08e9061 Rebuild all artifacts [skip ci]",
    "08e9061 Rebuild all artifacts",
    "08e9061 chore: tidy up [skip ci]",
    "08e9061 rebuild all artifacts [SKIP CI]",
])
def test_automated_commits_recognized(subject: str) -> None:
    assert decide_release.is_automated_commit(subject) is True


@pytest.mark.parametrize("subject", [
    "2973bc0 feat: add Sheba Medical Center to Institution enum (#949)",
    "7130246 Point to correct range (#966)",
    "6448b5e Delete dca-template-config.json",
    "1b4817b fix: expand file format validation (#964)",
])
def test_meaningful_commits_not_treated_as_automated(subject: str) -> None:
    assert decide_release.is_automated_commit(subject) is False


def test_meaningful_commits_filters_and_preserves_order() -> None:
    result = decide_release.meaningful_commits(REAL_COMMITS_11_1)

    assert all("Rebuild all artifacts" not in line for line in result)
    assert len(result) == 8  # 14 commits in the range, 6 of them automated rebuilds
    assert result[0].endswith("Delete dca-template-config.json")
    assert result[-1].endswith("feat: add Sheba Medical Center to Institution enum (#949)")


def test_blank_lines_ignored() -> None:
    assert decide_release.meaningful_commits(["", "   ", "\t"]) == []


# ── Decision logic ──────────────────────────────────────────────────

def test_decide_releases_minor_when_meaningful_commits_exist() -> None:
    decision = decide_release.decide("v11.1.22", ["abc1234 fix: correct a range"])

    assert decision["release"] is True
    assert decision["version"] == "11.2"
    assert decision["reasoning"]


def test_decide_reproduces_the_real_11_1_release() -> None:
    """Same inputs the AI saw for v11.1.22 must yield the same MINOR decision."""
    decision = decide_release.decide("v11.0.20", REAL_COMMITS_11_1)

    assert decision["release"] is True
    assert decision["version"] == "11.1"


def test_decide_declines_when_only_automated_commits() -> None:
    only_automated = [
        "08e9061 Rebuild all artifacts [skip ci]",
        "a72d678 Rebuild all artifacts [skip ci]",
    ]
    decision = decide_release.decide("v11.1.22", only_automated)

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
    decision = decide_release.decide("v11.1.22", ["abc1234 fix: something real"])

    assert set(decision).issubset({"release", "version", "reasoning", "notes"})
    assert isinstance(decision["release"], bool)
    assert isinstance(decision["version"], str)
    assert isinstance(decision["reasoning"], str)
    # Notes are left to GitHub's --generate-notes on the fallback path.
    assert not decision.get("notes")


def test_decide_rejects_malformed_tag() -> None:
    with pytest.raises(ValueError):
        decide_release.decide("not-a-tag", ["abc1234 fix: something real"])


# ── CLI behaviour (how the workflow actually invokes it) ────────────

def _run_cli(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
    )


def test_cli_prints_valid_json_and_exits_zero(tmp_path: Path) -> None:
    commits = tmp_path / "commits.txt"
    commits.write_text("\n".join(REAL_COMMITS_11_1) + "\n")

    result = _run_cli(["--last-tag", "v11.0.20", "--commits-file", str(commits)])

    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)
    assert decision == {
        "release": True,
        "version": "11.1",
        "reasoning": decision["reasoning"],
    }


def test_cli_declines_with_only_automated_commits(tmp_path: Path) -> None:
    commits = tmp_path / "commits.txt"
    commits.write_text("08e9061 Rebuild all artifacts [skip ci]\n")

    result = _run_cli(["--last-tag", "v11.1.22", "--commits-file", str(commits)])

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["release"] is False


def test_cli_handles_missing_commits_file_as_empty(tmp_path: Path) -> None:
    """
    The workflow may not have written a commits file; that means nothing to
    release, not a crash that blocks the pipeline.
    """
    result = _run_cli([
        "--last-tag", "v11.1.22",
        "--commits-file", str(tmp_path / "absent.txt"),
    ])

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["release"] is False


def test_cli_fails_loudly_on_malformed_tag(tmp_path: Path) -> None:
    commits = tmp_path / "commits.txt"
    commits.write_text("abc1234 fix: something real\n")

    result = _run_cli(["--last-tag", "vNope", "--commits-file", str(commits)])

    assert result.returncode != 0
    assert "vNope" in result.stderr
    assert result.stdout.strip() == ""
