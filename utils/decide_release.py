#!/usr/bin/env python3
"""
Deterministic release decision, used as a fallback when the AI evaluation in
the Release workflow cannot be reached (API outage, exhausted credits, or a
malformed response).

Applies the same versioning rules the AI prompt states, but only ever proposes
a MINOR bump - MAJOR bumps need human judgement and must go through a manual
`workflow_dispatch` with an explicit version.

A release is proposed only when both hold: there are non-automated commits,
and those commits touch the data model or the code that generates it. Docs, CI
and unrelated tooling churn alone must not push a tag and burn a Synapse schema
version.

Emits the same JSON contract as the AI step so the rest of the pipeline does
not care which path decided:

    {"release": true, "version": "MAJOR.MINOR", "reasoning": "..."}
    {"release": false, "reasoning": "..."}

Release notes are deliberately omitted; the workflow falls back to GitHub's
--generate-notes when none are supplied.

Also validates a version proposed by either path, so a decision that would tag
something malformed or behind the last release can be rejected before any tag
is pushed.

Uses only the Python standard library - no extra pip installs required.

Usage:
    git log v11.1.22..HEAD --no-merges --name-only --format='%x1e%h %s' \
      > /tmp/commit_paths.txt
    python decide_release.py decide \
      --last-tag v11.1.22 --commit-paths-file /tmp/commit_paths.txt
    python decide_release.py check-version --last-tag v11.1.22 --version 11.2
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
TAG_PATTERN = re.compile(r"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?$")

# A decided version is MAJOR.MINOR exactly; PATCH is the workflow run number.
VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

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


def version_error(version: str, last_tag: str) -> str:
    """
    Return why `version` cannot be released after `last_tag`, or "" if it can.

    Rejects anything that is not MAJOR.MINOR, and anything that would move the
    series backwards - `gh release list` orders by creation date, so a
    backwards release becomes the baseline for every later decision.
    """
    candidate = (version or "").strip()
    if not VERSION_PATTERN.match(candidate):
        return f"version {version!r} is not MAJOR.MINOR"
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


def is_schema_relevant(path: str) -> bool:
    """True if a changed path can affect the published data model."""
    normalized = path.strip()
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

    Validates the tag before looking at commits so a malformed tag always
    raises, even when there is nothing to release.
    """
    parse_major_minor(last_tag)
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


def read_commit_records(path: Path) -> list:
    """
    Read commit records from a file.

    A missing file means the workflow found nothing to summarize, which is a
    "nothing to release" signal - not a reason to break the pipeline.
    """
    if not path.exists():
        return []
    return parse_commit_records(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decide whether to cut a release without calling the AI evaluator."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    decide_parser = subparsers.add_parser(
        "decide", help="Print the release decision as JSON"
    )
    decide_parser.add_argument(
        "--last-tag",
        required=True,
        help="Most recent release tag, e.g. v11.1.22",
    )
    decide_parser.add_argument(
        "--commit-paths-file",
        required=True,
        type=Path,
        help=(
            "File of `git log --no-merges --name-only --format='%%x1e%%h %%s'` "
            "records since --last-tag"
        ),
    )

    check_parser = subparsers.add_parser(
        "check-version",
        help="Exit non-zero if a proposed MAJOR.MINOR is unusable for a release",
    )
    check_parser.add_argument(
        "--last-tag",
        required=True,
        help="Most recent release tag, e.g. v11.1.22",
    )
    check_parser.add_argument(
        "--version",
        required=True,
        help="Proposed MAJOR.MINOR version, e.g. 11.2",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.command == "check-version":
            error = version_error(args.version, args.last_tag)
            if error:
                print(f"❌ {error}", file=sys.stderr)
                return 1
            return 0

        decision = decide(args.last_tag, read_commit_records(args.commit_paths_file))
    except ValueError as error:
        print(f"❌ {error}", file=sys.stderr)
        return 1

    print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    sys.exit(main())
