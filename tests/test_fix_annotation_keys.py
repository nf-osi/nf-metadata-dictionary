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
from pathlib import Path

import pytest

utils_path = os.path.join(os.path.dirname(__file__), '..', 'utils')
sys.path.insert(0, utils_path)

import annotation_key_policy as policy  # noqa: E402
import fix_annotation_keys as fix  # noqa: E402
import synapse_annotation_io as io  # noqa: E402


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


def _to_wire(value):
    # Synapse serialises a BOOLEAN as 'true'/'false', not Python's 'True'.
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def to_typed(plain):
    """A plain ``{key: [value]}`` dict in the /annotations2 wire format."""
    typed = {}
    for key, value in plain.items():
        items = value if isinstance(value, list) else [value]
        declared = _infer_type(items[0]) if items else 'STRING'
        typed[key] = {'type': declared, 'value': [_to_wire(v) for v in items]}
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


def test_a_transient_read_failure_is_retried_rather_than_sinking_the_run(
    duplicate_entity, rules, logs, monkeypatch
):
    # A 503 on a read is not a verdict about the entity, and the schema preflight
    # refuses the whole run on an entity it could not read - so without a retry one
    # blip would abort a plan of thousands. --max-retries covers reads, not just
    # etag conflicts on write.
    monkeypatch.setattr(io.time, 'sleep', lambda _seconds: None)

    class FlakyReads(StubSynapse):
        def __init__(self, entities, *, read_failures):
            super().__init__(entities)
            self.read_failures = read_failures

        def restGET(self, path):
            if path.endswith('/annotations2') and self.read_failures > 0:
                self.read_failures -= 1
                raise StubSynapseError('Service Unavailable', 503)
            return super().restGET(path)

    syn = FlakyReads(duplicate_entity, read_failures=2)
    result = fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                              dry_run=False, max_retries=3, **rules)
    assert result.status == 'ok'
    assert syn.plain('syn1') == {'age': ['1.5'], 'sex': ['Female']}


def test_a_dropped_connection_counts_as_transient_despite_not_subclassing_the_builtin():
    # requests' ConnectionError and Timeout come from RequestException -> OSError,
    # not from the builtins of the same name, and they carry no response - so
    # matching only the builtins meant the two most common transient failures in a
    # multi-hour scan were never retried by the shared policy.
    requests = pytest.importorskip('requests')
    assert not issubclass(requests.exceptions.ConnectionError, ConnectionError)
    assert not issubclass(requests.exceptions.Timeout, TimeoutError)

    assert io.is_retryable(requests.exceptions.ConnectionError('connection aborted'))
    assert io.is_retryable(requests.exceptions.Timeout('read timed out'))
    assert io.is_retryable(TimeoutError('socket timeout'))
    assert io.is_retryable(StubSynapseError('service unavailable', 503))
    # A connection dropped mid-response, and urllib3's own retry budget running
    # out, sit in the same gap: no status, and not a builtin either.
    assert io.is_retryable(requests.exceptions.ChunkedEncodingError('truncated body'))
    assert io.is_retryable(requests.exceptions.RetryError('too many retries'))
    # A definite HTTP verdict outside the retryable set, and a plain bug, are not
    # going to come back different on the second attempt. In particular the policy
    # is not widened to RequestException, which would retry a malformed URL.
    assert not io.is_retryable(StubSynapseError('not found', 404))
    assert not io.is_retryable(ValueError('malformed payload'))
    assert not io.is_retryable(requests.exceptions.MissingSchema('no scheme'))


def test_a_dropped_connection_is_actually_retried_by_the_shared_policy(monkeypatch):
    requests = pytest.importorskip('requests')
    monkeypatch.setattr(io.time, 'sleep', lambda _seconds: None)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise requests.exceptions.ConnectionError('connection aborted')
        return 'ok'

    assert io.with_retries(flaky, max_retries=3, label='syn1') == 'ok'
    assert len(attempts) == 3


