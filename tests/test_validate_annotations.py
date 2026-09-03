#!/usr/bin/env python3
"""
Tests for schema conformance checking of Synapse entity annotations.

Offline: the Synapse REST surface is stubbed, and the schemas are the real
`registered-json-schemas/*.json` from this repo, so a schema change that would
break the checker fails here.
"""

import csv
import json
import os
import sys
from pathlib import Path

import pytest

utils_path = os.path.join(os.path.dirname(__file__), '..', 'utils')
sys.path.insert(0, utils_path)

import synapse_annotation_io as io  # noqa: E402
import validate_annotations as validate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).parent / 'data' / 'annotation_keys'


class StubSynapse:
    """Serves /entity/{id}/json and /entity/{id}/schema/binding."""

    def __init__(self, instances, bindings=None, missing_binding=()):
        self.instances = instances
        self.bindings = bindings or {}
        self.missing_binding = set(missing_binding)

    def restGET(self, path):
        parts = path.strip('/').split('/')
        entity_id = parts[1]
        if path.endswith('/json'):
            return json.loads(json.dumps(self.instances[entity_id]))
        if path.endswith('/schema/binding'):
            if entity_id in self.missing_binding:
                raise RuntimeError(f"404 Client Error: No JSON schema found for '{entity_id}'")
            return self.bindings[entity_id]
        raise AssertionError(f'unexpected path {path}')


def binding(schema_name, semantic_version):
    return {
        'jsonSchemaVersionInfo': {
            'organizationName': 'org.synapse.nf',
            'schemaName': schema_name,
            '$id': f'org.synapse.nf-{schema_name}-{semantic_version}',
            'semanticVersion': semantic_version,
        }
    }


@pytest.fixture(scope='module')
def registry():
    return validate.SchemaRegistry.load()


# ---------------------------------------------------------------------------
# Schema registry
# ---------------------------------------------------------------------------

def test_registry_maps_synapse_schema_names_to_repo_files(registry):
    # Synapse reports the bound schema name lowercased ('microscopyassaytemplate'),
    # the repo file is PascalCase.
    assert registry.path_for('microscopyassaytemplate').name == 'MicroscopyAssayTemplate.json'
    assert registry.path_for('MicroscopyAssayTemplate').name == 'MicroscopyAssayTemplate.json'
    assert registry.path_for('ImagingAssayTemplate').name == 'ImagingAssayTemplate.json'


def test_registry_covers_every_registered_schema(registry):
    on_disk = list((REPO_ROOT / 'registered-json-schemas').rglob('*.json'))
    assert len(registry.by_name) == len(on_disk)
    # Lowercasing must not collide, or a bound schema would resolve ambiguously.
    assert len({p.name for p in registry.by_name.values()}) == len(on_disk)


def test_registry_returns_none_for_an_unknown_template(registry):
    assert registry.path_for('NoSuchTemplate') is None


# ---------------------------------------------------------------------------
# Instance retrieval
# ---------------------------------------------------------------------------

def test_uses_the_entity_json_synapse_itself_validates(registry):
    # Reconstructing the instance from annotations2 is wrong: Synapse's
    # presentation is schema-driven, flattening some single-value annotations to
    # scalars while leaving others as arrays (`age` -> 1.5 but
    # `individualID` -> ['1119']). Only /entity/{id}/json gets that right.
    instance = {'id': 'syn1', 'age': 1.5, 'individualID': ['1119']}
    syn = StubSynapse({'syn1': instance})
    assert validate.entity_instance(syn, 'syn1') == instance


def test_binding_is_reported_with_its_semantic_version():
    syn = StubSynapse({}, {'syn1': binding('microscopyassaytemplate', '11.1.22')})
    info = validate.bound_schema(syn, 'syn1')
    assert info.schema_name == 'microscopyassaytemplate'
    assert info.semantic_version == '11.1.22'


def test_missing_binding_is_not_an_error():
    # Plenty of entities have no bound schema; that is a reportable state, not a
    # crash.
    syn = StubSynapse({}, {}, missing_binding=['syn1'])
    assert validate.bound_schema(syn, 'syn1') is None


# ---------------------------------------------------------------------------
# Conformance before and after the planned fix
# ---------------------------------------------------------------------------

