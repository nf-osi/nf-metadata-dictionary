#!/usr/bin/env python3
"""
Tests for the project entity walk used by the annotation key audit drill-down.

Offline: children are served from an in-memory tree. The walk is the part that
dominates runtime on a large project (syn23664726 has over 1,300 folders), so
its parallel and streaming behaviour is worth pinning down.
"""

import os
import sys

import pytest

utils_path = os.path.join(os.path.dirname(__file__), '..', 'utils')
sys.path.insert(0, utils_path)

import audit_annotation_keys as audit  # noqa: E402

FILE_TYPE = 'org.sagebionetworks.repo.model.FileEntity'
FOLDER_TYPE = 'org.sagebionetworks.repo.model.Folder'


class TreeStub:
    """Serves POST /entity/children from a nested dict, and counts calls."""

    def __init__(self, tree, fail_on=()):
        self.tree = tree
        self.calls = []
        self.fail_on = set(fail_on)

    def restPOST(self, path, body=None):
        import json
        assert path == '/entity/children'
        parent = json.loads(body)['parentId']
        self.calls.append(parent)
        if parent in self.fail_on:
            raise RuntimeError(f'boom on {parent}')
        return {'page': self.tree.get(parent, [])}


def entry(entity_id, is_folder=False):
    return {'id': entity_id, 'name': entity_id,
            'type': FOLDER_TYPE if is_folder else FILE_TYPE}


@pytest.mark.parametrize('workers', [1, 4])
def test_walk_finds_every_entity_at_every_depth(workers):
    tree = {
        'syn0': [entry('f1', True), entry('file1')],
        'f1': [entry('f2', True), entry('file2')],
        'f2': [entry('file3')],
    }
    syn = TreeStub(tree)
    found = dict(audit._iter_project_entities(syn, 'syn0', workers=workers))
    assert set(found) == {'f1', 'file1', 'f2', 'file2', 'file3'}
    assert found['f1'] == 'Folder'
    assert found['file3'] == 'FileEntity'


@pytest.mark.parametrize('workers', [1, 4])
def test_walk_visits_each_folder_once_even_with_a_cycle(workers):
    # A folder that lists an ancestor would otherwise loop forever.
    tree = {
        'syn0': [entry('f1', True)],
        'f1': [entry('f2', True), entry('file1')],
        'f2': [entry('f1', True)],
    }
    syn = TreeStub(tree)
    found = list(audit._iter_project_entities(syn, 'syn0', workers=workers))
    assert sorted(i for i, _ in found) == ['f1', 'f1', 'f2', 'file1']
    # f1 is yielded twice (it is listed twice) but only expanded once.
    assert syn.calls.count('f1') == 1


@pytest.mark.parametrize('workers', [1, 4])
def test_walk_honours_the_limit(workers):
    tree = {'syn0': [entry(f'file{i}') for i in range(10)]}
    syn = TreeStub(tree)
    assert len(list(audit._iter_project_entities(syn, 'syn0', limit=4, workers=workers))) == 4


@pytest.mark.parametrize('workers', [1, 4])
def test_a_folder_that_cannot_be_listed_does_not_sink_the_walk(workers):
    # One unreadable folder in a 1,300-folder project must not lose the other 1,299.
    tree = {
        'syn0': [entry('f1', True), entry('f2', True)],
        'f1': [entry('file1')],
        'f2': [entry('file2')],
    }
    syn = TreeStub(tree, fail_on=['f1'])
    found = {i for i, _ in audit._iter_project_entities(syn, 'syn0', workers=workers)}
    assert 'file2' in found
    assert 'file1' not in found


def test_walk_parallelises_each_depth_level():
    # 8 sibling folders at one depth should be listed in one parallel batch, not
    # eight sequential round trips. Verified by call ordering: every sibling is
    # requested before any of their children.
    tree = {'syn0': [entry(f'f{i}', True) for i in range(8)]}
    for i in range(8):
        tree[f'f{i}'] = [entry(f'file{i}')]
    syn = TreeStub(tree)
    list(audit._iter_project_entities(syn, 'syn0', workers=8))
    assert syn.calls[0] == 'syn0'
    assert sorted(syn.calls[1:9]) == [f'f{i}' for i in range(8)]


@pytest.mark.parametrize('workers', [1, 4])
def test_the_project_entity_is_walked_only_when_asked_for(workers):
    # --include-project-entity folds the project's own annotation keys into the
    # inventory, so the drill-down has to be able to reach them too - otherwise a
    # project-level finding shows up in the summary with no row in
    # entity_findings.jsonl, which is the only input the fix tool consumes.
    tree = {'syn0': [entry('file1')]}
    syn = TreeStub(tree)
    with_project = list(audit._iter_project_entities(
        syn, 'syn0', workers=workers, include_project_entity=True))
    assert with_project[0] == ('syn0', 'Project')
    assert ('file1', 'FileEntity') in with_project