def test_a_read_that_keeps_failing_is_still_reported_as_an_error(
    duplicate_entity, rules, logs, monkeypatch
):
    # Retrying must not turn a real outage into a silent pass: once the budget is
    # spent the entity is an error, which is what the preflight buckets as
    # unvalidatable.
    monkeypatch.setattr(io.time, 'sleep', lambda _seconds: None)

    class DeadReads(StubSynapse):
        def restGET(self, path):
            if path.endswith('/annotations2'):
                raise StubSynapseError('Service Unavailable', 503)
            return super().restGET(path)

    syn = DeadReads(duplicate_entity)
    result = fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                              dry_run=False, max_retries=2, **rules)
    assert result.status == 'error'
    assert syn.writes == []


def test_a_forbidden_read_fails_fast_without_burning_the_retry_budget(
    duplicate_entity, rules, logs, monkeypatch
):
    # A 403 does not become a 200 on the second attempt; retrying it only delays
    # the finding.
    monkeypatch.setattr(io.time, 'sleep', lambda _seconds: pytest.fail('403 was retried'))

    class ForbiddenReads(StubSynapse):
        def __init__(self, entities):
            super().__init__(entities)
            self.attempts = 0

        def restGET(self, path):
            if path.endswith('/annotations2'):
                self.attempts += 1
                raise StubSynapseError('403 Forbidden', 403)
            return super().restGET(path)

    syn = ForbiddenReads(duplicate_entity)
    result = fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.DROP_STRAY},
                              dry_run=False, max_retries=3, **rules)
    assert result.status == 'error'
    assert syn.attempts == 1


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


def test_untouched_keys_round_trip_their_exact_wire_representation(rules, logs):
    # Decoding is lossy in the textual direction: the DOUBLE '1.50' decodes to
    # 1.5 and re-encodes to '1.5', and '1e6' to '1000000.0'. verify_run compares
    # decoded values, so it can never catch that - the run would silently rewrite
    # the stored form of a key it was never asked to touch.
    entities = {'syn1': ('etag-1', {})}
    syn = StubSynapse(entities)
    syn.entities['syn1'] = ('etag-1', {
        'Age': {'type': 'DOUBLE', 'value': ['1.5']},
        'age': {'type': 'DOUBLE', 'value': ['1.50']},
        'readDepth': {'type': 'DOUBLE', 'value': ['1e6']},
        'specimenID': {'type': 'STRING', 'value': ['0001']},
    })
    result = fix.apply_entity(syn, 'syn1', logs=logs,
                              allowed_actions={policy.Action.DROP_STRAY},
                              dry_run=False, **rules)
    assert result.status == 'ok'
    written = syn.typed_writes[0][1]
    assert written == {
        'age': {'type': 'DOUBLE', 'value': ['1.50']},
        'readDepth': {'type': 'DOUBLE', 'value': ['1e6']},
        'specimenID': {'type': 'STRING', 'value': ['0001']},
    }
    # The backup records the same wire form, so a rollback restores the original
    # representation rather than a re-serialised one.
    backup = json.loads(logs.backup_path.read_text().splitlines()[0])
    assert backup['annotations']['age'] == {'type': 'DOUBLE', 'value': ['1.50']}


def test_a_renamed_key_carries_its_raw_wire_strings_to_its_new_name(rules, logs):
    # A rename moves metadata; it must not rewrite it. Re-encoding from the
    # decoded value would land '1e6' as '1000000.0' and '1.50' as '1.5', so the
    # stray's original wire strings travel across to the canonical key.
    syn = StubSynapse({'syn1': ('etag-1', {})})
    syn.entities['syn1'] = ('etag-1', {
        'ReadDepth': {'type': 'DOUBLE', 'value': ['1e6']},
        'Age': {'type': 'DOUBLE', 'value': ['1.50']},
    })
    fix.apply_entity(syn, 'syn1', logs=logs, allowed_actions={policy.Action.RENAME_STRAY},
                     dry_run=False, **rules)
    assert syn.typed_writes[0][1] == {
        'readDepth': {'type': 'DOUBLE', 'value': ['1e6']},
        'age': {'type': 'DOUBLE', 'value': ['1.50']},
    }


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


def _planned(entity_id, plan, values=None):
    """The dry-run result the preflight consumes for an entity with a plan."""
    return fix.ApplyResult(entity_id, 'would_write', planned=values or {}, applied=plan)


