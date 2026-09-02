#!/usr/bin/env python3
"""
Tests for schema conformance checking of Synapse entity annotations.

Offline: the Synapse REST surface is stubbed, and the schemas are the real
`registered-json-schemas/*.json` from this repo, so a schema change that would
break the checker fails here.
"""

import json
import os
import sys
from pathlib import Path

import pytest

utils_path = os.path.join(os.path.dirname(__file__), '..', 'utils')
sys.path.insert(0, utils_path)

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