@pytest.mark.parametrize('workers', [1, 4])
def test_the_project_entity_is_absent_by_default(workers):
    # The flag is opt-in, and leaving it off has to keep the default scope
    # exactly as it was: descendants only.
    tree = {'syn0': [entry('f1', True), entry('file1')], 'f1': [entry('file2')]}
    syn = TreeStub(tree)
    found = list(audit._iter_project_entities(syn, 'syn0', workers=workers))
    assert 'syn0' not in {entity_id for entity_id, _ in found}
    assert sorted(entity_id for entity_id, _ in found) == ['f1', 'file1', 'file2']


def test_the_project_entity_counts_against_the_limit():
    tree = {'syn0': [entry('file1')]}
    syn = TreeStub(tree)
    found = list(audit._iter_project_entities(
        syn, 'syn0', limit=1, workers=1, include_project_entity=True))
    assert found == [('syn0', 'Project')]
    # Nothing was listed, because the limit was reached before the walk began.
    assert syn.calls == []


def _audit_with_project_entity(monkeypatch, *, columns, values, types):
    import annotation_key_policy as policy
    import synapse_annotation_io as io

    canon = frozenset({'age', 'specimenID', 'studyName', 'deadline', 'dspDatasetIndex'})
    index = policy.KeyIndex.build(canon)
    monkeypatch.setattr(audit, 'scope_columns', lambda syn, scope, **kwargs: dict(columns))
    monkeypatch.setattr(audit, 'read_annotations', lambda syn, entity_id: io.AnnotationRecord(
        entity_id, 'etag-1', values, types,
    ))
    return audit.audit_project(
        object(), {'project_id': 'syn0', 'project_name': 'p'}, canon=canon, index=index,
        view_type_mask=1, include_project_entity=True, async_mode='rest', max_retries=0,
    )


def test_the_project_entity_contributes_its_declared_types_not_a_placeholder(monkeypatch):
    # The multitype report is the triage input for the value-type issue, so
    # folding the project entity in with a hardcoded STRING would invent a
    # conflict against a real DOUBLE column and a real conflict would be lost in
    # the noise.
    result = _audit_with_project_entity(
        monkeypatch,
        columns={'age': {'DOUBLE'}},
        values={'age': ['about five'], 'studyName': ['NF study']},
        types={'age': 'STRING', 'studyName': 'STRING'},
    )
    assert result.status == 'ok'
    assert result.key_types == {'age': ['DOUBLE', 'STRING'], 'studyName': ['STRING']}
    # 'age' really does carry two types here; 'studyName' exists only on the
    # project entity and must not be reported as conflicting with itself.
    assert set(result.multitype) == {'age'}


def test_a_project_entity_annotation_type_is_translated_to_the_view_vocabulary(monkeypatch):
    # /annotations2 and /column/view/scope/async speak different vocabularies:
    # LONG is INTEGER on the view side and TIMESTAMP_MS is DATE, so merging the
    # annotation type verbatim reported conflicts that do not exist.
    result = _audit_with_project_entity(
        monkeypatch,
        columns={'dspDatasetIndex': {'INTEGER'}, 'deadline': {'DATE'},
                 'specimenID': {'STRING_LIST'}},
        values={'dspDatasetIndex': [3], 'deadline': [1700000000000],
                'specimenID': ['s1', 's2']},
        types={'dspDatasetIndex': 'LONG', 'deadline': 'TIMESTAMP_MS',
               'specimenID': 'STRING'},
    )
    assert result.status == 'ok'
    assert result.key_types == {
        'dspDatasetIndex': ['INTEGER'],
        'deadline': ['DATE'],
        'specimenID': ['STRING_LIST'],
    }
    assert result.multitype == {}


def test_the_column_type_mapping_covers_every_type_the_real_fixture_carries():
    # Driven off the committed capture so a vocabulary change on either side
    # fails loudly rather than silently reintroducing phantom conflicts.
    import json

    import synapse_annotation_io as io

    fixture = os.path.join(os.path.dirname(__file__), 'data', 'annotation_keys',
                           'syn25881328_scope_columns.json')
    with open(fixture, encoding='utf-8') as handle:
        observed = {column['columnType'] for column in json.load(handle)}

    scalar = {io.column_type_for(declared, 1) for declared in io.VALUE_DECODERS}
    listed = {io.column_type_for(declared, 2) for declared in io.VALUE_DECODERS}
    assert scalar == {'STRING', 'DOUBLE', 'BOOLEAN', 'INTEGER', 'DATE'}
    assert listed == {'STRING_LIST', 'BOOLEAN_LIST', 'INTEGER_LIST', 'DATE_LIST'}
    # No annotation type may map to a name the view never uses.
    assert 'LONG' not in scalar | listed
    assert 'TIMESTAMP_MS' not in scalar | listed
    assert observed <= scalar | listed


def test_walk_is_lazy_and_does_not_read_the_whole_tree_up_front():
    # The caller stops after the first entity; the walk must not have expanded
    # deeper levels. This is what keeps memory bounded on a large project.
    tree = {'syn0': [entry('f1', True)], 'f1': [entry('file1')]}
    syn = TreeStub(tree)
    walker = audit._iter_project_entities(syn, 'syn0', workers=1)
    next(walker)
    assert syn.calls == ['syn0']