def test_schema_preflight_blocks_a_plan_that_would_break_conformance(rules, logs):
    import validate_annotations as validate

    registry = validate.SchemaRegistry.load()
    fixture = Path(__file__).parent / 'data' / 'annotation_keys' / 'syn64420376_entity_json.json'
    valid = json.loads(fixture.read_text())

    class SchemaStub:
        """Serves the entity JSON and a binding, for the conformance check."""

        def __init__(self, instance):
            self.instance = instance

        def restGET(self, path):
            if path.endswith('/json'):
                return json.loads(json.dumps(self.instance))
            if path.endswith('/schema/binding'):
                return {'jsonSchemaVersionInfo': {
                    'schemaName': 'microscopyassaytemplate',
                    'semanticVersion': '11.1.22',
                    '$id': 'org.synapse.nf-microscopyassaytemplate-11.1.22',
                }}
            raise AssertionError(path)

    syn = SchemaStub(valid)
    # A plan that drops a schema-required key must be refused.
    bad_plan = [{'action': 'drop_stray', 'stray_key': 'fileFormat', 'canonical_key': 'fileFormat'}]
    report = fix.schema_preflight(
        syn, [_planned('syn64420376', bad_plan)], registry=registry, repo_version='11.1.22')
    assert [b.entity_id for b in report.blockers] == ['syn64420376']
    assert not report.ok

    # The real plan - dropping PascalCase strays - must pass.
    strays = [k for k in valid if k[:1].isupper()
              and k not in ('Component', 'Filename', 'Id', 'Uuid', 'EntityId')]
    good_plan = [{'action': 'drop_stray', 'stray_key': k, 'canonical_key': k[:1].lower() + k[1:]}
                 for k in strays]
    clean = fix.schema_preflight(
        syn, [_planned('syn64420376', good_plan)], registry=registry, repo_version='11.1.22')
    assert clean.blockers == []
    assert clean.unvalidatable == []
    assert clean.ok


def test_schema_preflight_reports_entities_it_could_not_validate_at_all(rules, logs):
    # An entity the check could not reach a verdict on is not a pass. Counting it
    # as one makes "every entity proven safe" indistinguishable from "nothing
    # could be checked", which is the weaker of the two gates the fix tool wraps.
    import validate_annotations as validate

    registry = validate.SchemaRegistry.load()

    class UnreachableStub:
        def restGET(self, path):
            if path.endswith('/json'):
                if 'syn_missing_schema' in path:
                    return {'id': 'syn_missing_schema'}
                raise RuntimeError('503 Service Unavailable')
            if path.endswith('/schema/binding'):
                return {'jsonSchemaVersionInfo': {
                    'schemaName': 'notatemplateinthischeckout',
                    'semanticVersion': '1.0.0',
                    '$id': 'org.synapse.nf-notatemplateinthischeckout-1.0.0',
                }}
            raise AssertionError(path)

    plan = [{'action': 'drop_stray', 'stray_key': 'Age', 'canonical_key': 'age'}]
    report = fix.schema_preflight(
        UnreachableStub(),
        [_planned('syn_missing_schema', plan), _planned('syn_unreadable', plan)],
        registry=registry, repo_version='11.1.22')
    assert report.checked == 2
    assert report.blockers == []
    assert {r.status for r in report.unvalidatable} == {'no_schema', 'error'}
    assert not report.ok


def test_schema_preflight_does_not_credit_an_unvalidatable_unbound_entity():
    # An entity with no binding and no Component was never validated either, so
    # crediting it toward "proven conformant" would be the same silent pass that
    # `error` and `no_schema` used to get.
    import validate_annotations as validate

    registry = validate.SchemaRegistry.load()

    class UnboundStub:
        def restGET(self, path):
            if path.endswith('/json'):
                return {'id': 'syn1', 'Age': 1.5}
            if path.endswith('/schema/binding'):
                raise RuntimeError('404 No JSON schema found')
            raise AssertionError(path)

    plan = [{'action': 'drop_stray', 'stray_key': 'Age', 'canonical_key': 'age'}]
    report = fix.schema_preflight(
        UnboundStub(), [_planned('syn1', plan)], registry=registry, repo_version='11.1.22')
    assert [r.status for r in report.unvalidatable] == ['unbound']
    assert report.proven == 0
    assert not report.ok


