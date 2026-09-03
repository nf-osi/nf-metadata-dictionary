#!/usr/bin/env python3
"""
Tests for the annotation key audit's coverage honesty and its reports.

Offline: the Synapse surfaces are served from in-memory stubs and the allowlist
baseline is generated from a state file, which is how a curator regenerates it
without credentials.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import yaml

utils_path = os.path.join(os.path.dirname(__file__), '..', 'utils')
sys.path.insert(0, utils_path)

import annotation_key_policy as policy  # noqa: E402
import audit_annotation_keys as audit  # noqa: E402
import synapse_annotation_io as io  # noqa: E402

FILE_TYPE = 'org.sagebionetworks.repo.model.FileEntity'
FOLDER_TYPE = 'org.sagebionetworks.repo.model.Folder'


class ServiceUnavailable(Exception):
    """A 503 as the retry policy sees it: a response carrying a retryable status."""

    def __init__(self, status_code=503):
        super().__init__(f'{status_code} Service Unavailable')

        class _Response:
            pass

        self.response = _Response()
        self.response.status_code = status_code


# ---------------------------------------------------------------------------
# Table query pagination
# ---------------------------------------------------------------------------

class TableQueryStub:
    """The async table-query surface, serving one scripted page per request."""

    def __init__(self, pages):
        self.pages = pages          # [(row_ids, next_page_token), ...]
        self.requests = []          # (path, body) per started job

    def restPOST(self, path, body=None):
        self.requests.append((path, json.loads(body)))
        return {'token': f'job{len(self.requests)}'}

    def restGET(self, path):
        rows, token = self.pages[len(self.requests) - 1]
        page = {
            'queryResults': {
                'headers': [{'name': 'studyId'}, {'name': 'studyName'},
                            {'name': 'studyStatus'}],
                'rows': [{'values': [row, f'{row} study', 'Active']} for row in rows],
            },
        }
        if token:
            page['nextPageToken'] = token
        # The first page arrives inside a query bundle; later pages do not.
        if 'nextPage' in path:
            return {'jobState': 'COMPLETE', **page}
        return {'jobState': 'COMPLETE', 'queryResult': page}


def test_a_table_query_follows_every_page():
    # list_portal_projects is the only caller: a truncated first page would make
    # the audit report full coverage over a subset of the portal, which is exactly
    # the silent failure the coverage-first reporting exists to prevent.
    syn = TableQueryStub([(['syn1', 'syn2'], 'page-2'), (['syn3'], None)])
    projects = audit.list_portal_projects(syn, 'syn9')
    assert [p['project_id'] for p in projects] == ['syn1', 'syn2', 'syn3']
    assert syn.requests[1][0] == '/entity/syn9/table/query/nextPage/async/start'
    assert syn.requests[1][1]['token'] == 'page-2'


def test_a_table_query_that_never_stops_paging_fails_loudly():
    class Endless(TableQueryStub):
        def restGET(self, path):
            page = {'queryResults': {'headers': [], 'rows': []}, 'nextPageToken': 'more'}
            if 'nextPage' in path:
                return {'jobState': 'COMPLETE', **page}
            return {'jobState': 'COMPLETE', 'queryResult': page}

    with pytest.raises(RuntimeError, match='pagination did not terminate'):
        audit.query_table(Endless([]), 'syn9', 'SELECT studyId FROM syn9', max_pages=3)


# ---------------------------------------------------------------------------
# A lost entity read is a finding, not a skip
# ---------------------------------------------------------------------------

class ChildrenStub:
    def __init__(self, tree):
        self.tree = tree

    def restPOST(self, path, body=None):
        assert path == '/entity/children'
        return {'page': self.tree.get(json.loads(body)['parentId'], [])}


def _flagged_audit(project_id='syn0'):
    result = audit.ProjectAudit(project_id=project_id, status='ok')
    result.summary = {'duplicates': {'Age': 'age'}, 'orphans': {}, 'case_variants': {},
                      'reserved': {}, 'near_misses': {}}
    result.key_types = {'Age': ['DOUBLE'], 'age': ['DOUBLE']}
    return result


def test_a_drill_down_read_gets_the_retry_budget_and_a_lost_one_is_recorded(monkeypatch):
    # entity_findings.jsonl is the only input fix_annotation_keys.py --findings
    # reads, so an entity dropped from it is a real finding that can never be
    # repaired. audit_project already treats a failed read as a finding; the
    # drill-down used to only log it.
    canon = frozenset({'age'})
    index = policy.KeyIndex.build(canon)
    syn = ChildrenStub({'syn0': [{'id': 'file1', 'name': 'file1', 'type': FILE_TYPE},
                                 {'id': 'file2', 'name': 'file2', 'type': FILE_TYPE}]})
    attempts = []

    def read(_syn, entity_id, *, max_retries=0):
        attempts.append((entity_id, max_retries))
        if entity_id == 'file2':
            raise RuntimeError('503 Service Unavailable')
        return io.AnnotationRecord(entity_id, 'etag-1', {'Age': [1.5], 'age': [1.5]},
                                   {'Age': 'DOUBLE', 'age': 'DOUBLE'})

    monkeypatch.setattr(audit, 'read_annotations', read)
    project = _flagged_audit()
    findings = audit.drill_down_project(syn, project, canon=canon, index=index,
                                        workers=1, max_retries=4)

    assert [f['entity_id'] for f in findings] == ['file1']
    assert {retries for _entity, retries in attempts} == {4}
    assert [f['entity_id'] for f in project.read_failures] == ['file2']


def test_a_listing_lost_after_retries_is_recorded_rather_than_read_as_an_empty_project(
        monkeypatch):
    # The worst case of the coverage invariant: a single transient 503 on a
    # project's root made the walk yield nothing, so the project contributed no rows
    # to entity_findings.jsonl - the fix tool's only input - while the same report
    # listed it as affected, said "Entity reads lost after retries: 0" and exited 0.
    monkeypatch.setattr(io.time, 'sleep', lambda _seconds: None)
    canon = frozenset({'age'})
    index = policy.KeyIndex.build(canon)
    attempts = []

    class UnlistableRoot:
        def restPOST(self, path, body=None):
            attempts.append(json.loads(body)['parentId'])
            raise ServiceUnavailable()

    project = _flagged_audit()
    findings = audit.drill_down_project(UnlistableRoot(), project, canon=canon, index=index,
                                        workers=1, max_retries=2)

    assert findings == []
    assert attempts == ['syn0'] * 3, 'a listing gets the same retry budget as a read'
    assert [f['entity_id'] for f in project.read_failures] == ['syn0']
    assert 'could not list children' in project.read_failures[0]['error']
    assert audit.exit_code_for([project], fail_on_findings=False, max_unscanned=0) == 2


@pytest.mark.parametrize('workers', [1, 4])
def test_the_drill_down_loop_is_guarded_by_the_circuit_breaker(monkeypatch, workers):
    # The largest per-entity network loop in the tooling - 13,150 entities on the
    # recorded scan - and the last one without an abort guard. With a retry budget
    # and no guard, a degradation confined to /annotations2 has every read pay the
    # full jittered backoff, which is over a day of grinding to reach a state file
    # that is nothing but read failures.
    canon = frozenset({'age'})
    index = policy.KeyIndex.build(canon)
    tree = {'syn0': [{'id': f'file{n}', 'name': f'file{n}', 'type': FILE_TYPE}
                     for n in range(400)]}
    reads = []

    def read(_syn, entity_id, **_kwargs):
        reads.append(entity_id)
        raise RuntimeError('503 Service Unavailable')

    monkeypatch.setattr(audit, 'read_annotations', read)
    project = _flagged_audit()
    audit.drill_down_project(ChildrenStub(tree), project, canon=canon, index=index,
                             workers=workers)

    # Sequentially it stops at the floor, one slot of which the project's own
    # successful children listing occupies - listings are requests, so they are
    # sampled too; threaded, it stops at the end of the chunk that tripped it.
    # Either way it is nowhere near the 400 the project holds.
    chunk = max(workers * 8, 64) if workers > 1 else io.ERROR_FLOOR - 1
    assert len(reads) == chunk
    # The entities it never inspected are absent from entity_findings.jsonl just as
    # surely as the ones whose read failed, so the abort is lost coverage too.
    aborts = [f for f in project.read_failures if 'aborted' in f['error']]
    assert [f['entity_id'] for f in aborts] == ['syn0']
    assert audit.exit_code_for([project], fail_on_findings=False, max_unscanned=0) == 2


def test_a_lost_entity_read_reaches_the_reports_and_the_exit_code(tmp_path):
    project = _flagged_audit()
    project.read_failures = [{'entity_id': 'file2', 'entity_type': 'FileEntity',
                              'error': 'RuntimeError: 503 Service Unavailable'}]

    stats = audit.build_summary([project])
    assert stats['entity_read_failures'] == 1
    assert stats['entity_reads_lost'][0]['project_id'] == 'syn0'

    report = audit.format_markdown([project])
    assert 'Entity reads lost after retries: **1**' in report
    assert 'file2' in report

    audit.write_reports([project], tmp_path)
    projects_csv = (tmp_path / 'annotation_key_audit_projects.csv').read_text()
    assert 'read_failures' in projects_csv.splitlines()[0]

    # Lost coverage spends the same budget as an unreadable project rather than
    # passing silently.
    assert audit.exit_code_for([project], fail_on_findings=False, max_unscanned=0) == 2
    assert audit.exit_code_for([project], fail_on_findings=False, max_unscanned=1) == 0


def test_carrying_a_project_forward_keeps_a_lost_read_nothing_has_re_verified():
    # carry_forward runs before anything knows which projects this run will read,
    # so it must not decide that a gap has been closed. Dropping the failure here
    # let a --resume report better coverage than it had - exit 0 and "0 reads lost"
    # with nothing having re-read the entity - while the state file it was built
    # from still recorded the gap.
    stale = _flagged_audit('syn1')
    stale.read_failures = [{'entity_id': 'syn1', 'entity_type': 'Project',
                            'error': 'RuntimeError: 503'}]
    carried = audit.carry_forward({'syn1': stale}, [])

    assert [a.project_id for a in carried] == ['syn1']
    assert [f['entity_id'] for f in carried[0].read_failures] == ['syn1']
    assert audit.exit_code_for(carried, fail_on_findings=False, max_unscanned=0) == 2


def test_the_drill_down_breaker_spans_the_run_rather_than_one_project(tmp_path, monkeypatch):
    # A breaker built per project gave every project a fresh window, so a systemic
    # degradation cost one breaker's worth of doomed reads per project - about ten
    # minutes each, nine hours across the 53 flagged projects on the recorded scan -
    # when the whole point of the guard is that one systemic failure stops the run.
    reads = []

    def read(_syn, entity_id, **_kwargs):
        reads.append(entity_id)
        raise RuntimeError('503 Service Unavailable')

    monkeypatch.setattr(audit, 'read_annotations', read)
    tree = {f'syn{n}': [{'id': f'syn{n}-file{i}', 'name': 'f', 'type': FILE_TYPE}
                        for i in range(40)] for n in range(4)}
    monkeypatch.setattr(audit, 'login', lambda **kwargs: ChildrenStub(tree))
    monkeypatch.setattr(audit, 'audit_project',
                        lambda _syn, project, **kwargs: _flagged_audit(project['project_id']))

    exit_code = audit.main(['--project', 'syn0', '--project', 'syn1', '--project', 'syn2',
                            '--project', 'syn3', '--out-dir', str(tmp_path), '--drill-down',
                            '--drill-down-workers', '1',
                            '--allowlist', str(tmp_path / 'none.yaml')])

    # The first project trips the breaker at the floor - its successful root listing
    # takes one slot in the window - and nothing else is read.
    assert len(reads) == io.ERROR_FLOOR - 1
    assert {entity.split('-')[0] for entity in reads} == {'syn0'}
    # The three projects it never looked at are lost coverage of their own.
    state = audit.load_state(tmp_path / 'state.jsonl')
    assert [f['operation'] for f in state['syn3'].read_failures] == [audit.READ_OP_DRILL_DOWN]
    assert exit_code == 2


@pytest.mark.parametrize('workers', [1, 4])
def test_a_listing_only_degradation_trips_the_breaker(monkeypatch, workers):
    # The children listing was the last per-entity network loop outside the guard. A
    # degradation confined to POST /entity/children while /annotations2 stayed
    # healthy was invisible: the successful reads filled the trailing window with
    # successes, so the rate could never clear the threshold, while every listing
    # paid the full retry backoff - hours of grinding on the 1,300-folder project.
    canon = frozenset({'age'})
    index = policy.KeyIndex.build(canon)
    folders = [{'id': f'f{n}', 'name': f'f{n}', 'type': FOLDER_TYPE} for n in range(200)]

    class UnlistableFolders:
        def __init__(self):
            self.listed = []

        def restPOST(self, path, body=None):
            assert path == '/entity/children'
            parent = json.loads(body)['parentId']
            self.listed.append(parent)
            if parent != 'syn0':
                raise ServiceUnavailable()
            return {'page': folders}

    monkeypatch.setattr(audit, 'read_annotations',
                        lambda _syn, entity_id, **kwargs: io.AnnotationRecord(
                            entity_id, 'etag-1', {'Age': [1.5], 'age': [1.5]},
                            {'Age': 'DOUBLE', 'age': 'DOUBLE'}))
    syn = UnlistableFolders()
    project = _flagged_audit()
    audit.drill_down_project(syn, project, canon=canon, index=index, workers=workers)

    lost = [parent for parent in syn.listed if parent != 'syn0']
    assert 0 < len(lost) < len(folders), 'the walk stops rather than listing every folder'
    # And the abort is lost coverage, like any other pass that stopped early.
    aborts = [f for f in project.read_failures if 'aborted' in f['error']]
    assert [f['entity_id'] for f in aborts] == ['syn0']
    assert audit.exit_code_for([project], fail_on_findings=False, max_unscanned=0) == 2


# ---------------------------------------------------------------------------
# The findings file is the fix tool's only input
# ---------------------------------------------------------------------------

def _drill_down_run(tmp_path, monkeypatch, *, read):
    """A four-project --drill-down whose entity reads behave as ``read`` says."""
    tree = {f'syn{n}': [{'id': f'syn{n}-file{i}', 'name': 'f', 'type': FILE_TYPE}
                        for i in range(40)] for n in range(4)}
    monkeypatch.setattr(audit, 'read_annotations', read)
    monkeypatch.setattr(audit, 'login', lambda **kwargs: ChildrenStub(tree))
    monkeypatch.setattr(audit, 'audit_project',
                        lambda _syn, project, **kwargs: _flagged_audit(project['project_id']))
    return audit.main(['--project', 'syn0', '--project', 'syn1', '--project', 'syn2',
                       '--project', 'syn3', '--out-dir', str(tmp_path), '--drill-down',
                       '--drill-down-workers', '1',
                       '--allowlist', str(tmp_path / 'none.yaml')])


def test_an_aborted_drill_down_leaves_the_last_complete_findings_file_alone(
        tmp_path, monkeypatch):
    # entity_findings.jsonl is the only input fix_annotation_keys.py --findings
    # reads. The breaker spans the run, so an abort skips every remaining flagged
    # project; rewriting the real path in place would replace a complete findings
    # file with a subset, and a curator re-running during a transient degradation
    # would then repair part of the work believing it was all of it.
    findings_path = tmp_path / 'entity_findings.jsonl'
    findings_path.write_text(json.dumps({'project_id': 'syn0', 'entity_id': 'earlier'}) + '\n')
    audit.write_findings_manifest(findings_path, complete=True, projects=['syn0'], entities=1)

    def read(_syn, entity_id, **_kwargs):
        raise RuntimeError('503 Service Unavailable')

    exit_code = _drill_down_run(tmp_path, monkeypatch, read=read)

    assert exit_code == 2
    assert [json.loads(line)['entity_id'] for line in
            findings_path.read_text().splitlines()] == ['earlier']
    assert audit.read_findings_manifest(findings_path)['complete'] is True

    # What this pass did resolve is kept, under a name that says what it is.
    partial = tmp_path / 'entity_findings.partial.jsonl'
    assert partial.exists()
    manifest = audit.read_findings_manifest(partial)
    assert manifest['complete'] is False
    assert manifest['projects_not_inspected'] == ['syn1', 'syn2', 'syn3']


def test_a_completed_drill_down_replaces_the_findings_file_and_says_so(tmp_path, monkeypatch):
    findings_path = tmp_path / 'entity_findings.jsonl'
    findings_path.write_text(json.dumps({'project_id': 'syn0', 'entity_id': 'earlier'}) + '\n')

    def read(_syn, entity_id, **_kwargs):
        return io.AnnotationRecord(entity_id, 'etag-1', {'Age': [1.5], 'age': [1.5]},
                                   {'Age': 'DOUBLE', 'age': 'DOUBLE'})

    _drill_down_run(tmp_path, monkeypatch, read=read)

    entities = [json.loads(line)['entity_id'] for line in
                findings_path.read_text().splitlines()]
    assert 'earlier' not in entities and len(entities) == 160
    manifest = audit.read_findings_manifest(findings_path)
    assert manifest['complete'] is True
    assert manifest['projects_inspected'] == ['syn0', 'syn1', 'syn2', 'syn3']
    assert manifest['entities'] == 160
    # No stale partial left claiming to describe anything.
    assert not (tmp_path / 'entity_findings.partial.jsonl').exists()
    assert not (tmp_path / 'entity_findings.partial.manifest.json').exists()


def test_an_abort_is_recorded_alongside_the_project_entity_s_own_failed_read():
    # Both name the project entity, and during an outage the entity read fails
    # first. Recording them under one identity deduped the abort away, so the report
    # could not distinguish "64 reads lost" from "64 reads lost and 6,000 entities
    # never looked at".
    project = _flagged_audit('syn1')
    project.record_read_failure('syn1', 'RuntimeError: 503', 'Project',
                                operation=audit.READ_OP_ANNOTATIONS)
    project.record_read_failure('syn1', 'drill-down aborted', 'Project',
                                operation=audit.READ_OP_DRILL_DOWN)

    assert [f['operation'] for f in project.read_failures] == [
        audit.READ_OP_ANNOTATIONS, audit.READ_OP_DRILL_DOWN]
    assert audit.build_summary([project])['entity_read_failures'] == 2


def test_a_lost_listing_and_a_lost_read_of_one_entity_are_two_gaps():
    # A listing and an annotation read are different operations, so one cannot
    # stand in for the other: a folder whose children were never enumerated is a
    # different hole from a folder whose own annotations were not read.
    project = _flagged_audit('syn1')
    project.record_read_failure('folder1', 'could not list children', 'Folder',
                                operation=audit.READ_OP_LISTING)
    project.record_read_failure('folder1', 'RuntimeError: 503', 'Folder',
                                operation=audit.READ_OP_ANNOTATIONS)

    assert len(project.read_failures) == 2
    assert audit.build_summary([project])['entity_read_failures'] == 2
    # And the report names which was lost, so a reader can tell an unenumerated
    # folder from an unread one.
    report = audit.format_markdown([project])
    assert f'| {audit.READ_OP_LISTING} |' in report
    assert f'| {audit.READ_OP_ANNOTATIONS} |' in report


def test_a_repeat_of_the_same_lost_operation_is_counted_once():
    # The same operation failing twice - across chunks, or across a resume that
    # re-reads and loses the same entity again - is one gap in coverage and must not
    # spend the --max-unscanned budget twice.
    project = _flagged_audit('syn1')
    project.record_read_failure('syn1', 'RuntimeError: 503', 'Project',
                                operation=audit.READ_OP_ANNOTATIONS)
    project.record_read_failure('syn1', 'RuntimeError: 503 again', 'Project',
                                operation=audit.READ_OP_ANNOTATIONS)

    assert [f['entity_id'] for f in project.read_failures] == ['syn1']
    assert audit.build_summary([project])['entity_read_failures'] == 1


def test_a_resumed_run_reports_the_gaps_it_inherited_and_says_so(tmp_path, monkeypatch):
    # The contract that replaced two rounds of cross-run re-verification: a resumed
    # run does not retire another run's coverage gaps, not even for a scope it
    # happens to re-read. It reports them, and says its coverage figure is not
    # authoritative - which under-claims coverage rather than over-claiming it, and
    # a full scan is what clears a gap that a later read recovered.
    state = tmp_path / 'state.jsonl'
    stale = _flagged_audit('syn0')
    stale.record_read_failure('file2', 'RuntimeError: 503', 'FileEntity',
                              operation=audit.READ_OP_ANNOTATIONS)
    audit.append_state(state, stale)

    syn = ChildrenStub({'syn0': [{'id': 'file1', 'name': 'file1', 'type': FILE_TYPE},
                                 {'id': 'file2', 'name': 'file2', 'type': FILE_TYPE}]})
    monkeypatch.setattr(audit, 'login', lambda **kwargs: syn)
    monkeypatch.setattr(audit, 'read_annotations',
                        lambda _syn, entity_id, **kwargs: io.AnnotationRecord(
                            entity_id, 'etag-1', {'Age': [1.5], 'age': [1.5]},
                            {'Age': 'DOUBLE', 'age': 'DOUBLE'}))

    exit_code = audit.main(['--project', 'syn0', '--out-dir', str(tmp_path),
                            '--resume', '--drill-down', '--allowlist', str(tmp_path / 'none.yaml')])

    # file2 was re-read successfully this run, and its inherited gap is still
    # reported: nothing here decided that the re-read retired it.
    assert [f['entity_id'] for f in audit.load_state(state)['syn0'].read_failures] == ['file2']
    assert exit_code == 2
    summary = (tmp_path / 'summary.md').read_text()
    assert 'This coverage figure is not authoritative' in summary
    assert 'Carried forward from an earlier run: **1**' in summary
    assert json.loads((tmp_path / 'summary.json').read_text())['coverage_authoritative'] is False
    findings = (tmp_path / 'entity_findings.jsonl').read_text().splitlines()
    assert [json.loads(line)['entity_id'] for line in findings] == ['file1', 'file2']


def test_a_full_scan_reports_its_coverage_as_authoritative(tmp_path, monkeypatch):
    # The other side of the same statement: a run that read every project in scope
    # itself carries no inherited gaps, so its coverage figure stands on its own.
    syn = ChildrenStub({'syn0': []})
    monkeypatch.setattr(audit, 'login', lambda **kwargs: syn)
    monkeypatch.setattr(audit, 'audit_project',
                        lambda _syn, project, **kwargs: _flagged_audit(project['project_id']))

    audit.main(['--project', 'syn0', '--out-dir', str(tmp_path),
                '--allowlist', str(tmp_path / 'none.yaml')])

    summary = (tmp_path / 'summary.md').read_text()
    assert 'Carried forward from an earlier run: **0**' in summary
    assert 'not authoritative' not in summary
    assert json.loads((tmp_path / 'summary.json').read_text())['coverage_authoritative'] is True


def test_read_failures_survive_the_state_file(tmp_path):
    project = _flagged_audit()
    project.record_read_failure('file2', 'RuntimeError: 503', 'FileEntity',
                                operation=audit.READ_OP_ANNOTATIONS)
    state = tmp_path / 'state.jsonl'
    audit.append_state(state, project)
    assert audit.load_state(state)['syn0'].read_failures == project.read_failures


def test_a_read_failure_that_does_not_name_its_operation_still_counts(tmp_path):
    # An entry from before failures recorded what they lost keeps being reported,
    # under an identity of its own so it cannot be folded into a real operation.
    state = tmp_path / 'state.jsonl'
    state.write_text(json.dumps({'project_id': 'syn0', 'status': 'ok',
                                 'read_failures': [{'entity_id': 'file2',
                                                    'error': 'RuntimeError: 503'}]}) + '\n')
    restored = audit.load_state(state)['syn0']
    assert restored.read_failures[0]['operation'] == audit.READ_OP_UNKNOWN
    assert audit.exit_code_for([restored], fail_on_findings=False, max_unscanned=0) == 2


# ---------------------------------------------------------------------------
# Capped markdown tables
# ---------------------------------------------------------------------------

def test_the_tables_that_grow_are_capped_so_the_issue_body_cannot_run_away():
    # summary.md is piped verbatim into a GitHub issue body, and issue bodies are
    # capped at 65,536 characters. What grows is the per-(project, key) table.
    audits = []
    for number in range(audit.MAX_MULTITYPE_ROWS + 10):
        project = _flagged_audit(f'syn{number}')
        project.multitype = {'individualID': ['INTEGER', 'STRING']}
        audits.append(project)
    report = audit.format_markdown(audits)
    assert report.count('| `individualID` |') == audit.MAX_MULTITYPE_ROWS
    assert 'more rows omitted' in report


def test_the_list_of_affected_projects_is_never_truncated():
    # This is the one actionable list in the issue body, and it is one short row
    # per project: a curator must not have to download a CI artifact to learn
    # which project to look at.
    audits = [_flagged_audit(f'syn{number}') for number in range(audit.MAX_KEY_FREQUENCY_ROWS + 25)]
    report = audit.format_markdown(audits)
    for project in audits:
        assert f'Synapse:{project.project_id})' in report


# ---------------------------------------------------------------------------
# Generated allowlist baseline
# ---------------------------------------------------------------------------

def _baseline_state(tmp_path):
    first = audit.ProjectAudit(project_id='syn1', status='ok')
    first.summary = {'duplicates': {'Age': 'age'},
                     'near_misses': {'progrssReportNumber': 'progressReportNumber'}}
    second = audit.ProjectAudit(project_id='syn2', status='ok')
    second.summary = {'case_variants': {'timePointUnit': 'timepointUnit'},
                      'reserved': {'Description': 'description'}}
    state = tmp_path / 'state.jsonl'
    for project in (first, second):
        audit.append_state(state, project)
    return state, [first, second]


def test_emitting_a_baseline_records_every_finding_scoped_to_its_project(tmp_path, monkeypatch):
    state, audits = _baseline_state(tmp_path)
    monkeypatch.setattr(audit, 'login',
                        lambda **kwargs: pytest.fail('--emit-allowlist must not log in'))

    out = tmp_path / 'allowlist.yaml'
    assert audit.main(['--state', str(state), '--out-dir', str(tmp_path),
                       '--emit-allowlist', str(out), '--baseline-expires', '2099-01-01']) == 0

    document = yaml.safe_load(out.read_text())
    entries = document['entries']
    # One entry per (project, key, classification), and `reserved` is left out
    # because it never gates the exit code.
    assert len(entries) == 3
    assert {e['scope'] for e in entries} == {'syn1', 'syn2'}
    assert all(e['reason'] and e['expires'] == '2099-01-01' for e in entries)
    assert {(e['classification'], e['issue']) for e in entries} == {
        ('duplicates', 939), ('near_misses', 939), ('case_variants', 976),
    }

    header = out.read_text().split('entries:')[0]
    assert 'GENERATED, NOT HAND-WRITTEN' in header
    assert '--emit-allowlist' in header
    assert 'SHRINK' in header


def test_the_baseline_makes_the_recorded_scan_green_but_not_new_drift(tmp_path):
    state, audits = _baseline_state(tmp_path)
    out = tmp_path / 'allowlist.yaml'
    audit.main(['--state', str(state), '--out-dir', str(tmp_path),
                '--emit-allowlist', str(out), '--baseline-expires', '2099-01-01'])
    allowlist = audit.load_allowlist(out)

    assert audit.exit_code_for(audits, fail_on_findings=True, max_unscanned=0,
                               allowlist=allowlist) == 0

    # The same key on a project the baseline does not name is new drift.
    fresh = audit.ProjectAudit(project_id='syn3', status='ok')
    fresh.summary = {'duplicates': {'Age': 'age'}}
    assert audit.exit_code_for([*audits, fresh], fail_on_findings=True, max_unscanned=0,
                               allowlist=allowlist) == 1


def test_an_expired_baseline_stops_suppressing(tmp_path):
    # The acceptance is time-boxed on purpose: the baseline is meant to shrink as
    # the remediation passes run, not to be renewed.
    state, audits = _baseline_state(tmp_path)
    out = tmp_path / 'allowlist.yaml'
    audit.main(['--state', str(state), '--out-dir', str(tmp_path),
                '--emit-allowlist', str(out), '--baseline-expires', '2000-01-01'])
    allowlist = audit.load_allowlist(out)
    assert audit.exit_code_for(audits, fail_on_findings=True, max_unscanned=0,
                               allowlist=allowlist) == 1


def test_a_malformed_baseline_expiry_is_rejected(tmp_path):
    state, _ = _baseline_state(tmp_path)
    assert audit.main(['--state', str(state), '--out-dir', str(tmp_path),
                       '--emit-allowlist', str(tmp_path / 'allowlist.yaml'),
                       '--baseline-expires', 'next quarter']) == 1


def test_regenerating_the_baseline_preserves_a_hand_triaged_entry(tmp_path):
    # The header and utils/README.md both promise this file holds the generated
    # baseline PLUS hand-added acceptances, and tell the reader to regenerate it -
    # so regeneration has to merge rather than overwrite.
    state, _ = _baseline_state(tmp_path)
    out = tmp_path / 'allowlist.yaml'
    audit.main(['--state', str(state), '--out-dir', str(tmp_path),
                '--emit-allowlist', str(out), '--baseline-expires', '2099-01-01'])
    out.write_text(out.read_text() + (
        '  - key: tissue\n'
        '    scope: global\n'
        '    classification: unknown\n'
        '    reason: legitimate custom annotation\n'
        '    expires: 2099-06-01\n'
    ))

    assert audit.main(['--state', str(state), '--out-dir', str(tmp_path),
                       '--emit-allowlist', str(out), '--baseline-expires', '2099-02-02']) == 0

    entries = yaml.safe_load(out.read_text())['entries']
    generated = [e for e in entries if e.get('generated')]
    hand_added = [e for e in entries if not e.get('generated')]
    # The baseline was replaced - an explicit --baseline-expires is the one thing
    # that moves a deadline - and the curator's entry came through untouched.
    assert len(generated) == 3 and {e['expires'] for e in generated} == {'2099-02-02'}
    assert [e['key'] for e in hand_added] == ['tissue']
    assert hand_added[0]['reason'] == 'legitimate custom annotation'
    assert audit.load_allowlist(out).suppresses('tissue', 'syn9', 'unknown')


def test_regenerating_without_an_explicit_expiry_keeps_the_recorded_deadline(tmp_path):
    # The documented regeneration command must not renew the baseline. Defaulting to
    # today + a quarter reset all 489 entries every time the command in the header
    # was run, so the drift would never resurface - the opposite of what the header
    # and utils/README.md say the file does, and of the reason the expiry exists.
    state, _ = _baseline_state(tmp_path)
    out = tmp_path / 'allowlist.yaml'
    audit.main(['--state', str(state), '--out-dir', str(tmp_path),
                '--emit-allowlist', str(out), '--baseline-expires', '2026-12-01'])

    # A later scan finds drift on a project the baseline does not name yet.
    fresh = audit.ProjectAudit(project_id='syn3', status='ok')
    fresh.summary = {'duplicates': {'Age': 'age'}}
    audit.append_state(state, fresh)

    assert audit.main(['--state', str(state), '--out-dir', str(tmp_path),
                       '--emit-allowlist', str(out)]) == 0

    entries = {(e['scope'], e['key']): e for e in yaml.safe_load(out.read_text())['entries']}
    assert entries[('syn1', 'Age')]['expires'] == '2026-12-01'
    assert entries[('syn2', 'timePointUnit')]['expires'] == '2026-12-01'
    # Newly found drift still lands with a deadline of its own, a quarter out.
    default = (datetime.now(timezone.utc).date()
               + timedelta(days=audit.BASELINE_TTL_DAYS)).isoformat()
    assert entries[('syn3', 'Age')]['expires'] == default
    # And the header points at the deadline that comes first.
    assert '2026-12-01' in out.read_text().split('entries:')[0]


def test_a_hand_triaged_entry_wins_over_the_generated_one_it_duplicates(tmp_path):
    # Same (key, scope, classification): the human's reason and expiry are the
    # decision of record, and the file must not carry the finding twice.
    state, _ = _baseline_state(tmp_path)
    out = tmp_path / 'allowlist.yaml'
    out.write_text(
        'entries:\n'
        '  - key: Age\n'
        '    scope: syn1\n'
        '    classification: duplicates\n'
        '    reason: accepted by hand\n'
        '    expires: 2099-06-01\n'
    )
    audit.main(['--state', str(state), '--out-dir', str(tmp_path),
                '--emit-allowlist', str(out), '--baseline-expires', '2099-01-01'])

    entries = yaml.safe_load(out.read_text())['entries']
    matching = [e for e in entries if (e['key'], e['scope']) == ('Age', 'syn1')]
    assert len(matching) == 1
    assert matching[0]['reason'] == 'accepted by hand'


def test_an_unparseable_existing_allowlist_is_not_overwritten(tmp_path):
    # The entries at risk are the ones nothing else records, so a file that cannot
    # be read is refused rather than replaced.
    state, _ = _baseline_state(tmp_path)
    out = tmp_path / 'allowlist.yaml'
    out.write_text('entries: [unclosed\n')

    assert audit.main(['--state', str(state), '--out-dir', str(tmp_path),
                       '--emit-allowlist', str(out)]) == 1
    assert out.read_text() == 'entries: [unclosed\n'


def test_the_committed_baseline_is_the_shape_the_audit_consumes():
    document = yaml.safe_load(audit.DEFAULT_ALLOWLIST.read_text())
    # Only the generated baseline is checked here; a hand-triaged entry is a
    # curator's call and may legitimately be global or of another classification.
    entries = [e for e in document['entries'] if e.get('generated')]
    assert entries, 'the committed baseline should record the pre-remediation findings'
    for entry in entries:
        assert entry['scope'].startswith('syn'), 'a baseline entry is scoped to its project'
        assert entry['classification'] in audit.BASELINE_BUCKETS
        assert entry['issue'] in set(audit.BASELINE_ISSUES.values())
        assert entry['expires'] and entry['reason']
