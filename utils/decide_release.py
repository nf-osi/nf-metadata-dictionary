#!/usr/bin/env python3
"""
Release decision for the Release workflow: judges the AI evaluator's answer and
decides deterministically instead whenever that answer cannot be used (API
outage, exhausted credits, or a malformed response).

The deterministic path applies the commit and path rules the AI prompt states,
and only ever proposes a MINOR bump - MAJOR bumps need human judgement and must
go through a manual `workflow_dispatch` with an explicit version. It
deliberately does not reproduce the prompt's rules that depend on Synapse
registration state; that comes from a network call the workflow tolerates
failing, so the decision here rests on the git history alone.

A release is proposed only when both hold: there are non-automated commits,
and those commits touch the data model or the code that generates it. Docs, CI
and unrelated tooling churn alone must not push a tag and burn a Synapse schema
version.

Both paths emit the same JSON contract so the rest of the pipeline does not
care which one decided:

    {"release": true, "version": "MAJOR.MINOR", "reasoning": "...", "notes": "..."}
    {"release": false, "reasoning": "..."}

On the deterministic path release notes are omitted; the workflow falls back to
GitHub's --generate-notes when none are supplied.

Every version that reaches the workflow is validated here, so a decision that
would tag something malformed or behind the last release is rejected before any
tag is pushed. An unusable version from the AI is just another reason to fall
back; one from the deterministic path cannot happen and is a hard failure.

Uses only the Python standard library - no extra pip installs required.

Usage:
    git -c core.quotePath=false log v11.1.22..HEAD --no-merges \
      --name-only --format='%x1e%h %s' > /tmp/commit_paths.txt
    python decide_release.py accept-ai \
      --last-tag v11.1.22 --http-code 200 \
      --response-file /tmp/api_response.json \
      --commit-paths-file /tmp/commit_paths.txt
    python decide_release.py decide \
      --last-tag v11.1.22 --commit-paths-file /tmp/commit_paths.txt
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

# Commits produced by automation are not, on their own, a reason to release.
AUTOMATED_MARKERS = ("rebuild all artifacts", "[skip ci]")

# Matches a tag as MAJOR.MINOR with an optional leading "v" and optional PATCH.
# `\Z` rather than `$` so a trailing newline cannot sneak through a match.
TAG_PATTERN = re.compile(r"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?\Z")

# A decided version is MAJOR.MINOR exactly; PATCH is the workflow run number.
VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")

# curl reports no HTTP status when the request never reached the API.
CURL_FAILURE_CODE = "000"

# The API reports this when a response was cut off at the token cap.
MAX_TOKENS_STOP_REASON = "max_tokens"

# `git log --format='%x1e...'` prefixes each commit with an ASCII record
# separator, so subject lines can never be confused with `--name-only` paths.
RECORD_SEPARATOR = "\x1e"

# Only changes under these locations affect what gets registered in Synapse.
# modules/ and header.yaml are the LinkML source the model is built from,
# rules/ supplies the Superdataset overlay, and gen-json-schema-class.py is the
# generator itself - a change to any of them rewrites published schemas. dist/
# and registered-json-schemas/ are those generated artifacts.
SCHEMA_RELEVANT_DIRS = ("modules", "rules", "dist", "registered-json-schemas")
SCHEMA_RELEVANT_FILES = ("header.yaml", "utils/gen-json-schema-class.py")


@dataclass(frozen=True)
class CommitRecord:
    """One commit from the release range, with the paths it touched."""

    sha: str
    subject: str
    paths: tuple

    @property
    def is_automated(self) -> bool:
        return is_automated_commit(self.subject)


def parse_major_minor(tag: str) -> tuple:
    """
    Parse a release tag into its (MAJOR, MINOR) pair.

    Raises ValueError on anything that is not recognisably a release tag,
    rather than guessing - a wrong guess here would tag and publish a
    release at the wrong version.
    """
    match = TAG_PATTERN.match((tag or "").strip())
    if not match:
        raise ValueError(
            f"Cannot parse release tag {tag!r}; expected MAJOR.MINOR[.PATCH] "
            "with an optional leading 'v' (e.g. v11.1.22)"
        )
    return int(match.group(1)), int(match.group(2))


def next_minor_version(tag: str) -> str:
    """Return the next MAJOR.MINOR after the given tag, e.g. v10.9.15 -> 10.10."""
    major, minor = parse_major_minor(tag)
    return f"{major}.{minor + 1}"


def baseline_error(tag: str) -> str:
    """
    Return why `tag` is unusable as a release baseline, or "" if it is usable.

    This repo has published tags like "10.08.0" and "v.6.2.0", and
    `gh release list` returns the newest by date, so an unparseable baseline is
    a real possibility that callers have to degrade around rather than crash on.
    """
    try:
        parse_major_minor(tag)
    except ValueError as error:
        return str(error)
    return ""


def version_error(version: str, last_tag: str) -> str:
    """
    Return why `version` cannot be released after `last_tag`, or "" if it can.

    Rejects anything that is not MAJOR.MINOR, and anything that would move the
    series backwards - `gh release list` orders by creation date, so a
    backwards release becomes the baseline for every later decision.

    An unparseable `last_tag` says nothing about `version`, so the ordering half
    of the check is skipped rather than blaming a perfectly usable version for a
    baseline it cannot be compared against.
    """
    candidate = (version or "").strip()
    if not VERSION_PATTERN.match(candidate):
        return f"version {version!r} is not MAJOR.MINOR"
    if baseline_error(last_tag):
        return ""
    if parse_major_minor(candidate) < parse_major_minor(last_tag):
        return (
            f"version {candidate!r} is behind the last release {last_tag!r}; "
            "releases must not move the series backwards"
        )
    return ""


def is_automated_commit(subject: str) -> bool:
    """True if a commit subject came from automation."""
    lowered = subject.lower()
    return any(marker in lowered for marker in AUTOMATED_MARKERS)


def unquote_git_path(path: str) -> str:
    """
    Undo the C-style quoting `git log --name-only` applies to awkward paths.

    The workflow passes `core.quotePath=false`, which covers non-ASCII bytes,
    but git still quotes a path holding a double quote or a control character.
    A quoted path starts with `"` rather than a directory name, so leaving it
    escaped would fail the data model gate and silently decline a real release.
    """
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    escaped = path[1:-1]
    try:
        return (
            escaped.encode("latin-1", "backslashreplace")
            .decode("unicode_escape")
            .encode("latin-1")
            .decode("utf-8", "replace")
        )
    except (UnicodeDecodeError, UnicodeEncodeError):
        return escaped


def is_schema_relevant(path: str) -> bool:
    """True if a changed path can affect the published data model."""
    normalized = unquote_git_path(path.strip())
    if not normalized:
        return False
    parts = PurePosixPath(normalized).parts
    return parts[0] in SCHEMA_RELEVANT_DIRS or normalized in SCHEMA_RELEVANT_FILES


def parse_commit_records(text: str) -> list:
    """
    Parse `git log --no-merges --name-only --format='%x1e%h %s'` output.

    Each record is the separator, a `<sha> <subject>` line, then the paths the
    commit touched.
    """
    records = []
    for chunk in text.split(RECORD_SEPARATOR):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        header, paths = lines[0], lines[1:]
        sha, _, subject = header.partition(" ")
        records.append(CommitRecord(sha=sha, subject=subject, paths=tuple(paths)))
    return records


def meaningful_records(records: Iterable) -> list:
    """Drop automated commits, preserving the original order."""
    return [record for record in records if not record.is_automated]


def schema_relevant_paths(records: Iterable) -> list:
    """Sorted, de-duplicated data model paths touched by the given commits."""
    return sorted({
        path
        for record in records
        for path in record.paths
        if is_schema_relevant(path)
    })


def decide(last_tag: str, records: Iterable) -> dict:
    """
    Decide whether to release, and at what MAJOR.MINOR.

    An unusable baseline tag leaves no MINOR to bump, so this declines with a
    reason naming the tag instead of raising: this runs as the last line of
    defence for the release cadence, and failing here would block the run the
    fallback exists to keep going.
    """
    unusable_baseline = baseline_error(last_tag)
    if unusable_baseline:
        return {
            "release": False,
            "reasoning": (
                "Cannot determine the next version deterministically: "
                f"{unusable_baseline}. Dispatch the workflow manually with an "
                "explicit version to release."
            ),
        }

    records = list(records)
    relevant = meaningful_records(records)

    if not relevant:
        detail = (
            f"all {len(records)} were automated rebuilds"
            if records
            else "the commit range is empty"
        )
        return {
            "release": False,
            "reasoning": f"No meaningful commits since {last_tag}; {detail}.",
        }

    # Only the meaningful commits are inspected: automated rebuilds always
    # touch dist/ and registered-json-schemas/, so including them would make
    # this gate trivially true.
    touched = schema_relevant_paths(relevant)
    if not touched:
        locations = ", ".join(
            [f"{name}/" for name in SCHEMA_RELEVANT_DIRS] + list(SCHEMA_RELEVANT_FILES)
        )
        return {
            "release": False,
            "reasoning": (
                f"{len(relevant)} meaningful commit(s) since {last_tag}, but none "
                f"touch the data model ({locations}); there is nothing new to "
                "register in Synapse."
            ),
        }

    version = next_minor_version(last_tag)
    return {
        "release": True,
        "version": version,
        "reasoning": (
            f"{len(relevant)} meaningful commit(s) since {last_tag} touching "
            f"{len(touched)} data model file(s); proposing a MINOR bump to {version} "
            "(deterministic fallback, AI evaluation unavailable)."
        ),
    }


class AiUnusable(Exception):
    """
    The AI evaluation cannot be used, so the deterministic path must decide.

    Every rejection is this, never a hard failure: an evaluator that cannot
    answer must not be the reason the release cadence stops.
    """


@dataclass(frozen=True)
class Outcome:
    """Which path decided, what it decided, and what the AI actually said."""

    decision: dict
    fallback_reason: str
    ai_text: str

    @property
    def source(self) -> str:
        return "fallback" if self.fallback_reason else "ai"


def strip_code_fences(text: str) -> str:
    """Drop markdown fence lines, which the model adds despite being asked not to."""
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("```")
    )


def content_block_text(content: Iterable) -> str:
    """
    Return the text carried by an Anthropic response's content blocks.

    The answer is not necessarily the first block: a leading `thinking` or
    server tool-use block would otherwise look like an unusable payload and
    silently route every run to the deterministic path.
    """
    carrying_text = [
        block
        for block in content
        if isinstance(block, dict)
        and isinstance(block.get("text"), str)
        and block["text"].strip()
    ]
    for block in carrying_text:
        if block.get("type") == "text":
            return block["text"]
    return carrying_text[0]["text"] if carrying_text else ""


def ai_response_text(http_code: str, response_body: str) -> str:
    """
    Extract the model's answer from a raw Anthropic API response.

    Raises AiUnusable for anything that is not a successful, well-formed
    response carrying a complete answer.
    """
    code = (http_code or "").strip()
    if not code or code == CURL_FAILURE_CODE:
        raise AiUnusable(
            "the AI evaluation request never completed (no HTTP status; DNS, "
            "network failure or timeout)"
        )
    if code != "200":
        raise AiUnusable(f"the AI evaluation request failed with HTTP {code}")

    try:
        payload = json.loads(response_body)
        content = payload["content"]
        stop_reason = payload.get("stop_reason")
        if not isinstance(content, list):
            raise TypeError("content is not a list of blocks")
    except (ValueError, TypeError, KeyError, AttributeError):
        raise AiUnusable(
            "the AI returned HTTP 200 but the response body was not a usable "
            "API payload"
        )

    # A response cut off at the token cap carries a half-written decision, so
    # name truncation rather than reporting it as a misformatted answer.
    if stop_reason == MAX_TOKENS_STOP_REASON:
        raise AiUnusable(
            f"the AI response was truncated (stop_reason: {MAX_TOKENS_STOP_REASON}); "
            "raise max_tokens in the workflow if this recurs"
        )

    text = content_block_text(content)
    if not text.strip():
        raise AiUnusable("the AI returned HTTP 200 but the response carried no text")
    return text


def ai_decision(text: str, last_tag: str) -> dict:
    """
    Turn the model's answer into a decision, or raise AiUnusable.

    Rebuilt field by field rather than passed through, so only validated values
    reach the workflow. `release` must be a real boolean - a null or "yes" would
    sail past a looser check and then silently decline the release. A version
    that is malformed or behind the last release is the model's mistake, not a
    pipeline fault, so it falls back like any other unusable answer.
    """
    try:
        raw = json.loads(strip_code_fences(text))
    except ValueError:
        raise AiUnusable(
            "the AI response was not a single valid decision JSON document"
        )
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), bool):
        raise AiUnusable("the AI response carried no boolean 'release' field")

    reasoning = raw.get("reasoning")
    decision = {
        "release": raw["release"],
        "reasoning": reasoning if isinstance(reasoning, str) else "",
    }
    if not raw["release"]:
        return decision

    version = raw.get("version") if isinstance(raw.get("version"), str) else ""
    error = version_error(version, last_tag)
    if error:
        raise AiUnusable(f"the AI proposed an unusable version ({error})")

    decision["version"] = version.strip()
    notes = raw.get("notes")
    if isinstance(notes, str) and notes.strip():
        decision["notes"] = notes
    return decision


def resolve_decision(
    http_code: str, response_body: str, last_tag: str, records: Iterable
) -> Outcome:
    """Prefer the AI's decision; fall back to the deterministic one otherwise."""
    text = ""
    try:
        text = ai_response_text(http_code, response_body)
        return Outcome(
            decision=ai_decision(text, last_tag), fallback_reason="", ai_text=text
        )
    except AiUnusable as unusable:
        return Outcome(
            decision=decide(last_tag, records),
            fallback_reason=str(unusable),
            ai_text=text,
        )