def test_schema_preflight_does_not_count_a_still_invalid_entity_as_proven():
    # `still_invalid` is not a regression, so it does not block - but the entity
    # fails validation both before and after, so reporting it as "proven to leave
    # the entity conformant" is the same overstatement the unvalidatable gates
    # were added to remove.
    import validate_annotations as validate

    registry = validate.SchemaRegistry.load()
    fixture = Path(__file__).parent / 'data' / 'annotation_keys' / 'syn64420376_entity_json.json'
    instance = json.loads(fixture.read_text())
    instance.pop('fileFormat')

    class SchemaStub:
        def restGET(self, path):
            if path.endswith('/json'):
                return json.loads(json.dumps(instance))
            if path.endswith('/schema/binding'):
                return {'jsonSchemaVersionInfo': {
                    'schemaName': 'microscopyassaytemplate',
                    'semanticVersion': '11.1.22',
                    '$id': 'org.synapse.nf-microscopyassaytemplate-11.1.22',
                }}
            raise AssertionError(path)

    plan = [{'action': 'drop_stray', 'stray_key': 'Age', 'canonical_key': 'age'}]
    report = fix.schema_preflight(
        SchemaStub(), [_planned('syn64420376', plan)], registry=registry, repo_version='11.1.22')
    assert [r.status for r in report.still_invalid] == ['still_invalid']
    assert report.blockers == []
    assert report.unvalidatable == []
    assert report.proven == 0
    # Not a blocker: the failure predates the plan and the plan does not worsen it.
    assert report.ok


def test_schema_preflight_validates_an_unbound_entity_against_its_component():
    # The Component annotation still records which template the curator intended,
    # so an unbound-but-annotated entity is checked rather than written off - the
    # same fallback the standalone validate_annotations tool applies.
    import validate_annotations as validate

    registry = validate.SchemaRegistry.load()
    fixture = Path(__file__).parent / 'data' / 'annotation_keys' / 'syn64420376_entity_json.json'
    instance = json.loads(fixture.read_text())

    class UnboundStub:
        def restGET(self, path):
            if path.endswith('/json'):
                return json.loads(json.dumps(instance))
            if path.endswith('/schema/binding'):
                raise RuntimeError('404 No JSON schema found')
            raise AssertionError(path)

    plan = [{'action': 'drop_stray', 'stray_key': 'Age', 'canonical_key': 'age'}]
    report = fix.schema_preflight(
        UnboundStub(),
        [_planned('syn64420376', plan, {'Component': [instance['Component']]})],
        registry=registry, repo_version='11.1.22',
    )
    assert report.unvalidatable == []
    assert report.blockers == []
    assert report.ok


def test_schema_preflight_treats_an_unplannable_dry_run_as_unvalidatable():
    # A dry run whose read failed produces no plan. Dropping it from the gate is
    # how an entity reached the write pass with no conformance verdict behind it
    # at all, while the success line - counting only what it could see - still
    # read as a clean pass.
    import validate_annotations as validate

    registry = validate.SchemaRegistry.load()

    class NeverCalled:
        def restGET(self, path):
            raise AssertionError(f'the preflight should not have reached {path}')

    failed = fix.ApplyResult('syn_unreadable', 'error', error='RuntimeError: 503')
    report = fix.schema_preflight(NeverCalled(), [failed], registry=registry)
    assert [r.entity_id for r in report.unvalidatable] == ['syn_unreadable']
    assert report.unvalidatable[0].error == 'RuntimeError: 503'
    assert report.proven == 0
    assert report.unaccounted == []
    assert not report.ok


def test_schema_preflight_accounts_for_an_entity_with_nothing_to_change():
    # A no-op is genuinely harmless - the write pass has nothing to break - but it
    # still has to be accounted for, or the totals stop reconciling.
    import validate_annotations as validate

    report = fix.schema_preflight(
        None, [fix.ApplyResult('syn_noop', 'noop', planned={'age': [1.5]})],
        registry=validate.SchemaRegistry.load())
    assert report.unchanged == ['syn_noop']
    assert report.checked == 0
    assert report.unaccounted == []
    assert report.ok