def test_dropping_stray_keys_keeps_a_valid_entity_valid(registry):
    instance = json.loads((FIXTURE_DIR / 'syn64420376_entity_json.json').read_text())
    schema = registry.load_schema('microscopyassaytemplate')

    before = validate.validate_instance(instance, schema)
    assert before.is_valid, before.messages

    strays = [k for k in instance if k[:1].isupper()
              and k not in ('Component', 'Filename', 'Id', 'Uuid', 'EntityId')]
    assert len(strays) >= 15
    after = validate.validate_instance(
        validate.apply_key_changes(instance, drop=strays, rename={}), schema)
    assert after.is_valid, after.messages


def test_renaming_an_orphan_can_repair_a_required_key(registry):
    # The whole reason orphans are renamed rather than deleted: the value is real
    # and the schema wants it under the canonical name. Built from the real
    # captured instance, because this template requires seven properties and a
    # hand-rolled minimal dict would fail for unrelated reasons.
    schema = registry.load_schema('microscopyassaytemplate')
    valid = json.loads((FIXTURE_DIR / 'syn64420376_entity_json.json').read_text())
    assert validate.validate_instance(valid, schema).is_valid

    orphaned = validate.apply_key_changes(valid, drop=[], rename={'fileFormat': 'FileFormat'})
    before = validate.validate_instance(orphaned, schema)
    assert not before.is_valid
    assert any('fileFormat' in m for m in before.messages)

    after = validate.validate_instance(
        validate.apply_key_changes(orphaned, drop=[], rename={'FileFormat': 'fileFormat'}), schema)
    assert after.is_valid, after.messages


def test_a_fix_that_would_break_conformance_is_detected(registry):
    # The guard that must exist: dropping a key the schema requires has to be
    # caught by the dry run, not discovered after the write.
    schema = registry.load_schema('microscopyassaytemplate')
    valid = json.loads((FIXTURE_DIR / 'syn64420376_entity_json.json').read_text())
    assert validate.validate_instance(valid, schema).is_valid

    broken = validate.apply_key_changes(valid, drop=['fileFormat'], rename={})
    outcome = validate.validate_instance(broken, schema)
    assert not outcome.is_valid
    assert validate.classify_transition(True, outcome.is_valid) == 'regression'


def test_apply_key_changes_does_not_mutate_its_input():
    instance = {'Age': 1.5, 'age': 1.5}
    before = dict(instance)
    validate.apply_key_changes(instance, drop=['Age'], rename={})
    assert instance == before


def test_apply_key_changes_renames_by_moving_the_value():
    result = validate.apply_key_changes({'Nf2Genotype': '-/-'}, drop=[], rename={'Nf2Genotype': 'nf2Genotype'})
    assert result == {'nf2Genotype': '-/-'}


def test_apply_key_changes_ignores_keys_that_are_absent():
    # The instance comes from Synapse's schema-driven JSON, which can omit a key
    # the annotation plan names; that must not raise here.
    assert validate.apply_key_changes({'age': 1.5}, drop=['Age'], rename={'X': 'x'}) == {'age': 1.5}


# ---------------------------------------------------------------------------
# The predicted post-rename shape has to match what Synapse will render
# ---------------------------------------------------------------------------

def animal_individual_instance():
    """A valid AnimalIndividualTemplate instance built from the real capture.

    The values come from `syn64420376`, whose entity JSON is the evidence that
    Synapse renders `individualID` as an array and `modelSystemName` as a scalar
    on the template bound there; this template declares both as arrays, which is
    exactly the asymmetry the rename shape has to follow.
    """
    captured = json.loads((FIXTURE_DIR / 'syn64420376_entity_json.json').read_text())
    return {
        'Component': 'AnimalIndividualTemplate',
        'individualID': captured['individualID'],
        'species': captured['species'],
        'sex': captured['sex'],
        'diagnosis': captured['diagnosis'],
    }, captured


def test_a_rename_into_an_array_typed_slot_is_not_reported_as_a_regression(registry):
    # The write path stores a renamed value as a list, and Synapse renders an
    # array-typed property as an array. Predicting a scalar here made the
    # preflight report a regression that cannot happen, which aborts the whole
    # rename pass because one blocker exits 1.
    schema = registry.load_schema('AnimalIndividualTemplate')
    assert 'array' in validate.declared_types(schema, 'modelSystemName')

    instance, captured = animal_individual_instance()
    instance['ModelSystemName'] = captured['modelSystemName']
    before = validate.validate_instance(instance, schema)
    assert before.is_valid, before.messages

    renamed = validate.apply_key_changes(
        instance, drop=[], rename={'ModelSystemName': 'modelSystemName'}, schema=schema)
    assert renamed['modelSystemName'] == [captured['modelSystemName']]
    after = validate.validate_instance(renamed, schema)
    assert after.is_valid, after.messages
    assert validate.classify_transition(before.is_valid, after.is_valid) == 'clean'


