#!/usr/bin/env python3
"""
Tests for the Release workflow's decision step: both the AI-acceptance path
and the deterministic fallback used when the AI evaluation is unavailable
(e.g. Anthropic API outage or exhausted credits), plus the choice between them.

AI acceptance covers ai_response_text (non-200, a request that never completed,
unusable or truncated payloads, text blocks after thinking blocks), ai_decision
(fence stripping, the boolean gate, version shape and ordering), and the
accept-ai CLI. The deterministic side covers decide, releasability_error and
resolve_decision.

Both paths must emit the same JSON contract, so the rest of the release
pipeline stays agnostic about which one decided.
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
WORKFLOW = (
    Path(__file__).parent.parent
    / '.github' / 'workflows' / 'release-new-version.yaml'
)
RS = decide_release.RECORD_SEPARATOR


def api_call_command() -> str:
    """The curl invocation that calls the API, with the prose around it dropped.

    Searching the whole workflow would match the comment above the call, which
    names most of these flags, so the assertions would hold even with the flags
    deleted from the command itself.
    """
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(
        index for index, line in enumerate(lines)
        if "curl -s -o /tmp/api_response.json" in line
    )
    command = [lines[start]]
    while command[-1].rstrip().endswith("\\"):
        command.append(lines[start + len(command)])
    return "\n".join(command)


# The real commit range v11.0.20..v11.1.22, as
# `git log --no-merges --name-only --format='%x1e%h %s'` rendered it. Long path
# lists are trimmed to a representative subset, but every path below is one the
# named commit actually touched - `git show --name-only <sha>` is the source of
# truth here, since the point of this fixture is that it replays real history.
# Note the generator change in this range is 1b4817b (#964), not fc83fe9 (#965).
REAL_RECORDS_11_1 = "".join([
    f"{RS}6448b5e Delete dca-template-config.json\n\ndca-template-config.json\n",
    f"{RS}08e9061 Rebuild all artifacts [skip ci]\n\ndist/NF.ttl\n"
    "registered-json-schemas/RNASeqTemplate.json\n",
    f"{RS}7130246 Point to correct range (#966)\n\nmodules/props.yaml\n"
    "tests/data/ChIPSeqTemplate/valid_geneperturbed_complete.json\n",
    f"{RS}a72d678 Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n",
    f"{RS}fc83fe9 Add controlled schema escape hatches (#960, #961) (#965)\n\n"
    "modules/Experiment/Factor.yaml\nmodules/Template/Data_Clinical.yaml\n"
    "modules/props.yaml\ntests/test_schema_escape_hatches.py\n",
    f"{RS}bc9b9d8 Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n",
    f"{RS}1b4817b fix: expand file format validation (#964)\n\n"
    "modules/Data/FileFormat.yaml\nmodules/Template/Data_Genomics.yaml\n"
    "tests/test_file_entity_schema_guard.py\nutils/gen-json-schema-class.py\n",
    f"{RS}03aa77b Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n",
    f"{RS}3be8c7b Add .arf file format (hearing test / ABR data) (#956)\n\n"
    "modules/Data/FileFormat.yaml\nmodules/Template/Data_Clinical.yaml\n",
    f"{RS}da004e4 Update curation task utils, building on new synapseclient "
    "support (#953)\n\n.github/workflows/create-curation-task.yml\n"
    "dev/DEVELOPMENT.md\nutils/create_curation_task.py\n"
    "utils/create_recordset_task.py\n",
    f"{RS}9752beb Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n",
    f"{RS}e83152d Address enum gap\n\nmodules/Template/Data_Imaging.yaml\n"
    "modules/Template/Data_Proteomics.yaml\n",
    f"{RS}cad41ba Rebuild all artifacts [skip ci]\n\ndist/NF.yaml\n",
    f"{RS}2973bc0 feat: add Sheba Medical Center to Institution enum (#949)\n\n"
    "modules/Other/Organization.yaml\n",
])

# Real release tags from this repo's history that TAG_PATTERN cannot parse:
# "10.08.0" has a leading zero in the MINOR, "v.6.2.0" has a "v." prefix.
UNPARSEABLE_REAL_TAGS = ("10.08.0", "v.6.2.0")


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


# ── Unusable baseline tags ──────────────────────────────────────────

@pytest.mark.parametrize("tag", UNPARSEABLE_REAL_TAGS)
def test_baseline_error_names_an_unparseable_real_tag(tag: str) -> None:
    assert tag in decide_release.baseline_error(tag)


@pytest.mark.parametrize("tag", ["v11.1.22", "11.1", "v0.10.3"])
def test_baseline_error_accepts_usable_tags(tag: str) -> None:
    assert decide_release.baseline_error(tag) == ""


@pytest.mark.parametrize("tag", UNPARSEABLE_REAL_TAGS)
def test_version_error_skips_ordering_against_an_unusable_baseline(tag: str) -> None:
    """
    An unparseable baseline is the tag's fault, not the proposed version's, and
    must not block a shape-valid version - that would fail the whole run.
    """
    assert decide_release.version_error("11.2", tag) == ""


@pytest.mark.parametrize("tag", UNPARSEABLE_REAL_TAGS)
def test_version_error_still_rejects_shape_against_an_unusable_baseline(tag: str) -> None:
    assert "not MAJOR.MINOR" in decide_release.version_error("11.2.0", tag)


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
    "utils/create_curation_task.py",
    "utils/decide_release.py",
    ".github/workflows/release-new-version.yaml",
    "tests/test_decide_release.py",
    "docs/index.md",
    "README.md",
    "dca-template-config.json",
    "config.yml",
    "",
    # These have no leading path segment at all. No git output is known to emit
    # them, but a garbled records file must still only cost a release decision,
    # never abort the step.
    ".",
    "./",
    # Not a directory prefix match: only a leading path segment counts.
    "docs/modules/overview.md",
    "retired-modules/Old.yaml",
])
def test_non_schema_paths_rejected(path: str) -> None:
    assert decide_release.is_schema_relevant(path) is False


@pytest.mark.parametrize("quoted,unquoted", [
    # What `git log --name-only` emits for a non-ASCII path when core.quotePath
    # is left at its default. The workflow disables it, so this is belt and
    # braces.
    (r'"modules/Caf\303\251.yaml"', "modules/Café.yaml"),
    # core.quotePath=false does not cover these: git quotes any path holding a
    # double quote or a control character regardless of that setting.
    (r'"modules/say\"hi.yaml"', 'modules/say"hi.yaml'),
    (r'"modules/tab\there.yaml"', "modules/tab\there.yaml"),
])
def test_quoted_paths_are_unescaped_before_the_gate(
    quoted: str, unquoted: str
) -> None:
    """A C-quoted path starts with `"` instead of a directory name, so leaving
    it escaped would decline a release that really did change the model."""
    assert decide_release.unquote_git_path(quoted) == unquoted
    assert decide_release.is_schema_relevant(quoted) is True


def test_quoted_non_model_path_still_rejected() -> None:
    assert decide_release.is_schema_relevant(r'"docs/Caf\303\251.md"') is False


def test_decide_releases_for_a_quoted_model_path() -> None:
    records = [record("feat: add a template", r'"modules/Caf\303\251.yaml"')]

    assert decide_release.decide("v11.1.22", records)["release"] is True


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
        record("Update curation task utils (#953)", "utils/create_curation_task.py"),
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


@pytest.mark.parametrize("tag", UNPARSEABLE_REAL_TAGS + ("not-a-tag",))
def test_decide_declines_on_an_unusable_baseline_without_raising(tag: str) -> None:
    """
    There is no MINOR to bump, but raising would abort the release step under
    `set -e` - the exact blocking the fallback exists to prevent.
    """
    decision = decide_release.decide(
        tag, [record("fix: something real", "modules/props.yaml")]
    )

    assert decision["release"] is False
    assert "version" not in decision
    assert tag in decision["reasoning"]


# ── Reading the AI's response ───────────────────────────────────────

def api_body(text: str) -> str:
    """An Anthropic /v1/messages response carrying `text`."""
    return json.dumps({"content": [{"type": "text", "text": text}]})


def test_ai_response_text_extracts_the_model_answer() -> None:
    assert decide_release.ai_response_text("200", api_body("hello")) == "hello"


def test_ai_response_text_finds_text_after_a_thinking_block() -> None:
    """
    The answer is not always the first content block.

    Indexing block 0 would report a perfectly good decision as an unusable
    payload the moment the API prepends a thinking or server tool-use block,
    silently routing every scheduled run to the deterministic path.
    """
    body = json.dumps({
        "content": [
            {"type": "thinking", "thinking": "weighing the commits"},
            {"type": "text", "text": '{"release": false}'},
        ]
    })

    assert decide_release.ai_response_text("200", body) == '{"release": false}'


def test_ai_response_text_prefers_a_text_block_over_another_text_field() -> None:
    body = json.dumps({
        "content": [
            {"type": "server_tool_use", "text": "not the answer"},
            {"type": "text", "text": "the answer"},
        ]
    })

    assert decide_release.ai_response_text("200", body) == "the answer"


def test_ai_response_text_names_truncation_explicitly() -> None:
    """
    A response cut off at max_tokens is truncated, not misformatted.

    Reporting it as invalid JSON would leave a maintainer with no hint that
    raising the cap is the fix.
    """
    body = json.dumps({
        "stop_reason": "max_tokens",
        "content": [{"type": "text", "text": '{"release": true, "version": "12.'}],
    })

    with pytest.raises(decide_release.AiUnusable, match="truncated"):
        decide_release.ai_response_text("200", body)


def test_truncated_response_degrades_instead_of_failing() -> None:
    """Truncation is one more reason to fall back, never a reason to abort."""
    body = json.dumps({
        "stop_reason": "max_tokens",
        "content": [{"type": "text", "text": '{"release": true, "version": "12.'}],
    })

    outcome = decide_release.resolve_decision(
        "200", body, "v11.1.22", [record("feat: new template", "modules/props.yaml")]
    )

    assert outcome.source == "fallback"
    assert "truncated" in outcome.fallback_reason
    assert outcome.decision == {
        "release": True,
        "version": "11.2",
        "reasoning": outcome.decision["reasoning"],
    }


def test_ai_response_text_accepts_a_normal_stop_reason() -> None:
    body = json.dumps({
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "hello"}],
    })

    assert decide_release.ai_response_text("200", body) == "hello"


@pytest.mark.parametrize("code", ["400", "401", "402", "429", "500", "529"])
def test_ai_response_text_rejects_non_200(code: str) -> None:
    """The credit-exhaustion error that caused #967 arrives as an HTTP status."""
    with pytest.raises(decide_release.AiUnusable, match=f"HTTP {code}"):
        decide_release.ai_response_text(code, api_body("ignored"))


