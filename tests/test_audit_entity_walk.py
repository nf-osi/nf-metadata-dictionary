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


def test_walk_is_lazy_and_does_not_read_the_whole_tree_up_front():
    # The caller stops after the first entity; the walk must not have expanded
    # deeper levels. This is what keeps memory bounded on a large project.
    tree = {'syn0': [entry('f1', True)], 'f1': [entry('file1')]}
    syn = TreeStub(tree)
    walker = audit._iter_project_entities(syn, 'syn0', workers=1)
    next(walker)
    assert syn.calls == ['syn0']