def test_a_rename_into_a_scalar_slot_unwraps_a_single_value(registry):
    # The mirror case: `sex` is declared a string, so Synapse renders it
    # unwrapped, and predicting a one-item array would invent a regression too.
    schema = registry.load_schema('AnimalIndividualTemplate')
    assert validate.declared_types(schema, 'sex') == frozenset({'string'})

    instance, captured = animal_individual_instance()
    del instance['sex']
    instance['Sex'] = [captured['sex']]
    renamed = validate.apply_key_changes(
        instance, drop=[], rename={'Sex': 'sex'}, schema=schema)
    assert renamed['sex'] == captured['sex']
    assert validate.validate_instance(renamed, schema).is_valid


def test_the_declared_shape_matches_how_synapse_actually_renders_the_entity(registry):
    # The check that makes the whole prediction trustworthy: on the real
    # syn64420376 capture, every property MicroscopyAssayTemplate types is
    # rendered as an array exactly when the schema says `array` - `individualID`
    # is, the other 15 are not. If that correspondence ever breaks, coercing to
    # the declared shape is the wrong model and this must fail.
    schema = registry.load_schema('microscopyassaytemplate')
    instance = json.loads((FIXTURE_DIR / 'syn64420376_entity_json.json').read_text())
    typed = {key: validate.declared_types(schema, key) for key in instance}
    typed = {key: types for key, types in typed.items() if types}
    assert len(typed) >= 16
    for key, types in typed.items():
        assert isinstance(instance[key], list) == ('array' in types), key


def test_a_rename_target_the_schema_does_not_type_keeps_its_shape(registry):
    # A stray PascalCase key is not in any schema, so there is nothing to coerce
    # toward and the value must be moved verbatim.
    schema = registry.load_schema('microscopyassaytemplate')
    assert validate.declared_types(schema, 'FileFormat') == frozenset()
    result = validate.apply_key_changes(
        {'fileFormat': 'png'}, drop=[], rename={'fileFormat': 'FileFormat'}, schema=schema)
    assert result == {'FileFormat': 'png'}


def test_declared_types_sees_through_the_concretetype_guard(registry):
    # MicroscopyAssayTemplate declares almost nothing at the top level: the real
    # declarations sit under allOf[0].then, gated on concreteType == FileEntity.
    # A top-level-only lookup would find no type for exactly the properties that
    # matter, including the array-typed individualID.
    schema = registry.load_schema('microscopyassaytemplate')
    assert 'properties' not in schema
    assert validate.declared_types(schema, 'individualID') == frozenset({'array'})
    assert validate.declared_types(schema, 'fileFormat') == frozenset({'string'})


def test_a_multi_value_rename_into_a_scalar_slot_stays_a_list(registry):
    # Two values genuinely do not fit a scalar property. Silently keeping only
    # the first would hide a real finding.
    schema = registry.load_schema('AnimalIndividualTemplate')
    result = validate.apply_key_changes(
        {'Sex': ['Female', 'Male']}, drop=[], rename={'Sex': 'sex'}, schema=schema)
    assert result == {'sex': ['Female', 'Male']}


def test_declared_types_reads_through_anyof_branches(registry):
    # `age` is declared as anyOf[number, AgeMask enum]; the type sits inside the
    # branches, not on the property.
    schema = registry.load_schema('AnimalIndividualTemplate')
    assert validate.declared_types(schema, 'age') == frozenset({'number', 'string'})


def test_check_entity_uses_the_bound_schema_for_the_predicted_shape(registry):
    # End to end through check_entity: the same rename that used to come back as
    # `regression` has to come back `clean`.
    instance, captured = animal_individual_instance()
    instance['ModelSystemName'] = captured['modelSystemName']
    syn = StubSynapse({'syn1': instance},
                      {'syn1': binding('animalindividualtemplate', '11.1.22')})
    outcome = validate.check_entity(
        syn, 'syn1', registry=registry,
        decisions=[{'action': 'rename_stray', 'stray_key': 'ModelSystemName',
                    'canonical_key': 'modelSystemName'}],
    )
    assert outcome.status == 'clean', outcome.after_messages
    assert not outcome.blocking