@pytest.mark.parametrize("code", [decide_release.CURL_FAILURE_CODE, "", "   "])
def test_ai_response_text_rejects_an_unreachable_api(code: str) -> None:
    """curl reports no status at all on DNS failure, network failure or a
    --max-time/--connect-timeout expiry."""
    with pytest.raises(decide_release.AiUnusable, match="never completed"):
        decide_release.ai_response_text(code, "")


@pytest.mark.parametrize("body", [
    "",
    "not json at all",
    "<html>502 Bad Gateway</html>",
    json.dumps({"error": {"message": "credit balance is too low"}}),
    json.dumps({"content": []}),
    json.dumps({"content": [{"type": "tool_use"}]}),
])
def test_ai_response_text_rejects_an_unusable_payload(body: str) -> None:
    with pytest.raises(decide_release.AiUnusable):
        decide_release.ai_response_text("200", body)


@pytest.mark.parametrize("text", ["", "   \n  "])
def test_ai_response_text_rejects_empty_text(text: str) -> None:
    with pytest.raises(decide_release.AiUnusable, match="no text"):
        decide_release.ai_response_text("200", api_body(text))


# ── Judging the AI's decision ───────────────────────────────────────

def test_ai_decision_accepts_a_well_formed_release() -> None:
    decision = decide_release.ai_decision(
        json.dumps({
            "release": True,
            "version": "11.2",
            "reasoning": "new templates",
            "notes": "## What's new",
        }),
        "v11.1.22",
    )

    assert decision == {
        "release": True,
        "version": "11.2",
        "reasoning": "new templates",
        "notes": "## What's new",
    }


