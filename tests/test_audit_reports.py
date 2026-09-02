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

import pytest
import yaml

utils_path = os.path.join(os.path.dirname(__file__), '..', 'utils')
sys.path.insert(0, utils_path)

import annotation_key_policy as policy  # noqa: E402
import audit_annotation_keys as audit  # noqa: E402
import synapse_annotation_io as io  # noqa: E402

FILE_TYPE = 'org.sagebionetworks.repo.model.FileEntity'


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


def test_read_failures_survive_the_state_file(tmp_path):
    project = _flagged_audit()
    project.read_failures = [{'entity_id': 'file2', 'error': 'RuntimeError: 503'}]
    state = tmp_path / 'state.jsonl'
    audit.append_state(state, project)
    assert audit.load_state(state)['syn0'].read_failures == project.read_failures


# ---------------------------------------------------------------------------
# Capped markdown tables
# ---------------------------------------------------------------------------

def test_the_markdown_tables_are_capped_so_the_issue_body_cannot_run_away():
    # summary.md is piped verbatim into a GitHub issue body, and issue bodies are
    # capped at 65,536 characters.
    audits = []
    for number in range(audit.MAX_TABLE_ROWS + 10):
        project = _flagged_audit(f'syn{number}')
        project.multitype = {'individualID': ['INTEGER', 'STRING']}
        audits.append(project)
    report = audit.format_markdown(audits)
    assert report.count('| `individualID` |') == audit.MAX_TABLE_ROWS
    assert 'more rows omitted' in report


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


def test_the_committed_baseline_is_the_shape_the_audit_consumes():
    document = yaml.safe_load(audit.DEFAULT_ALLOWLIST.read_text())
    entries = document['entries']
    assert entries, 'the committed baseline should record the pre-remediation findings'
    for entry in entries:
        assert entry['scope'].startswith('syn'), 'a baseline entry is scoped to its project'
        assert entry['classification'] in audit.BASELINE_BUCKETS
        assert entry['issue'] in set(audit.BASELINE_ISSUES.values())
        assert entry['expires'] and entry['reason']