def releasability_error(decision: dict, last_tag: str) -> str:
    """
    Return why a decision cannot be acted on, or "" if it can.

    Defence in depth only: an unusable version from the AI has already become a
    fallback, and the deterministic path cannot emit one, so a non-empty result
    here means this module is broken - and tagging garbage is worse than failing.
    """
    if not decision.get("release"):
        return ""
    return version_error(decision.get("version", ""), last_tag)


def read_text_or_empty(path: Path) -> str:
    """
    Read a file the workflow may not have produced.

    Every input this module reads is workflow-generated and outside its control:
    a missing file, an unreadable one, or a commit subject carrying raw non-UTF-8
    bytes is one more reason to fall back, never a reason to abort the release
    step. So decode leniently and treat any read failure as absent content.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_commit_records(path: Path) -> list:
    """
    Read commit records from a file.

    A missing file means the workflow found nothing to summarize, which is a
    "nothing to release" signal - not a reason to break the pipeline.
    """
    return parse_commit_records(read_text_or_empty(path))


def add_range_arguments(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--last-tag",
        required=True,
        help="Most recent release tag, e.g. v11.1.22",
    )
    subparser.add_argument(
        "--commit-paths-file",
        required=True,
        type=Path,
        help=(
            "File of `git log --no-merges --name-only --format='%%x1e%%h %%s'` "
            "records since --last-tag"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decide whether to cut a release, with or without the AI evaluator."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    accept_parser = subparsers.add_parser(
        "accept-ai",
        help=(
            "Print {source, fallback_reason, decision} from an AI response, "
            "deciding deterministically if that response is unusable"
        ),
    )
    add_range_arguments(accept_parser)
    accept_parser.add_argument(
        "--http-code",
        required=True,
        help=f"HTTP status curl reported, or {CURL_FAILURE_CODE} if it failed",
    )
    accept_parser.add_argument(
        "--response-file",
        required=True,
        type=Path,
        help="File holding the raw Anthropic API response body",
    )

    decide_parser = subparsers.add_parser(
        "decide", help="Print the deterministic release decision as JSON"
    )
    add_range_arguments(decide_parser)
    return parser


def report_diagnostics(outcome: Outcome, last_tag: str, response_body: str) -> None:
    """
    Log what the model said and how it was judged.

    Everything goes to stderr so stdout stays a single machine-readable
    document. The model's answer is logged whether it was used or rejected, so a
    recurring misformat is diagnosable from the run page.
    """
    if outcome.ai_text:
        print("Claude's evaluation:", file=sys.stderr)
        print(outcome.ai_text, file=sys.stderr)
    elif response_body.strip():
        print("AI response body:", file=sys.stderr)
        print(response_body, file=sys.stderr)

    if outcome.fallback_reason:
        print(
            f"⚠️  Falling back to deterministic rules: {outcome.fallback_reason}.",
            file=sys.stderr,
        )
        return

    unusable_baseline = baseline_error(last_tag)
    if unusable_baseline:
        print(f"⚠️  Ordering check skipped: {unusable_baseline}", file=sys.stderr)


def main() -> int:
    args = build_parser().parse_args()
    records = read_commit_records(args.commit_paths_file)

    if args.command == "decide":
        print(json.dumps(decide(args.last_tag, records)))
        return 0

    response_body = read_text_or_empty(args.response_file)
    outcome = resolve_decision(
        args.http_code, response_body, args.last_tag, records
    )
    report_diagnostics(outcome, args.last_tag, response_body)

    unreleasable = releasability_error(outcome.decision, args.last_tag)
    if unreleasable:
        print(f"❌ Refusing to release: {unreleasable}", file=sys.stderr)
        return 1

    print(json.dumps({
        "source": outcome.source,
        "fallback_reason": outcome.fallback_reason,
        "decision": outcome.decision,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