def test_an_entity_in_no_bucket_is_reported_as_unaccounted():
    # The gate's value rests on every entity sitting in exactly one bucket, so a
    # bucketing bug must fail loudly rather than shrink the denominator quietly.
    report = fix.PreflightReport(considered=['syn1', 'syn2'], unchanged=['syn1'])
    assert report.unaccounted == ['syn2']
    assert not report.ok

    report.unchanged.append('syn2')
    assert report.unaccounted == []
    assert report.ok

    # Double-counting is the other direction and equally untrustworthy.
    report.unchanged.append('syn2')
    assert report.unaccounted == ['syn2']
    assert not report.ok


@pytest.mark.parametrize('values,expected', [
    ({'Component': ['MicroscopyAssayTemplate']}, 'MicroscopyAssayTemplate'),
    ({'component': ['GenomicsAssayTemplate']}, 'GenomicsAssayTemplate'),
    ({'Component': []}, None),
    ({'Component': ['  ']}, None),
    ({}, None),
    (None, None),
])
def test_component_of_reads_either_casing_and_tolerates_absence(values, expected):
    assert fix.component_of(values) == expected


@pytest.mark.parametrize('healthy', [60, 500])
def test_the_circuit_breaker_trips_when_writes_start_failing_mid_run(
        monkeypatch, tmp_path, healthy):
    # The point of the breaker is that a systemic problem - a revoked token, a
    # service degradation, an ACL changed mid-run - stops the run where it
    # starts. Hence the trailing window: a whole-run rate needs ~56 consecutive
    # failures to clear 10% after a healthy prefix of 500, and the longer the
    # prefix the worse it gets.
    class FlakySynapse:
        def __init__(self, healthy):
            self.healthy = healthy
            self.reads = 0

        def restGET(self, path):
            if path.endswith('/permissions'):
                return {'canEdit': True}
            self.reads += 1
            if self.reads > self.healthy:
                raise RuntimeError('503 Service Unavailable')
            entity_id = path.split('/')[2]
            return {'id': entity_id, 'etag': 'etag-1',
                    'annotations': to_typed({'Age': [1.5], 'age': [1.5]})}

    syn = FlakySynapse(healthy=healthy)
    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', lambda: syn)

    argv = ['--actions', 'drop_stray', '--log-dir', str(tmp_path / 'run')]
    for index in range(1000):
        argv += ['--entity', f'syn{index}']
    assert fix.main(argv) == 1
    # Six failures in the trailing window of 50 clears 10%, so it aborts within a
    # handful of entities of the degradation regardless of how healthy the run
    # was beforehand - nowhere near 1,000.
    assert syn.reads == healthy + 6


def test_the_circuit_breaker_guards_a_run_shorter_than_the_full_window(monkeypatch, tmp_path):
    # A curator applying to 30 entities by hand with a revoked token must not
    # issue all 30 failing calls. Requiring the window to be full left every run
    # shorter than it completely unguarded.
    class DeadSynapse:
        def __init__(self):
            self.reads = 0

        def restGET(self, path):
            if path.endswith('/permissions'):
                return {'canEdit': True}
            self.reads += 1
            raise RuntimeError('403 Forbidden')

    syn = DeadSynapse()
    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', lambda: syn)

    argv = ['--actions', 'drop_stray', '--log-dir', str(tmp_path / 'run')]
    for index in range(30):
        argv += ['--entity', f'syn{index}']
    assert fix.main(argv) == 1
    assert syn.reads == fix.ERROR_FLOOR


def test_a_run_below_the_floor_is_not_aborted_by_one_failure(monkeypatch, tmp_path):
    # The floor is what keeps a single transient failure from aborting a
    # three-entity run, so the breaker stays worth leaving on.
    class OneBadEntity:
        def __init__(self):
            self.reads = 0

        def restGET(self, path):
            self.reads += 1
            entity_id = path.split('/')[2]
            if entity_id == 'syn0':
                raise RuntimeError('503 Service Unavailable')
            return {'id': entity_id, 'etag': 'etag-1',
                    'annotations': to_typed({'Age': [1.5], 'age': [1.5]})}

    syn = OneBadEntity()
    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', lambda: syn)

    argv = ['--actions', 'drop_stray', '--log-dir', str(tmp_path / 'run'),
            '--entity', 'syn0', '--entity', 'syn1', '--entity', 'syn2']
    assert fix.main(argv) == 1
    assert syn.reads == 3