def test_ai_decision_accepts_markdown_fenced_json() -> None:
    """The prompt asks for bare JSON, but the model often fences it anyway."""
    decision = decide_release.ai_decision(
        '```json\n{"release": true, "version": "11.2", "reasoning": "ok"}\n```',
        "v11.1.22",
    )

    assert decision["release"] is True
    assert decision["version"] == "11.2"


def test_ai_decision_accepts_a_decline() -> None:
    decision = decide_release.ai_decision(
        json.dumps({"release": False, "reasoning": "only automated rebuilds"}),
        "v11.1.22",
    )

    assert decision == {"release": False, "reasoning": "only automated rebuilds"}


def test_ai_decision_drops_unvalidated_extra_fields() -> None:
    """Only rebuilt, validated fields may reach the workflow."""
    decision = decide_release.ai_decision(
        json.dumps({
            "release": True,
            "version": "11.2",
            "reasoning": "ok",
            "should_release": "true",
            "notes": "   ",
        }),
        "v11.1.22",
    )

    assert set(decision) == {"release", "version", "reasoning"}


@pytest.mark.parametrize("text", [
    "I'd recommend releasing version 11.2 because the templates changed.",
    "",
    "```json\n```",
    # Two JSON documents: the prompt shows two alternatives, so a model can
    # emit both. A per-document check would pass on the last one alone.
    '{"release": false, "reasoning": "a"}\n{"release": false, "reasoning": "b"}',
])
def test_ai_decision_rejects_a_non_document_response(text: str) -> None:
    with pytest.raises(decide_release.AiUnusable, match="single valid decision JSON"):
        decide_release.ai_decision(text, "v11.1.22")


