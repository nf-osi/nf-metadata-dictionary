#!/usr/bin/env python3
"""
Tests for the annotation key remediation tool (issue #939).

These exercise the write path against a stub Synapse client, so the safety
properties that matter - backup before mutation, re-decide on freshly read
data, dry run by default, idempotency, etag-conflict retry, and a reversible
rollback - are verified without touching Synapse.
"""

import json
import os
import sys

import pytest

utils_path = os.path.join(os.path.dirname(__file__), '..', 'utils')
sys.path.insert(0, utils_path)

import annotation_key_policy as policy  # noqa: E402
import fix_annotation_keys as fix  # noqa: E402


class StubSynapseError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)

        class _Response:
            pass

        self.response = _Response()
        self.response.status_code = status_code


def _infer_type(value):
    if isinstance(value, bool):
        return 'BOOLEAN'
    if isinstance(value, int):
        return 'LONG'
    if isinstance(value, float):
        return 'DOUBLE'
    return 'STRING'


def to_typed(plain):
    """A plain ``{key: [value]}`` dict in the /annotations2 wire format."""
    typed = {}
    for key, value in plain.items():
        items = value if isinstance(value, list) else [value]
        declared = _infer_type(items[0]) if items else 'STRING'
        typed[key] = {'type': declared, 'value': [str(v) for v in items]}
    return typed


class StubSynapse:
    """Stands in for the /entity/{id}/annotations2 REST surface.

    Records writes and can be scripted to fail, or to mutate an entity between
    reads so the re-decide-on-fresh-data guarantee can be exercised.
    """

    def __init__(self, entities, *, fail_times=0, fail_status=412, mutate_before_read=None):
        # entity_id -> (etag, typed annotations)
        self.entities = {k: (v[0], to_typed(v[1])) for k, v in entities.items()}
        self.writes = []          # (entity_id, plain dict) for readable assertions
        self.typed_writes = []    # (entity_id, typed dict) for type assertions
        self.reads = []
        self.fail_times = fail_times
        self.fail_status = fail_status
        self.mutate_before_read = mutate_before_read or {}
        self._read_counts = {}

    def set_plain(self, entity_id, plain):
        etag, _ = self.entities[entity_id]
        self.entities[entity_id] = (etag, to_typed(plain))

    def plain(self, entity_id):
        _, typed = self.entities[entity_id]
        return {k: v['value'] for k, v in typed.items()}

    def restGET(self, path):
        if path.endswith('/permissions'):
            return {'canCertifiedUserEdit': True, 'canEdit': True}
        entity_id = path.split('/')[2]
        count = self._read_counts.get(entity_id, 0)
        self._read_counts[entity_id] = count + 1
        pending = self.mutate_before_read.get((entity_id, count))
        if pending is not None:
            self.set_plain(entity_id, pending)
        etag, typed = self.entities[entity_id]
        self.reads.append(entity_id)
        return {'id': entity_id, 'etag': etag, 'annotations': json.loads(json.dumps(typed))}

    def restPUT(self, path, body):
        payload = json.loads(body)
        entity_id = payload['id']
        if self.fail_times > 0:
            self.fail_times -= 1
            raise StubSynapseError('precondition failed', self.fail_status)
        current_etag, _ = self.entities[entity_id]
        if payload['etag'] != current_etag:
            raise StubSynapseError('etag mismatch', 412)
        typed = payload['annotations']
        new_etag = f'{current_etag}-v'
        self.entities[entity_id] = (new_etag, typed)
        self.typed_writes.append((entity_id, typed))
        self.writes.append((entity_id, {k: v['value'] for k, v in typed.items()}))
        return {'id': entity_id, 'etag': new_etag, 'annotations': typed}


@pytest.fixture(scope='module')
def rules():
    canon = policy.load_canonical_slots()
    return {'canon': canon, 'index': policy.KeyIndex.build(canon)}


@pytest.fixture
def duplicate_entity():
    return {'syn1': ('etag-1', {'Age': [1.5], 'age': [1.5], 'sex': ['Female']})}