def _half_broken_synapse(unreadable='syn_unreadable', schema_name='microscopyassaytemplate'):
    """A client that serves one healthy entity and one whose read always fails."""
    fixture = Path(__file__).parent / 'data' / 'annotation_keys' / 'syn64420376_entity_json.json'
    instance = json.loads(fixture.read_text())

    class HalfBrokenSynapse:
        def __init__(self):
            self.writes = []
            self.annotation_reads = []

        def restGET(self, path):
            entity_id = path.split('/')[2]
            if path.endswith('/permissions'):
                return {'canEdit': True, 'canCertifiedUserEdit': True}
            if path.endswith('/annotations2'):
                if entity_id == unreadable:
                    raise RuntimeError('503 Service Unavailable')
                self.annotation_reads.append(entity_id)
                if entity_id.startswith('syn_clean'):
                    # Nothing to fix, so the dry run settles it as a noop and
                    # writes a progress line.
                    return {'id': entity_id, 'etag': 'etag-1',
                            'annotations': to_typed({'age': [1.5]})}
                return {'id': entity_id, 'etag': 'etag-1',
                        'annotations': to_typed({'Age': [1.5], 'age': [1.5],
                                                 'Component': ['MicroscopyAssayTemplate']})}
            if path.endswith('/json'):
                return json.loads(json.dumps(instance))
            if path.endswith('/schema/binding'):
                return {'jsonSchemaVersionInfo': {
                    'schemaName': schema_name,
                    'semanticVersion': '11.1.22',
                    '$id': f'org.synapse.nf-{schema_name}-11.1.22',
                }}
            raise AssertionError(path)

        def restPUT(self, path, body):
            self.writes.append(path)
            raise AssertionError(f'unexpected write to {path}')

    return HalfBrokenSynapse()


def test_the_preflight_refuses_an_apply_whose_dry_run_read_failed(monkeypatch, tmp_path):
    # End to end: the entity whose read failed has no plan, so it used to be
    # filtered out of the gate entirely and then mutated by the write pass with
    # no conformance verdict behind it.
    syn = _half_broken_synapse()
    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', lambda: syn)

    blocked = tmp_path / 'run'
    assert fix.main(['--actions', 'drop_stray', '--validate-schema', '--apply', '--yes',
                     '--log-dir', str(blocked),
                     '--entity', 'syn64420376', '--entity', 'syn_unreadable']) == 1
    # Refused at the gate, so the write pass never ran and nothing was mutated.
    assert not (blocked / 'report.csv').exists()
    assert syn.writes == []

    # The escape hatch is the same one the other unvalidatable statuses use.
    allowed = tmp_path / 'run2'
    monkeypatch.setattr(fix, '_SYN', None)
    fix.main(['--actions', 'drop_stray', '--validate-schema', '--log-dir', str(allowed),
              '--allow-unvalidatable', '--entity', 'syn64420376', '--entity', 'syn_unreadable'])
    assert (allowed / 'report.csv').exists()


def test_a_dry_run_still_writes_the_report_when_an_entity_could_not_be_validated(
    monkeypatch, tmp_path
):
    # A dry run mutates nothing, so there is nothing for the gate to protect - and
    # report.csv is exactly what a curator triages the unvalidatable entity from.
    # Withholding it made --allow-unvalidatable the path of least resistance.
    syn = _half_broken_synapse()
    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', lambda: syn)

    log_dir = tmp_path / 'dryrun'
    exit_code = fix.main(['--actions', 'drop_stray', '--validate-schema',
                          '--log-dir', str(log_dir),
                          '--entity', 'syn64420376', '--entity', 'syn_unreadable'])
    assert exit_code != 0
    assert (log_dir / 'report.csv').exists()
    reported = (log_dir / 'report.csv').read_text()
    assert 'syn_unreadable' in reported
    assert syn.writes == []