@pytest.mark.parametrize("raw", [
    {"reasoning": "forgot the verdict"},
    {"release": None, "reasoning": "null"},
    {"release": "yes", "reasoning": "a string"},
    {"release": "true", "reasoning": "a string"},
    {"release": 1, "reasoning": "an int"},
])
def test_ai_decision_requires_a_boolean_release(raw: dict) -> None:
    """A null or "yes" would sail past a has("release") check, then decline."""
    with pytest.raises(decide_release.AiUnusable, match="boolean 'release'"):
        decide_release.ai_decision(json.dumps(raw), "v11.1.22")


@pytest.mark.parametrize("version", ["11.1.0", "v11.2", "eleven.two", "", None])
def test_ai_decision_falls_back_on_a_malformed_version(version) -> None:
    """
    A malformed version is the model's mistake, not a pipeline fault, so it must
    become a fallback rather than failing the run.
    """
    with pytest.raises(decide_release.AiUnusable, match="not MAJOR.MINOR"):
        decide_release.ai_decision(
            json.dumps({"release": True, "version": version, "reasoning": "ok"}),
            "v11.1.22",
        )


def test_ai_decision_falls_back_on_a_backwards_version() -> None:
    with pytest.raises(decide_release.AiUnusable, match="behind the last release"):
        decide_release.ai_decision(
            json.dumps({"release": True, "version": "10.9", "reasoning": "ok"}),
            "v11.1.22",
        )


@pytest.mark.parametrize("tag", UNPARSEABLE_REAL_TAGS)
def test_ai_decision_accepts_a_good_version_despite_an_unusable_baseline(tag: str) -> None:
    """A tag this repo really published must not invalidate a usable version."""
    decision = decide_release.ai_decision(
        json.dumps({"release": True, "version": "11.2", "reasoning": "ok"}), tag
    )

    assert decision["version"] == "11.2"