class FlakySynapse(StubSynapse):
    """Fails the first ``failures`` reads of each path with a transient error."""

    def __init__(self, *args, failures=0, status=503, **kwargs):
        super().__init__(*args, **kwargs)
        self.failures = failures
        self.status = status
        self.attempts = 0

    def restGET(self, path):
        self.attempts += 1
        if self.failures > 0:
            self.failures -= 1

            class _Response:
                status_code = self.status

            error = RuntimeError(f'{self.status} transient')
            error.response = _Response()
            raise error
        return super().restGET(path)


def test_a_transient_read_failure_does_not_make_an_entity_unvalidatable(registry, monkeypatch):
    # The fix tool's preflight refuses an entire --apply run over one entity it
    # could not validate, and the only escape hatch discards the gate for every
    # entity - so one 503 among thousands must not cost the whole write pass.
    monkeypatch.setattr(io.time, 'sleep', lambda _seconds: None)
    instance, _ = animal_individual_instance()
    syn = FlakySynapse({'syn1': instance},
                       {'syn1': binding('animalindividualtemplate', '11.1.22')},
                       failures=2)

    outcome = validate.check_entity(syn, 'syn1', registry=registry, max_retries=3)
    assert outcome.status != 'error', outcome.error
    assert syn.attempts == 4  # two lost, then the instance and the binding


def test_the_conformance_loop_stops_when_the_service_stops_answering(tmp_path, monkeypatch):
    # The last per-entity network loop without an abort guard. Each read carries a
    # retry budget, so a systemic 503 costs over a minute of jittered backoff per
    # entity - days of grinding over the 13,150-entity findings file to reach a
    # report that is nothing but errors.
    monkeypatch.setattr(io.time, 'sleep', lambda _seconds: None)
    reads = []

    class DeadSynapse:
        def restGET(self, path):
            reads.append(path)
            raise RuntimeError('503 Service Unavailable')

    monkeypatch.setattr(validate, '_login', lambda: DeadSynapse())
    findings = tmp_path / 'entity_findings.jsonl'
    findings.write_text(''.join(
        json.dumps({'project_id': 'syn0', 'entity_id': f'syn{n}', 'decisions': []}) + '\n'
        for n in range(200)))
    report = tmp_path / 'conformance.md'
    csv_path = tmp_path / 'conformance.csv'

    assert validate.main(['--findings', str(findings), '--max-retries', '0',
                          '--markdown', str(report), '--report', str(csv_path)]) == 1
    assert len(reads) == io.ERROR_FLOOR, 'it stops at the floor rather than reading all 200'
    # And the document says it covers part of the plan rather than reading as a
    # complete verdict over a smaller set of entities.
    document = report.read_text()
    assert '190 entities were never checked' in document
    assert 'does not break conformance anywhere' not in document
    # The CSV says the same, so neither artifact can be mistaken for a full pass.
    rows = list(csv.DictReader(csv_path.read_text().splitlines()))
    assert sum(row['status'] == 'not_checked' for row in rows) == 190


def test_a_legitimate_verdict_about_the_data_does_not_stop_the_conformance_loop(
        tmp_path, monkeypatch, registry):
    # `unbound` is a fact about the entity, which is exactly what this pass exists
    # to surface; tripping on it would abort a run over entities that simply have no
    # schema bound.
    instance, _ = animal_individual_instance()
    syn = StubSynapse({f'syn{n}': instance for n in range(40)},
                      missing_binding=[f'syn{n}' for n in range(40)])
    monkeypatch.setattr(validate, '_login', lambda: syn)
    findings = tmp_path / 'entity_findings.jsonl'
    findings.write_text(''.join(
        json.dumps({'project_id': 'syn0', 'entity_id': f'syn{n}', 'decisions': []}) + '\n'
        for n in range(40)))

    assert validate.main(['--findings', str(findings), '--markdown',
                          str(tmp_path / 'report.md')]) == 0