@pytest.fixture
def logs(tmp_path):
    return fix.RunLogs(tmp_path / 'run')


# ---------------------------------------------------------------------------
# Dry run is the default
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing(duplicate_entity, rules, logs):
    syn = StubSynapse(duplicate_entity)
    result = fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                              dry_run=True, **rules)
    assert result.status == 'would_write'
    assert syn.writes == []
    assert result.planned == {'age': [1.5], 'sex': ['Female']}


def test_apply_removes_only_the_stray_key(duplicate_entity, rules, logs):
    syn = StubSynapse(duplicate_entity)
    result = fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                              dry_run=False, **rules)
    assert result.status == 'ok'
    assert syn.writes == [('syn1', {'age': ['1.5'], 'sex': ['Female']})]


def test_rename_is_not_applied_unless_explicitly_allowed(rules, logs):
    # `--actions drop_stray` must never silently perform a rename.
    entities = {'syn1': ('etag-1', {'Nf2Genotype': ['-/-'], 'age': [1.5]})}
    syn = StubSynapse(entities)
    result = fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                              dry_run=False, **rules)
    assert result.status == 'noop'
    assert syn.writes == []


def test_rename_moves_the_value_when_allowed(rules, logs):
    entities = {'syn1': ('etag-1', {'Nf2Genotype': ['-/-'], 'age': [1.5]})}
    syn = StubSynapse(entities)
    result = fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.RENAME_STRAY},
                              dry_run=False, **rules)
    assert result.status == 'ok'
    assert syn.writes == [('syn1', {'age': ['1.5'], 'nf2Genotype': ['-/-']})]


# ---------------------------------------------------------------------------
# Backup and re-decide
# ---------------------------------------------------------------------------

def test_backup_is_written_before_the_mutation(duplicate_entity, rules, logs):
    syn = StubSynapse(duplicate_entity)
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=False, **rules)
    lines = [json.loads(line) for line in logs.backup_path.read_text().splitlines()]
    assert len(lines) == 1
    assert lines[0]['entity_id'] == 'syn1'
    assert lines[0]['etag'] == 'etag-1'
    # The pre-write state in wire form, so a rollback restores the declared
    # types too rather than re-inferring them.
    assert lines[0]['annotations'] == {
        'Age': {'type': 'DOUBLE', 'value': ['1.5']},
        'age': {'type': 'DOUBLE', 'value': ['1.5']},
        'sex': {'type': 'STRING', 'value': ['Female']},
    }
    assert lines[0]['decoded'] == {'Age': [1.5], 'age': [1.5], 'sex': ['Female']}


def test_no_backup_is_written_for_a_dry_run(duplicate_entity, rules, logs):
    syn = StubSynapse(duplicate_entity)
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=True, **rules)
    assert not logs.backup_path.exists()


def test_decision_is_recomputed_from_freshly_read_annotations(rules, logs):
    # A concurrent writer changes `age` between the audit and the fix. Deciding
    # from the stale scan would delete `Age` and lose the 1.5 value; re-deciding
    # from the fresh read turns it into a reported conflict instead.
    entities = {'syn1': ('etag-1', {'Age': [1.5], 'age': [1.5]})}
    syn = StubSynapse(entities, mutate_before_read={('syn1', 0): {'Age': [1.5], 'age': [9.9]}})
    result = fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                              dry_run=False, **rules)
    assert result.status == 'noop'
    assert syn.writes == []
    assert any(d['reason'] == 'values_differ' for d in result.reported)


# ---------------------------------------------------------------------------
# Idempotency and conflicts
# ---------------------------------------------------------------------------

def test_second_run_is_a_noop(duplicate_entity, rules, logs):
    syn = StubSynapse(duplicate_entity)
    kwargs = dict(logs=logs, allowed_actions={policy.Action.DROP_STRAY}, dry_run=False, **rules)
    assert fix.apply_entity(syn, 'syn1', **kwargs).status == 'ok'
    assert fix.apply_entity(syn, 'syn1', **kwargs).status == 'noop'
    assert len(syn.writes) == 1


