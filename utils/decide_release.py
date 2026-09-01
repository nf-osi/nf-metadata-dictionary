#!/usr/bin/env python3
"""
Deterministic release decision, used as a fallback when the AI evaluation in
the Release workflow cannot be reached (API outage, exhausted credits, or a
malformed response).

Applies the same versioning rules the AI prompt states, but only ever proposes
a MINOR bump - MAJOR bumps need human judgement and must go through a manual
`workflow_dispatch` with an explicit version.

Emits the same JSON contract as the AI step so the rest of the pipeline does
not care which path decided:

    {"release": true, "version": "MAJOR.MINOR", "reasoning": "..."}
    {"release": false, "reasoning": "..."}

Release notes are deliberately omitted; the workflow falls back to GitHub's
--generate-notes when none are supplied.

Uses only the Python standard library - no extra pip installs required.

Usage:
    python decide_release.py --last-tag v11.1.22 --commits-file /tmp/commits.txt
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

# Commits produced by automation are not, on their own, a reason to release.
AUTOMATED_MARKERS = ("rebuild all artifacts", "[skip ci]")

# Matches a tag as MAJOR.MINOR with an optional leading "v" and optional PATCH.
TAG_PATTERN = re.compile(r"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?$")


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


def is_automated_commit(commit_line: str) -> bool:
    """True if a `git log --oneline` line came from automation."""
    subject = commit_line.lower()
    return any(marker in subject for marker in AUTOMATED_MARKERS)


def meaningful_commits(commit_lines: Iterable[str]) -> list:
    """Drop blank and automated lines, preserving the original order."""
    return [
        line for line in commit_lines
        if line.strip() and not is_automated_commit(line)
    ]


def decide(last_tag: str, commit_lines: Iterable[str]) -> dict:
    """
    Decide whether to release, and at what MAJOR.MINOR.

    Validates the tag before looking at commits so a malformed tag always
    raises, even when there is nothing to release.
    """
    parse_major_minor(last_tag)
    commit_lines = [line for line in commit_lines if line.strip()]
    relevant = meaningful_commits(commit_lines)

    if not relevant:
        detail = (
            f"all {len(commit_lines)} were automated rebuilds"
            if commit_lines
            else "the commit range is empty"
        )
        return {
            "release": False,
            "reasoning": f"No meaningful commits since {last_tag}; {detail}.",
        }

    version = next_minor_version(last_tag)
    return {
        "release": True,
        "version": version,
        "reasoning": (
            f"{len(relevant)} meaningful commit(s) since {last_tag}; "
            f"proposing a MINOR bump to {version} "
            "(deterministic fallback, AI evaluation unavailable)."
        ),
    }


def read_commit_lines(path: Path) -> list:
    """
    Read commit subjects from a file.

    A missing file means the workflow found nothing to summarize, which is a
    "nothing to release" signal - not a reason to break the pipeline.
    """
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decide whether to cut a release without calling the AI evaluator."
    )
    parser.add_argument(
        "--last-tag",
        required=True,
        help="Most recent release tag, e.g. v11.1.22",
    )
    parser.add_argument(
        "--commits-file",
        required=True,
        type=Path,
        help="File of `git log --oneline` lines since --last-tag",
    )
    args = parser.parse_args()

    try:
        decision = decide(args.last_tag, read_commit_lines(args.commits_file))
    except ValueError as error:
        print(f"❌ {error}", file=sys.stderr)
        return 1

    print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    sys.exit(main())