def test_entities_the_curator_cannot_read_do_not_stop_the_conformance_loop(
        tmp_path, monkeypatch):
    # A 403 is never retried, so every one of them landed in the breaker's window at
    # once and two were enough to abort the pass - deterministically, so re-running
    # reproduced it. The service answered: that is a fact about those entities.
    reads = []

    class ForbiddenSynapse:
        def restGET(self, path):
            reads.append(path)

            class _Response:
                status_code = 403

            error = RuntimeError('403 Forbidden')
            error.response = _Response()
            raise error

    monkeypatch.setattr(validate, '_login', lambda: ForbiddenSynapse())
    findings = tmp_path / 'entity_findings.jsonl'
    findings.write_text(''.join(
        json.dumps({'project_id': 'syn0', 'entity_id': f'syn{n}', 'decisions': []}) + '\n'
        for n in range(40)))
    markdown = tmp_path / 'conformance.md'

    # Exit 2, not 1: every entity is an error, and none of them stopped the pass.
    assert validate.main(['--findings', str(findings), '--max-retries', '0',
                          '--markdown', str(markdown)]) == 2
    assert len(reads) == 40
    assert 'never checked' not in markdown.read_text()


def test_a_truncated_pass_does_not_claim_the_fix_breaks_conformance_nowhere():
    # 'None. The planned fix does not break conformance anywhere.' is the sentence an
    # operator quotes when deciding to run --apply, and the entities a cut-short pass
    # never checked could hold any number of regressions.
    checked = [validate.EntityConformance(entity_id='syn1', status='clean',
                                          before_valid=True, after_valid=True)]
    truncated = validate.format_markdown(checked, not_checked=13_140)

    assert 'does not break conformance anywhere' not in truncated
    assert 'None among the 1 entities checked' in truncated
    assert '13140 were never checked' in truncated
    # A pass that finished still says so plainly.
    assert 'None. The planned fix does not break conformance anywhere.' \
        in validate.format_markdown(checked)


def test_a_truncated_report_csv_names_the_entities_it_never_checked(tmp_path):
    # Otherwise the artifact reads as a complete pass over a smaller plan, exactly as
    # the fix tool's report.csv did before it grew not_attempted rows.
    checked = [validate.EntityConformance(entity_id='syn1', status='clean')]
    path = tmp_path / 'conformance.csv'
    validate.write_report(checked, path, not_checked=['syn2', 'syn3'])

    rows = list(csv.DictReader(path.read_text().splitlines()))
    assert [(row['entity_id'], row['status']) for row in rows] == [
        ('syn1', 'clean'), ('syn2', 'not_checked'), ('syn3', 'not_checked')]
    assert 'aborted by the circuit breaker' in rows[1]['error']


def _http_error(message, status):
    class _Response:
        status_code = status

    error = RuntimeError(message)
    error.response = _Response()
    return error


def test_a_server_error_on_an_id_containing_404_is_not_read_as_unbound(registry, monkeypatch):
    # 'nothing is bound here' used to be a substring test over the whole message, and
    # synapseclient puts the status, the reason and the entity id in one string - so a
    # 5xx on syn20404567 (roughly one 8-digit id in forty contains '404') read as
    # unbound. Every consequence ran the wrong way for a gate in front of a
    # destructive write: the failure never reached the retry, the breaker counted it
    # as a healthy request, and an entity carrying a Component annotation was then
    # validated against that template rather than against the binding never read.
    monkeypatch.setattr(io.time, 'sleep', lambda _seconds: None)
    instance, _ = animal_individual_instance()
    attempts = []

    class UnreadableBinding(StubSynapse):
        def restGET(self, path):
            if path.endswith('/schema/binding'):
                attempts.append(path)
                raise _http_error('503 Server Error: Service Unavailable for syn20404567', 503)
            return super().restGET(path)

    syn = UnreadableBinding({'syn20404567': instance})
    with pytest.raises(RuntimeError):
        validate.bound_schema(syn, 'syn20404567')

    outcome = validate.check_entity(syn, 'syn20404567', registry=registry,
                                    fallback_component='AnimalIndividualTemplate',
                                    max_retries=2)
    assert outcome.status == 'error', 'a lost binding read is not a verdict about the entity'
    assert outcome.breaker_sample is True
    assert len(attempts) == 4, 'and it is retried like any other transient failure'


def test_a_404_on_the_binding_still_means_nothing_is_bound(registry):
    instance, _ = animal_individual_instance()

    class NoBinding(StubSynapse):
        def restGET(self, path):
            if path.endswith('/schema/binding'):
                raise _http_error('404 Client Error: Not Found', 404)
            return super().restGET(path)

    assert validate.bound_schema(NoBinding({'syn1': instance}), 'syn1') is None
    assert validate.check_entity(NoBinding({'syn1': instance}), 'syn1',
                                 registry=registry).status == 'unbound'