def test_ai_decision_tolerates_non_string_reasoning() -> None:
    decision = decide_release.ai_decision(
        json.dumps({"release": False, "reasoning": {"unexpected": "shape"}}), "v11.1.22"
    )

    assert decision == {"release": False, "reasoning": ""}


# ── Choosing between the two paths ──────────────────────────────────

MODEL_CHANGE_RECORDS = [record("fix: correct a range", "modules/props.yaml")]


def test_resolve_decision_prefers_a_usable_ai_answer() -> None:
    outcome = decide_release.resolve_decision(
        "200",
        api_body(json.dumps({"release": True, "version": "12.0", "reasoning": "ok"})),
        "v11.1.22",
        MODEL_CHANGE_RECORDS,
    )

    assert outcome.source == "ai"
    assert outcome.fallback_reason == ""
    assert outcome.decision["version"] == "12.0"


@pytest.mark.parametrize("code,body,expected", [
    ("402", '{"error": {"message": "credit balance is too low"}}', "HTTP 402"),
    (decide_release.CURL_FAILURE_CODE, "", "never completed"),
    ("200", "not json", "not a usable API payload"),
    ("200", None, "single valid decision JSON"),
])
def test_resolve_decision_falls_back_on_an_unusable_answer(
    code: str, body, expected: str
) -> None:
    outcome = decide_release.resolve_decision(
        code,
        api_body("prose, not JSON") if body is None else body,
        "v11.1.22",
        MODEL_CHANGE_RECORDS,
    )

    assert outcome.source == "fallback"
    assert expected in outcome.fallback_reason
    assert outcome.decision["release"] is True
    assert outcome.decision["version"] == "11.2"


def test_resolve_decision_keeps_the_model_text_for_logging() -> None:
    """A rejected answer must still be diagnosable from the run page."""
    outcome = decide_release.resolve_decision(
        "200", api_body("release it, probably"), "v11.1.22", MODEL_CHANGE_RECORDS
    )

    assert outcome.ai_text == "release it, probably"


@pytest.mark.parametrize("tag", UNPARSEABLE_REAL_TAGS)
def test_resolve_decision_declines_when_baseline_and_ai_are_both_unusable(tag: str) -> None:
    """No MINOR to bump and no evaluator, but the run must still not fail."""
    outcome = decide_release.resolve_decision(
        "500", "", tag, MODEL_CHANGE_RECORDS
    )

    assert outcome.source == "fallback"
    assert outcome.decision["release"] is False
    assert tag in outcome.decision["reasoning"]


# ── Defence in depth against an unreleasable decision ───────────────

@pytest.mark.parametrize("decision", [
    {"release": False, "reasoning": "no"},
    {"release": True, "version": "11.2", "reasoning": "ok"},
])
def test_releasability_error_accepts_sound_decisions(decision: dict) -> None:
    assert decide_release.releasability_error(decision, "v11.1.22") == ""


@pytest.mark.parametrize("decision", [
    {"release": True, "reasoning": "no version at all"},
    {"release": True, "version": "11.1.0", "reasoning": "full semver"},
    {"release": True, "version": "10.9", "reasoning": "backwards"},
])
def test_releasability_error_rejects_an_untaggable_decision(decision: dict) -> None:
    """Only reachable if this module is broken; tagging garbage is worse."""
    assert decide_release.releasability_error(decision, "v11.1.22") != ""


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


def test_cli_still_decides_when_a_commit_subject_is_not_utf8(tmp_path: Path) -> None:
    """
    git emits %s verbatim, so a commit authored without an encoding header can
    put raw non-UTF-8 bytes in the records file. That must not abort the step -
    the paths are still readable, so the release decision still stands.
    """
    commit_paths = tmp_path / "commit_paths.txt"
    commit_paths.write_bytes(
        RS.encode() + b"abc1234 fix: caf\xe9 subject\n\nmodules/props.yaml\n"
    )

    result = _run_cli([
        "decide", "--last-tag", "v11.1.22", "--commit-paths-file", str(commit_paths),
    ])

    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)
    assert decision["release"] is True
    assert decision["version"] == "11.2"