def test_a_dry_run_blocked_only_by_an_unvalidatable_entity_exits_two(monkeypatch, tmp_path):
    # The entity reads fine and has a plan; only its schema is absent from this
    # checkout. Nothing failed, so exit 1 would be wrong - but the plan is not
    # one --apply would accept, so exit 0 would be wrong too.
    syn = _half_broken_synapse(unreadable='syn_nothing_is_unreadable',
                               schema_name='notatemplateinthischeckout')
    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', lambda: syn)

    log_dir = tmp_path / 'dryrun'
    assert fix.main(['--actions', 'drop_stray', '--validate-schema',
                     '--log-dir', str(log_dir), '--entity', 'syn64420376']) == 2
    assert (log_dir / 'report.csv').exists()
    assert syn.writes == []


def test_the_schema_preflight_planning_loop_is_guarded_by_the_circuit_breaker(
        monkeypatch, tmp_path):
    # The preflight reads every entity too, so leaving its loop unguarded meant a
    # revoked token produced one failing read and one fsynced progress line per
    # entity - up to --max-entities-per-run of them - before the write loop's
    # breaker ever got a chance to fire.
    class DeadSynapse:
        def __init__(self):
            self.reads = 0

        def restGET(self, path):
            if path.endswith('/permissions'):
                return {'canEdit': True}
            self.reads += 1
            raise RuntimeError('403 Forbidden')

    syn = DeadSynapse()
    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', lambda: syn)

    argv = ['--actions', 'drop_stray', '--validate-schema', '--log-dir', str(tmp_path / 'run')]
    for index in range(30):
        argv += ['--entity', f'syn{index}']
    assert fix.main(argv) == 1
    assert syn.reads == fix.ERROR_FLOOR


def test_the_preflight_conformance_loop_is_guarded_by_the_circuit_breaker(monkeypatch, tmp_path):
    # Every per-entity network loop is covered by the same abort guard. Planning
    # succeeds here, so that breaker never trips; the conformance pass then fails
    # on every entity, and each of its reads carries the retry budget - so left
    # unguarded it would pay the full backoff on all 5,000 entities of a real run
    # to reach the same refusal it now reaches in ten.
    class ConformanceOutage:
        def __init__(self):
            self.json_reads = 0

        def restGET(self, path):
            if path.endswith('/permissions'):
                return {'canEdit': True}
            if path.endswith('/annotations2'):
                entity_id = path.split('/')[2]
                return {'id': entity_id, 'etag': 'etag-1',
                        'annotations': to_typed({'Age': [1.5], 'age': [1.5],
                                                 'Component': ['MicroscopyAssayTemplate']})}
            if path.endswith('/json'):
                self.json_reads += 1
                raise RuntimeError('503 Service Unavailable')
            raise AssertionError(path)

        def restPUT(self, path, body):
            raise AssertionError(f'unexpected write to {path}')

    syn = ConformanceOutage()
    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', lambda: syn)

    argv = ['--actions', 'drop_stray', '--validate-schema', '--apply', '--yes',
            '--log-dir', str(tmp_path / 'run')]
    for index in range(30):
        argv += ['--entity', f'syn{index}']
    assert fix.main(argv) == 1
    assert syn.json_reads == fix.ERROR_FLOOR


def test_a_legitimate_missing_schema_does_not_trip_the_conformance_breaker():
    # `no_schema` is a verdict about the data, not a sign the service is failing;
    # tripping on it would abort a run whose entities are simply bound to a
    # template this checkout does not carry.
    import validate_annotations as validate

    class Bound:
        def restGET(self, path):
            if path.endswith('/json'):
                return {'id': path.split('/')[2], 'age': 1.5}
            if path.endswith('/schema/binding'):
                return {'jsonSchemaVersionInfo': {
                    'schemaName': 'notatemplateinthischeckout',
                    'semanticVersion': '11.1.22',
                    '$id': 'org.synapse.nf-notatemplateinthischeckout-11.1.22',
                }}
            raise AssertionError(path)

    plan = [{'action': 'drop_stray', 'stray_key': 'Age', 'canonical_key': 'age'}]
    dry_runs = [_planned(f'syn{index}', plan) for index in range(30)]
    report = fix.schema_preflight(Bound(), dry_runs, registry=validate.SchemaRegistry.load())
    assert not report.aborted
    assert len(report.unvalidatable) == 30