class CachedVerdictSynapse(StubSynapse):
    """Also serves /entity/{id}/schema/validation, however ``cached`` says."""

    def __init__(self, *args, cached=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cached = cached
        self.validation_reads = 0

    def restGET(self, path):
        if path.endswith('/schema/validation'):
            self.validation_reads += 1
            if isinstance(self.cached, Exception):
                raise self.cached
            return self.cached
        return super().restGET(path)


def test_no_cached_verdict_is_distinguishable_from_a_cached_verdict_that_could_not_be_read(
        registry, monkeypatch):
    # One blank cell used to stand for two opposite things - 'Synapse has never
    # validated this' and 'the comparison did not happen' - and the row still read as
    # a successful comparison.
    monkeypatch.setattr(io.time, 'sleep', lambda _seconds: None)
    instance, _ = animal_individual_instance()
    bindings = {'syn1': binding('animalindividualtemplate', '11.1.22')}

    absent = CachedVerdictSynapse({'syn1': instance}, bindings,
                                  cached=_http_error('404 Client Error: Not Found', 404))
    outcome = validate.check_entity(absent, 'syn1', registry=registry, include_cached=True)
    assert outcome.synapse_cached_valid is None and outcome.cached_error is None
    assert outcome.breaker_sample is False

    lost = CachedVerdictSynapse({'syn1': instance}, bindings,
                                cached=_http_error('503 Service Unavailable', 503))
    outcome = validate.check_entity(lost, 'syn1', registry=registry, include_cached=True,
                                    max_retries=2)
    assert outcome.synapse_cached_valid is None
    assert '503' in outcome.cached_error
    # The same retry budget and the same guard as the two reads above it.
    assert lost.validation_reads == 3
    assert outcome.breaker_sample is True
    # The entity's own conformance verdict still stands; only the comparison is gone.
    assert outcome.status == 'clean'


def test_a_lost_cached_read_reaches_the_report_and_the_document(tmp_path, registry):
    lost = validate.EntityConformance(entity_id='syn1', status='clean',
                                      cached_error='RuntimeError: 503 Service Unavailable')
    path = tmp_path / 'conformance.csv'
    validate.write_report([lost], path)

    rows = list(csv.DictReader(path.read_text().splitlines()))
    assert rows[0]['synapse_cached_valid'] == ''
    assert '503' in rows[0]['synapse_cached_error']
    assert "cached verdict could not be read for 1" in validate.format_markdown([lost])


def test_a_forbidden_read_is_not_retried(registry, monkeypatch):
    # A 403 does not become a 200 on the second attempt; retrying only delays the
    # finding.
    monkeypatch.setattr(io.time, 'sleep', lambda _seconds: pytest.fail('403 was retried'))
    instance, _ = animal_individual_instance()
    syn = FlakySynapse({'syn1': instance}, failures=5, status=403)

    outcome = validate.check_entity(syn, 'syn1', registry=registry, max_retries=5)
    assert outcome.status == 'error'
    assert syn.attempts == 1


# ---------------------------------------------------------------------------
# The verdict matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('before,after,expected', [
    (True, True, 'clean'),
    (False, True, 'repaired'),
    (False, False, 'still_invalid'),
    (True, False, 'regression'),
])
def test_transition_classification(before, after, expected):
    assert validate.classify_transition(before, after) == expected


def test_regression_is_the_only_blocking_transition():
    assert validate.BLOCKING_TRANSITIONS == frozenset({'regression'})


# ---------------------------------------------------------------------------
# Version drift against the repo
# ---------------------------------------------------------------------------

def test_binding_matching_the_repo_version_is_not_drift():
    assert not validate.version_drift('11.1.22', '11.1.22')


def test_binding_behind_the_repo_version_is_drift():
    assert validate.version_drift('11.0.20', '11.1.22') == ('behind', '11.0.20', '11.1.22')


def test_binding_ahead_of_the_repo_version_is_drift():
    # Would mean the checkout is stale; validating locally would be misleading.
    assert validate.version_drift('11.2.0', '11.1.22')[0] == 'ahead'


def test_unparseable_versions_are_reported_rather_than_crashing():
    assert validate.version_drift('not-a-version', '11.1.22')[0] == 'unknown'