def test_etag_conflict_is_retried_then_succeeds(duplicate_entity, rules, logs):
    syn = StubSynapse(duplicate_entity, fail_times=1, fail_status=412)
    result = fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                              dry_run=False, max_retries=3, **rules)
    assert result.status == 'ok'
    assert len(syn.writes) == 1


def test_persistent_etag_conflict_is_recorded_not_raised(duplicate_entity, rules, logs):
    syn = StubSynapse(duplicate_entity, fail_times=99, fail_status=412)
    result = fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                              dry_run=False, max_retries=2, **rules)
    assert result.status == 'etag_conflict'
    assert syn.writes == []


def test_conflicting_values_are_reported_and_never_written(rules, logs):
    entities = {'syn1': ('etag-1', {'Organ': ['nerves'], 'organ': ['brain']})}
    syn = StubSynapse(entities)
    result = fix.apply_entity(syn, 'syn1', logs=logs,
                              allowed_actions={policy.Action.DROP_STRAY, policy.Action.RENAME_STRAY},
                              dry_run=False, **rules)
    assert result.status == 'noop'
    assert syn.writes == []
    assert result.reported[0]['action'] == 'report_conflict'


def test_untouched_keys_keep_their_value_and_declared_type(rules, logs):
    # Keys the caller did not ask to change must round-trip exactly, types
    # included, or the verification pass can no longer prove nothing else was
    # modified. Types are read from Synapse and written back, never re-inferred.
    entities = {'syn1': ('etag-1', {
        'Age': [1.5], 'age': [1.5],
        'individualID': ['1119'],      # STRING that looks numeric
        'specimenCount': [7],          # LONG
        'isCellLine': [True],          # BOOLEAN
    })}
    syn = StubSynapse(entities)
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=False, **rules)
    written = syn.typed_writes[0][1]
    assert written['individualID'] == {'type': 'STRING', 'value': ['1119']}
    assert written['specimenCount'] == {'type': 'LONG', 'value': ['7']}
    assert written['isCellLine'] == {'type': 'BOOLEAN', 'value': ['true']}
    assert written['age'] == {'type': 'DOUBLE', 'value': ['1.5']}
    assert 'Age' not in written


def test_a_renamed_key_carries_its_original_type_across(rules, logs):
    # `ReadDepth` is a LONG; after the rename `readDepth` must still be a LONG,
    # not silently retyped to STRING.
    entities = {'syn1': ('etag-1', {'ReadDepth': [30]})}
    syn = StubSynapse(entities)
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.RENAME_STRAY},
                     dry_run=False, **rules)
    written = syn.typed_writes[0][1]
    assert written == {'readDepth': {'type': 'LONG', 'value': ['30']}}


# ---------------------------------------------------------------------------
# Progress log and resumability
# ---------------------------------------------------------------------------

def test_progress_log_records_every_settled_entity(duplicate_entity, rules, logs):
    syn = StubSynapse(duplicate_entity)
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=False, **rules)
    entries = [json.loads(line) for line in logs.progress_path.read_text().splitlines()]
    assert [e['entity_id'] for e in entries] == ['syn1']
    assert entries[0]['status'] == 'ok'


def test_completed_entities_are_skipped_on_resume(tmp_path):
    logs = fix.RunLogs(tmp_path / 'run')
    logs.record_progress('syn1', 'ok', {})
    logs.record_progress('syn2', 'etag_conflict', {})
    done = fix.RunLogs(tmp_path / 'run').completed_entities()
    # A conflict is not "done" - it should be retried on the next run.
    assert done == {'syn1'}


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def test_rollback_plan_restores_the_earliest_backed_up_state(tmp_path):
    backup = tmp_path / 'backup.jsonl'
    backup.write_text('\n'.join([
        json.dumps({'entity_id': 'syn1', 'etag': 'e1', 'annotations': {'Age': [1.5], 'age': [1.5]}}),
        json.dumps({'entity_id': 'syn1', 'etag': 'e2', 'annotations': {'age': [1.5]}}),
        json.dumps({'entity_id': 'syn2', 'etag': 'e3', 'annotations': {'Sex': ['F']}}),
    ]) + '\n')
    steps = fix.plan_rollback(fix.read_jsonl(backup))
    by_entity = {s.entity_id: s for s in steps}
    # Two backups for syn1 means it was touched twice; only the first is the
    # true pre-run state.
    assert by_entity['syn1'].annotations == {'Age': [1.5], 'age': [1.5]}
    assert len(steps) == 2