@pytest.mark.parametrize("tag", UNPARSEABLE_REAL_TAGS + ("vNope",))
def test_cli_declines_on_an_unusable_baseline_without_failing(
    tmp_path: Path, tag: str
) -> None:
    result = _decide_cli(
        tmp_path, tag, f"{RS}abc1234 fix: real\n\nmodules/props.yaml\n"
    )

    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)
    assert decision["release"] is False
    assert tag in decision["reasoning"]


def _accept_ai_cli(
    tmp_path: Path,
    http_code: str,
    response_body,
    last_tag: str = "v11.1.22",
    records_text: str = f"{RS}abc1234 fix: real\n\nmodules/props.yaml\n",
) -> subprocess.CompletedProcess:
    commit_paths = tmp_path / "commit_paths.txt"
    commit_paths.write_text(records_text)
    response_file = tmp_path / "api_response.json"
    if response_body is not None:
        response_file.write_text(response_body)
    return _run_cli([
        "accept-ai",
        "--last-tag", last_tag,
        "--http-code", http_code,
        "--response-file", str(response_file),
        "--commit-paths-file", str(commit_paths),
    ])


def _outcome(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    # One JSON document on stdout, so the workflow's jq reads exactly one value.
    assert result.stdout.count("\n") == 1
    return json.loads(result.stdout)


def test_cli_accept_ai_uses_a_usable_ai_decision(tmp_path: Path) -> None:
    result = _accept_ai_cli(
        tmp_path,
        "200",
        api_body(json.dumps({
            "release": True, "version": "12.0", "reasoning": "big", "notes": "# notes",
        })),
    )
    outcome = _outcome(result)

    assert outcome == {
        "source": "ai",
        "fallback_reason": "",
        "decision": {
            "release": True, "version": "12.0", "reasoning": "big", "notes": "# notes",
        },
    }
    assert "Claude's evaluation:" in result.stderr


def test_cli_accept_ai_accepts_fenced_json(tmp_path: Path) -> None:
    result = _accept_ai_cli(
        tmp_path,
        "200",
        api_body('```json\n{"release": true, "version": "11.2", "reasoning": "ok"}\n```'),
    )

    assert _outcome(result)["source"] == "ai"


@pytest.mark.parametrize("http_code,response_body,expected", [
    ("402", '{"error": {"message": "credit balance is too low"}}', "HTTP 402"),
    ("500", "", "HTTP 500"),
    ("000", None, "never completed"),
    ("200", "<html>502</html>", "not a usable API payload"),
])
def test_cli_accept_ai_falls_back_when_the_api_fails(
    tmp_path: Path, http_code: str, response_body, expected: str
) -> None:
    result = _accept_ai_cli(tmp_path, http_code, response_body)
    outcome = _outcome(result)

    assert outcome["source"] == "fallback"
    assert expected in outcome["fallback_reason"]
    assert outcome["decision"] == {
        "release": True, "version": "11.2", "reasoning": outcome["decision"]["reasoning"],
    }


@pytest.mark.parametrize("flag", [
    "--connect-timeout",
    "--max-time",
    # --max-time restarts on every retry, so the total call is only bounded
    # when --retry-max-time is set alongside it.
    "--retry",
    "--retry-max-time",
])
def test_workflow_bounds_the_api_call(flag: str) -> None:
    """A hung API call would cancel the job, and a cancelled job never reaches
    the failure() issue step, so the release would vanish with no trace. With
    these flags curl reports 000 instead and the fallback takes over, and a
    transient rate limit is retried rather than costing the AI's verdict."""
    assert flag in api_call_command()


def test_workflow_reads_paths_without_git_quoting() -> None:
    """Escaped paths would not match the data model gate, so every git
    invocation the fallback reads paths from disables core.quotePath."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "git -c core.quotePath=false diff" in workflow
    assert "git -c core.quotePath=false log" in workflow
    assert "--name-only" in workflow


@pytest.mark.parametrize("text,expected", [
    ("Probably release 11.2, I think.", "single valid decision JSON"),
    ('{"release": false}\n{"release": false}', "single valid decision JSON"),
    ('{"release": null, "reasoning": "?"}', "boolean 'release'"),
    ('{"release": "yes", "reasoning": "?"}', "boolean 'release'"),
    ('{"release": true, "version": "11.1.0", "reasoning": "?"}', "not MAJOR.MINOR"),
    ('{"release": true, "version": "10.9", "reasoning": "?"}', "behind the last release"),
])
def test_cli_accept_ai_falls_back_on_an_unusable_answer(
    tmp_path: Path, text: str, expected: str
) -> None:
    """Every unusable answer degrades to the deterministic path, never exit 1."""
    result = _accept_ai_cli(tmp_path, "200", api_body(text))
    outcome = _outcome(result)

    assert outcome["source"] == "fallback"
    assert expected in outcome["fallback_reason"]
    assert outcome["decision"]["release"] is True
    # The rejected answer is logged, so a recurring misformat is diagnosable.
    assert text.splitlines()[0] in result.stderr


def test_cli_accept_ai_relays_a_decline_without_a_version(tmp_path: Path) -> None:
    result = _accept_ai_cli(
        tmp_path, "200", api_body('{"release": false, "reasoning": "nothing new"}')
    )
    outcome = _outcome(result)

    assert outcome["source"] == "ai"
    assert outcome["decision"] == {"release": False, "reasoning": "nothing new"}
    assert "version" not in outcome["decision"]


@pytest.mark.parametrize("tag", UNPARSEABLE_REAL_TAGS + ("vNope",))
def test_cli_accept_ai_keeps_a_good_ai_version_despite_an_unusable_baseline(
    tmp_path: Path, tag: str
) -> None:
    """A past tag named oddly must not cost the run its AI decision."""
    result = _accept_ai_cli(
        tmp_path,
        "200",
        api_body('{"release": true, "version": "11.2", "reasoning": "ok"}'),
        last_tag=tag,
    )
    outcome = _outcome(result)

    assert outcome["source"] == "ai"
    assert outcome["decision"]["version"] == "11.2"
    assert tag in result.stderr  # the skipped ordering check names the tag


@pytest.mark.parametrize("tag", UNPARSEABLE_REAL_TAGS + ("vNope",))
def test_cli_accept_ai_declines_without_failing_when_nothing_is_usable(
    tmp_path: Path, tag: str
) -> None:
    result = _accept_ai_cli(tmp_path, "402", "", last_tag=tag)
    outcome = _outcome(result)

    assert outcome["decision"]["release"] is False
    assert tag in outcome["decision"]["reasoning"]


def test_cli_accept_ai_declines_when_no_commit_touches_the_model(tmp_path: Path) -> None:
    result = _accept_ai_cli(
        tmp_path,
        "402",
        "",
        records_text=f"{RS}da004e4 Update curation task utils\n\nutils/x.py\n",
    )
    outcome = _outcome(result)

    assert outcome["decision"]["release"] is False
    assert "none touch the data model" in outcome["decision"]["reasoning"]


def test_cli_accept_ai_release_flag_is_a_json_boolean(tmp_path: Path) -> None:
    """
    The workflow writes `should_release=$(jq -r '.decision.release')` straight to
    $GITHUB_OUTPUT, so this must be exactly one line reading `true` or `false`.
    """
    for http_code, body in (
        ("200", api_body('{"release": false, "reasoning": "no"}')),
        ("402", ""),
    ):
        outcome = _outcome(_accept_ai_cli(tmp_path, http_code, body))
        assert isinstance(outcome["decision"]["release"], bool)


def test_cli_requires_a_subcommand() -> None:
    result = _run_cli([])

    assert result.returncode != 0
