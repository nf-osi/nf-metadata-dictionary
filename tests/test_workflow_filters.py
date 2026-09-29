"""The PR workflow's trigger paths and its `changes` filters must stay in sync.

main-ci.yml triggers on a set of paths and then gates every job on a dorny/paths-filter
`changes` job.  If a path can trigger the workflow but matches no filter, the run starts,
every job skips, and the PR reports green with nothing having been checked -- which is
indistinguishable from a passing run.  That happened once: the trigger was widened to
`tests/**` and `utils/**` while the filters still named individual files, leaving seven
paths that triggered a run in which nothing executed.

These tests are pure YAML/glob reasoning, so they need no build artifacts.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main-ci.yml"


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _on_block(wf):
    # PyYAML resolves a bare `on:` key to the boolean True.
    return wf.get("on", wf.get(True))


def _trigger_paths(wf):
    return _on_block(wf)["pull_request"]["paths"]


def _filters(wf):
    step = next(
        s for s in wf["jobs"]["changes"]["steps"] if s.get("id") == "filter"
    )
    return yaml.safe_load(step["with"]["filters"])


def _covers(pattern, target):
    """Whether `pattern` subsumes every file `target` can match.

    Directional on purpose. The question is not "do these two overlap" but "is everything
    the trigger admits also caught by a filter" -- so `utils/gen-json-schema-class.py`
    does NOT cover `utils/**`, even though a file exists that both match. An earlier
    version of this helper compared both directions and therefore passed on exactly the
    bug it was written to catch.
    """
    if pattern == target:
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return target == prefix or target.startswith(prefix + "/")
    return False


def test_every_trigger_path_matches_at_least_one_filter():
    wf = _workflow()
    filters = _filters(wf)
    uncovered = [
        p for p in _trigger_paths(wf)
        if not any(_covers(pat, p) for pats in filters.values() for pat in pats)
    ]
    assert not uncovered, (
        "These paths trigger main-ci but match no `changes` filter, so the workflow "
        f"would run with every job skipped and report green: {uncovered}. Either add "
        "them to a filter or remove them from the trigger."
    )


def test_every_filter_path_can_be_triggered():
    """The converse: a filter that no trigger can reach is dead configuration."""
    wf = _workflow()
    triggers = _trigger_paths(wf)
    unreachable = {
        name: [p for p in pats if not any(_covers(p, t) for t in triggers)]
        for name, pats in _filters(wf).items()
    }
    unreachable = {k: v for k, v in unreachable.items() if v}
    assert not unreachable, (
        f"Filter patterns that no trigger path can reach: {unreachable}. "
        "They will never evaluate true; add the path to on.pull_request.paths."
    )


def test_build_needed_reflects_the_filters_that_gate_build():
    """`build_needed` is the single gate for the artifact-dependent jobs."""
    wf = _workflow()
    expr = wf["jobs"]["changes"]["outputs"]["build_needed"]
    for name in ("model", "generator"):
        assert f"steps.filter.outputs.{name}" in expr, (
            f"`{name}` affects generated artifacts but is not part of build_needed: {expr}"
        )


@pytest.mark.parametrize("job", [
    "changes", "build", "analyze", "docs-preview",
    "pytest", "unit-tests", "check-schema-limits", "report",
])
def test_every_job_declares_a_runner(job):
    """A job missing `runs-on` makes the whole workflow file invalid, not just that job."""
    jobs = _workflow()["jobs"]
    assert job in jobs, f"job `{job}` is gone; update this test if that was deliberate"
    assert jobs[job].get("runs-on"), f"job `{job}` has no runs-on"


def test_changes_outputs_survive_workflow_dispatch():
    """Every `changes` output must fall back to true on a manual dispatch.

    paths-filter only runs on pull_request (on any other event it shells out to git,
    and the job has no checkout). So on workflow_dispatch every `steps.filter.outputs.*`
    is empty, and an output without the fallback silently gates its jobs off -- a manual
    run that appears to succeed while doing nothing.
    """
    outputs = _workflow()["jobs"]["changes"]["outputs"]
    missing = [
        name for name, expr in outputs.items()
        if "workflow_dispatch" not in expr
    ]
    assert not missing, (
        f"`changes` outputs with no workflow_dispatch fallback: {missing}. "
        "Add `|| github.event_name == 'workflow_dispatch'` or the jobs they gate "
        "will skip on every manual run."
    )


def test_paths_filter_step_is_pull_request_only():
    """Guard the reason the fallback above is needed."""
    step = next(
        s for s in _workflow()["jobs"]["changes"]["steps"]
        if s.get("id") == "filter"
    )
    assert "pull_request" in step.get("if", ""), (
        "The paths-filter step must be gated to pull_request. On other events it calls "
        "getChangedFilesFromGit -> `git branch --show-current`, and the changes job has "
        "no actions/checkout, so the step fails and every downstream job skips."
    )


def test_analyze_is_pull_request_gated():
    """`analyze` runs `git checkout "$HEAD_REF"`, which is empty on a manual dispatch."""
    condition = str(_workflow()["jobs"]["analyze"].get("if", ""))
    assert "pull_request" in condition, (
        "`analyze` diffs the PR head against main and checks out the head ref, which "
        f"does not exist on a workflow_dispatch. Current condition: {condition!r}"
    )