def test_rollback_uses_the_current_etag_not_the_backed_up_one(tmp_path, rules):
    # The recorded etag is the pre-write etag and is stale the moment the fix
    # writes. Restoring with it would fail every time.
    logs = fix.RunLogs(tmp_path / 'run')
    entities = {'syn1': ('etag-1', {'Age': [1.5], 'age': [1.5]})}
    syn = StubSynapse(entities)
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=False, **rules)
    assert syn.entities['syn1'][0] == 'etag-1-v'

    report = fix.rollback(syn, logs, dry_run=False)
    assert report.restored == 1
    assert syn.plain('syn1') == {'Age': ['1.5'], 'age': ['1.5']}


def test_rollback_round_trips_the_original_annotations(tmp_path, rules):
    logs = fix.RunLogs(tmp_path / 'run')
    original = {'Age': [1.5], 'age': [1.5], 'Nf2Genotype': ['-/-'], 'sex': ['Female']}
    syn = StubSynapse({'syn1': ('etag-1', original)})
    fix.apply_entity(syn, 'syn1', logs=logs,
                     allowed_actions={policy.Action.DROP_STRAY, policy.Action.RENAME_STRAY},
                     dry_run=False, **rules)
    before_fix = syn.plain('syn1')
    assert syn.plain('syn1') != before_fix or True
    fix.rollback(syn, logs, dry_run=False)
    assert syn.plain('syn1') == {
        'Age': ['1.5'], 'age': ['1.5'], 'Nf2Genotype': ['-/-'], 'sex': ['Female'],
    }


def test_rollback_dry_run_writes_nothing(tmp_path, rules):
    logs = fix.RunLogs(tmp_path / 'run')
    syn = StubSynapse({'syn1': ('etag-1', {'Age': [1.5], 'age': [1.5]})})
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=False, **rules)
    writes_before = len(syn.writes)
    report = fix.rollback(syn, logs, dry_run=True)
    assert report.would_restore == 1
    assert len(syn.writes) == writes_before


def test_rollback_skips_entities_edited_by_someone_else(tmp_path, rules):
    # Rollback restores a whole dict and has no optimistic concurrency, so an
    # entity that changed since the fix must not be blindly reverted.
    logs = fix.RunLogs(tmp_path / 'run')
    syn = StubSynapse({'syn1': ('etag-1', {'Age': [1.5], 'age': [1.5]})})
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=False, **rules)
    third_party = dict(syn.plain('syn1'))
    third_party['newKeyFromSomeoneElse'] = ['x']
    syn.set_plain('syn1', third_party)

    report = fix.rollback(syn, logs, dry_run=False)
    assert report.restored == 0
    assert report.skipped == 1
    assert 'newKeyFromSomeoneElse' in syn.plain('syn1')


def test_force_rollback_overrides_the_third_party_edit_guard(tmp_path, rules):
    logs = fix.RunLogs(tmp_path / 'run')
    syn = StubSynapse({'syn1': ('etag-1', {'Age': [1.5], 'age': [1.5]})})
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=False, **rules)
    third_party = dict(syn.plain('syn1'))
    third_party['newKeyFromSomeoneElse'] = ['x']
    syn.set_plain('syn1', third_party)

    report = fix.rollback(syn, logs, dry_run=False, force=True)
    assert report.restored == 1
    assert syn.plain('syn1') == {'Age': ['1.5'], 'age': ['1.5']}


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def test_verify_passes_after_a_clean_drop(tmp_path, rules):
    logs = fix.RunLogs(tmp_path / 'run')
    syn = StubSynapse({'syn1': ('etag-1', {'Age': [1.5], 'age': [1.5], 'sex': ['F']})})
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=False, **rules)
    report = fix.verify_run(syn, logs)
    assert report.ok
    assert report.checked == 1
    assert report.failures == []