def test_a_dry_run_with_the_preflight_reads_each_entity_once(monkeypatch, tmp_path):
    # The preflight plans every entity from a fresh read; re-planning them in the
    # main loop doubled the /annotations2 reads and wrote a second progress line
    # per unchanged entity, which then inflated what --resume reads back. A write
    # run still re-reads deliberately - re-deciding on fresh data is a safety
    # property, not redundancy.
    syn = _half_broken_synapse(unreadable='syn_nothing_is_unreadable')
    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', lambda: syn)

    log_dir = tmp_path / 'dryrun'
    assert fix.main(['--actions', 'drop_stray', '--validate-schema', '--log-dir', str(log_dir),
                     '--entity', 'syn64420376', '--entity', 'syn_clean1']) == 0
    assert sorted(syn.annotation_reads) == ['syn64420376', 'syn_clean1']

    progress = [json.loads(line) for line
                in (log_dir / 'progress.jsonl').read_text().splitlines() if line]
    assert [p['entity_id'] for p in progress] == ['syn_clean1']
    assert (log_dir / 'report.csv').exists()


def test_an_apply_run_still_re_reads_every_entity_after_the_preflight(monkeypatch, tmp_path):
    syn = _half_broken_synapse(unreadable='syn_nothing_is_unreadable')
    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', lambda: syn)

    # The stub refuses the write, so the run fails - what matters here is that the
    # write pass read the entity again rather than reusing the preflight's plan.
    assert fix.main(['--actions', 'drop_stray', '--validate-schema', '--apply', '--yes',
                     '--log-dir', str(tmp_path / 'apply'), '--entity', 'syn64420376']) == 1
    assert syn.annotation_reads == ['syn64420376', 'syn64420376']
    assert syn.writes == ['/entity/syn64420376/annotations2']


def test_the_carry_forward_of_a_resumed_scan_does_not_double_count(tmp_path):
    import audit_annotation_keys as audit

    existing = {
        'syn1': audit.ProjectAudit(project_id='syn1', status='ok'),
        'syn2': audit.ProjectAudit(project_id='syn2', status='forbidden'),
        'syn3': audit.ProjectAudit(project_id='syn3', status='error'),
    }
    # A resumed run rescans everything that was not 'ok'.
    carried = audit.carry_forward(existing, ['syn2', 'syn3'])
    assert [a.project_id for a in carried] == ['syn1']

    # With the fresh results appended, the previously forbidden projects are
    # counted once and as scanned, so the run does not still exit 2 on them.
    fresh = [audit.ProjectAudit(project_id='syn2', status='ok'),
             audit.ProjectAudit(project_id='syn3', status='ok')]
    summary = audit.build_summary(carried + fresh)
    assert summary['projects_total'] == 3
    assert summary['projects_scanned'] == 3
    assert summary['projects_forbidden'] == 0
    assert summary['projects_failed'] == 0


def test_a_project_left_out_of_a_limited_rescan_keeps_its_recorded_status(tmp_path):
    # --limit can cut a project out of the rescan; its previous audit still has
    # to be reported rather than vanishing from the run.
    import audit_annotation_keys as audit

    existing = {
        'syn1': audit.ProjectAudit(project_id='syn1', status='ok'),
        'syn2': audit.ProjectAudit(project_id='syn2', status='forbidden'),
    }
    carried = audit.carry_forward(existing, ['syn1'])
    assert [(a.project_id, a.status) for a in carried] == [('syn2', 'forbidden')]


def test_apply_requires_at_least_one_action():
    parser = fix.build_parser()
    args = parser.parse_args(['--project', 'syn1', '--apply', '--actions', 'drop_stray'])
    assert args.apply is True
    assert args.actions == 'drop_stray'


def test_apply_without_actions_is_refused_rather_than_defaulting_to_a_drop(monkeypatch, tmp_path):
    # `--actions` has no default, so a scripted `--apply --yes` cannot delete
    # stray keys across a findings file without naming the action.
    assert fix.build_parser().parse_args(['--apply']).actions is None

    def explode():
        raise AssertionError('must not reach Synapse without --actions')

    monkeypatch.setattr(fix, '_SYN', None)
    monkeypatch.setattr(fix, '_login', explode)
    with pytest.raises(SystemExit):
        fix.main(['--entity', 'syn1', '--apply', '--yes', '--log-dir', str(tmp_path / 'run')])