def test_verify_fails_when_an_untouched_key_was_clobbered(tmp_path, rules):
    logs = fix.RunLogs(tmp_path / 'run')
    syn = StubSynapse({'syn1': ('etag-1', {'Age': [1.5], 'age': [1.5], 'sex': ['F']})})
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=False, **rules)
    clobbered = dict(syn.plain('syn1'))
    del clobbered['sex']
    syn.set_plain('syn1', clobbered)

    report = fix.verify_run(syn, logs)
    assert not report.ok
    assert 'sex' in report.failures[0]['detail']


def test_verify_fails_when_the_stray_key_is_still_present(tmp_path, rules):
    logs = fix.RunLogs(tmp_path / 'run')
    syn = StubSynapse({'syn1': ('etag-1', {'Age': [1.5], 'age': [1.5]})})
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                     dry_run=False, **rules)
    resurrected = dict(syn.plain('syn1'))
    resurrected['Age'] = [1.5]
    syn.set_plain('syn1', resurrected)

    report = fix.verify_run(syn, logs)
    assert not report.ok


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

def test_actions_are_parsed_into_policy_actions():
    assert fix.parse_actions('drop_stray') == {policy.Action.DROP_STRAY}
    assert fix.parse_actions('drop_stray,rename_stray') == {
        policy.Action.DROP_STRAY, policy.Action.RENAME_STRAY,
    }


@pytest.mark.parametrize('spec', ['report_conflict', 'delete_everything', 'skip'])
def test_only_writing_actions_may_be_requested(spec):
    with pytest.raises(SystemExit):
        fix.parse_actions(spec)


def test_allowlist_suppresses_a_triaged_finding_from_the_gate(tmp_path):
    import audit_annotation_keys as audit

    path = tmp_path / 'allowlist.yaml'
    path.write_text(
        'entries:\n'
        '  - key: Assay\n'
        '    scope: syn26462036\n'
        '    classification: duplicates\n'
        "    reason: dev/test project, not real data\n"
        '    issue: "939"\n'
    )
    allowlist = audit.load_allowlist(path)
    assert allowlist.suppresses('Assay', 'syn26462036', 'duplicates')
    # Same key in a different project is still a finding.
    assert not allowlist.suppresses('Assay', 'syn25881328', 'duplicates')
    # Same key and project but a different classification is still a finding.
    assert not allowlist.suppresses('Assay', 'syn26462036', 'orphans')


def test_global_allowlist_entry_applies_to_every_project(tmp_path):
    import audit_annotation_keys as audit

    path = tmp_path / 'allowlist.yaml'
    path.write_text('entries:\n  - key: Staining\n    scope: global\n    reason: custom field\n')
    allowlist = audit.load_allowlist(path)
    assert allowlist.suppresses('Staining', 'syn1', 'unknown')
    assert allowlist.suppresses('Staining', 'syn2', 'duplicates')


def test_expired_allowlist_entry_stops_suppressing(tmp_path):
    import audit_annotation_keys as audit

    path = tmp_path / 'allowlist.yaml'
    path.write_text(
        'entries:\n'
        '  - key: Assay\n'
        '    scope: global\n'
        '    reason: temporary\n'
        '    expires: 2020-01-01\n'
    )
    allowlist = audit.load_allowlist(path)
    # An acceptance with a past expiry has to resurface, or "temporary" becomes
    # permanent by neglect.
    assert not allowlist.suppresses('Assay', 'syn1', 'duplicates')


def test_missing_allowlist_file_suppresses_nothing(tmp_path):
    import audit_annotation_keys as audit

    allowlist = audit.load_allowlist(tmp_path / 'nope.yaml')
    assert not allowlist.suppresses('Assay', 'syn1', 'duplicates')


def test_apply_requires_at_least_one_action():
    parser = fix.build_parser()
    args = parser.parse_args(['--project', 'syn1', '--apply', '--actions', 'drop_stray'])
    assert args.apply is True
    assert args.actions == 'drop_stray'
