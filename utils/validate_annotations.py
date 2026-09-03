#!/usr/bin/env python3
"""
Check whether Synapse entity annotations conform to the current NF JSON schemas.

Requires: jsonschema, pyyaml (synapseclient only to build a client). Read-only.

Two jobs:

1. **Is the metadata clean right now?** Validate each entity against the schema
   bound to it, using this checkout's ``registered-json-schemas/`` - i.e. the
   current version of the model, which may be newer than whatever Synapse last
   validated against.
2. **Would a planned annotation-key fix break conformance?** Validate the
   entity again with the planned drops and renames applied. A
   ``valid -> invalid`` transition is a blocker and must stop the fix.

Why ``/entity/{id}/json`` and not a dict rebuilt from annotations
----------------------------------------------------------------
Synapse's JSON presentation of an entity is **schema-driven**, not uniform: on
``syn64420376`` it renders ``age`` as the scalar ``1.5`` but ``individualID`` as
the array ``['1119']``, both single-value STRING/DOUBLE annotations. Rebuilding
the instance by flattening single-item lists produces spurious
"is not of type 'array'" failures. ``/entity/{id}/json`` is the exact document
Synapse validates, so it is the only correct input.

Known wrinkle this surfaces
---------------------------
Synapse's cached validation results can be stale relative to the bound schema
version. ``syn64420357`` reports ``isValid: false`` against
``microscopyassaytemplate-11.0.20`` for missing ``fileFormat``/``resourceType``,
but its binding is 11.1.22, and 11.1.22 restricts those requirements to
FileEntity via a ``concreteType`` guard - so the folder is valid under the
schema actually bound to it. Trust a fresh local check over a stale cached one.

Examples
--------
    # is the metadata on the affected entities clean?
    python utils/validate_annotations.py --findings audit/entity_findings.jsonl

    # would the planned fix break anything?
    python utils/validate_annotations.py --findings audit/entity_findings.jsonl \
        --check-plan --report validation.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from synapse_annotation_io import (  # noqa: E402
    breaker_verdict,
    run_guarded,
    status_of,
    with_retries,
)

LOG = logging.getLogger('validate_annotations')

SCHEMA_DIR = Path(__file__).resolve().parent.parent / 'registered-json-schemas'

#: Transitions that must stop a remediation run.
BLOCKING_TRANSITIONS = frozenset({'regression'})


# ---------------------------------------------------------------------------
# Schema registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SchemaRegistry:
    """The repo's registered JSON schemas, indexed for Synapse's naming.

    Synapse reports a bound schema name lowercased (``microscopyassaytemplate``);
    the repo file is PascalCase (``MicroscopyAssayTemplate.json``). Lowercasing
    is unambiguous across all 70 files, which a test asserts.
    """

    by_name: Mapping[str, Path]

    @classmethod
    def load(cls, schema_dir: Path | str = SCHEMA_DIR) -> SchemaRegistry:
        index: dict[str, Path] = {}
        for path in sorted(Path(schema_dir).rglob('*.json')):
            index[path.stem.lower()] = path
        return cls(by_name=index)

    def path_for(self, schema_name: str) -> Path | None:
        return self.by_name.get(schema_name.lower())

    def load_schema(self, schema_name: str) -> dict | None:
        path = self.path_for(schema_name)
        if path is None:
            return None
        with open(path) as handle:
            return json.load(handle)


# ---------------------------------------------------------------------------
# Synapse reads
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BindingInfo:
    schema_name: str
    semantic_version: str
    schema_id: str


def entity_instance(syn, entity_id: str) -> dict:
    """The JSON document Synapse itself validates for this entity."""
    return syn.restGET(f'/entity/{entity_id}/json')


def bound_schema(syn, entity_id: str) -> BindingInfo | None:
    """The schema bound to this entity, or None when nothing is bound.

    "Nothing is bound" is read off the response status, not off the message. A bare
    ``'404' in str(error)`` also matched a 5xx on an entity whose own synID contains
    those digits - ``syn20404567``, and roughly one 8-digit id in forty -
    because synapseclient puts the status, the reason and the entity id in the same
    string. Every consequence of that ran the wrong way for a gate in front of a
    destructive write: the failure never reached the surrounding retry, the circuit
    breaker counted it as a healthy request, and an entity carrying a ``Component``
    annotation was then validated against the template that annotation names rather
    than against the binding this read never saw.
    """
    try:
        payload = syn.restGET(f'/entity/{entity_id}/schema/binding')
    except Exception as error:  # noqa: BLE001 - an unbound entity is a state, not a failure
        if status_of(error) == 404 or 'No JSON schema found' in str(error):
            return None
        raise
    info = payload.get('jsonSchemaVersionInfo') or {}
    return BindingInfo(
        schema_name=info.get('schemaName', ''),
        semantic_version=info.get('semanticVersion', ''),
        schema_id=info.get('$id', ''),
    )


def synapse_validation_result(syn, entity_id: str) -> dict | None:
    """Synapse's own cached verdict, for comparison. May be stale.

    ``None`` means Synapse holds no verdict for this entity; a read that failed is
    raised, so the caller can report it. Swallowing both into ``None`` left one blank
    cell in the CSV standing for two opposite things - "Synapse has never validated
    this" and "the comparison did not happen" - and the row still read as a
    successful comparison.
    """
    try:
        return syn.restGET(f'/entity/{entity_id}/schema/validation')
    except Exception as error:  # noqa: BLE001 - no stored verdict is a state, not a failure
        if status_of(error) == 404:
            return None
        raise


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationOutcome:
    is_valid: bool
    messages: list[str] = field(default_factory=list)


def validate_instance(instance: Mapping, schema: Mapping) -> ValidationOutcome:
    validator = jsonschema.Draft7Validator(schema)
    messages = []
    for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        location = '/'.join(str(p) for p in error.absolute_path) or '#'
        messages.append(f'{location}: {error.message}')
    return ValidationOutcome(is_valid=not messages, messages=messages)


#: Keywords whose value is a subschema, or a list of them, that can carry a
#: property declaration. The NF templates put most declarations behind
#: ``allOf[].then``, gated on ``concreteType``, so a top-level-only lookup sees
#: nothing for exactly the properties that matter most.
SUBSCHEMA_KEYWORDS = ('allOf', 'anyOf', 'oneOf', 'if', 'then', 'else', 'not')


def _types_declared_by(subschema: Mapping) -> set[str]:
    types: set[str] = set()
    pending = [subschema]
    while pending:
        node = pending.pop()
        if not isinstance(node, Mapping):
            continue
        declared = node.get('type')
        if isinstance(declared, str):
            types.add(declared)
        elif isinstance(declared, list):
            types.update(item for item in declared if isinstance(item, str))
        for keyword in ('anyOf', 'oneOf', 'allOf'):
            pending.extend(node.get(keyword) or [])
    return types


def declared_types(schema: Mapping | None, name: str) -> frozenset[str]:
    """Every JSON type ``schema`` declares for property ``name``, anywhere in it.

    The declaration is collected across conditional branches rather than
    evaluated against an instance: a slot has one shape throughout the model, so
    the union is enough to predict how Synapse will render it, and evaluating the
    ``concreteType`` guards would duplicate the validator for no gain.

    Empty when the schema says nothing about the property - it is absent, or
    appears only as a bare ``{}`` stub inside an ``if``/``then`` guard, which
    constrains presence but not type.
    """
    if not schema:
        return frozenset()
    types: set[str] = set()
    pending: list = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, (list, tuple)):
            pending.extend(node)
            continue
        if not isinstance(node, Mapping):
            continue
        prop = (node.get('properties') or {}).get(name)
        if isinstance(prop, Mapping):
            types |= _types_declared_by(prop)
        for keyword in SUBSCHEMA_KEYWORDS:
            branch = node.get(keyword)
            if branch is not None:
                pending.append(branch)
    return frozenset(types)


def _rendered_as(value, types: frozenset[str]):
    """A moved value in the shape Synapse will render it under its new key.

    ``/entity/{id}/json`` is schema-driven: a property the bound schema declares
    as an array comes back as an array even for a single annotation value, and a
    scalar property comes back unwrapped. Predicting the wrong one is what made
    the preflight report renames into array-typed slots - ``individualID``,
    ``modelSystemName``, ``cellType`` - as regressions that cannot happen.

    A multi-value annotation is left as a list even for a scalar property: that
    genuinely does not fit the schema, and hiding it would suppress a real
    finding.
    """
    if 'array' in types:
        return value if isinstance(value, list) else [value]
    if types and isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def apply_key_changes(
    instance: Mapping,
    *,
    drop: Iterable[str],
    rename: Mapping[str, str],
    schema: Mapping | None = None,
) -> dict:
    """The instance as it would look after a planned fix. Pure.

    Keys named by the plan but absent from the instance are ignored rather than
    raising: Synapse's schema-driven JSON can legitimately omit a key that the
    annotation plan mentions.

    A renamed value is reshaped to what Synapse will render under the canonical
    name once ``annotation_key_policy.apply_decisions`` has written it. The two
    functions work on different shapes on purpose - that one operates on the
    annotations dict, where every value is a list, this one on the entity JSON,
    where a value is a scalar or an array depending on the bound schema - so
    ``schema`` is what keeps the prediction faithful. Without it the shape is
    left alone, which is right for a property the schema does not type.
    """
    result = dict(instance)
    for key in drop:
        result.pop(key, None)
    for stray, canonical in rename.items():
        if stray in result:
            result[canonical] = _rendered_as(result.pop(stray),
                                             declared_types(schema, canonical))
    return result


def classify_transition(before_valid: bool, after_valid: bool) -> str:
    if before_valid and after_valid:
        return 'clean'
    if not before_valid and after_valid:
        return 'repaired'
    if not before_valid and not after_valid:
        return 'still_invalid'
    return 'regression'


def version_drift(bound: str, repo: str) -> tuple[str, str, str] | None:
    """Whether the bound schema version differs from this checkout's.

    Validating locally against a different version than Synapse has bound would
    make the verdict misleading, so any drift is reported.
    """
    if bound == repo:
        return None

    def parts(value: str):
        try:
            return tuple(int(p) for p in value.split('.'))
        except (AttributeError, ValueError):
            return None

    bound_parts, repo_parts = parts(bound), parts(repo)
    if bound_parts is None or repo_parts is None:
        return ('unknown', bound, repo)
    return ('behind' if bound_parts < repo_parts else 'ahead', bound, repo)


# ---------------------------------------------------------------------------
# Per-entity check
# ---------------------------------------------------------------------------

@dataclass
class EntityConformance:
    entity_id: str
    project_id: str = ''
    schema_name: str = ''
    bound_version: str = ''
    drift: str = ''
    status: str = ''            # clean | repaired | still_invalid | regression | unbound | no_schema | error
    before_valid: bool | None = None
    after_valid: bool | None = None
    before_messages: list[str] = field(default_factory=list)
    after_messages: list[str] = field(default_factory=list)
    synapse_cached_valid: bool | None = None
    #: Why ``synapse_cached_valid`` is blank, when the reason is a lost read rather
    #: than Synapse holding no verdict. The two mean opposite things when triaging.
    cached_error: str | None = None
    error: str | None = None
    #: How the circuit breaker samples the reads behind this outcome. ``status`` alone
    #: cannot say: ``error`` covers a 503, a 403 on an entity the caller cannot see
    #: and a 404 on one deleted since the audit, and only the first is a sign that
    #: the service is failing. ``None`` keeps a definitive answer out of the window
    #: entirely - see ``synapse_annotation_io.breaker_verdict``.
    breaker_sample: bool | None = False

    @property
    def blocking(self) -> bool:
        return self.status in BLOCKING_TRANSITIONS


def plan_from_decisions(decisions: Sequence[Mapping]) -> tuple[list[str], dict[str, str]]:
    """Split a decision list into the drops and renames a fix would perform."""
    drop = [d['stray_key'] for d in decisions if d.get('action') == 'drop_stray']
    rename = {
        d['stray_key']: d['canonical_key']
        for d in decisions if d.get('action') == 'rename_stray' and d.get('canonical_key')
    }
    return drop, rename


def check_entity(
    syn,
    entity_id: str,
    *,
    registry: SchemaRegistry,
    repo_version: str | None = None,
    decisions: Sequence[Mapping] = (),
    project_id: str = '',
    fallback_component: str | None = None,
    include_cached: bool = False,
    max_retries: int = 0,
) -> EntityConformance:
    result = EntityConformance(entity_id=entity_id, project_id=project_id)
    try:
        # Both reads ride out a transient failure. A 503 among thousands of
        # entities is not a verdict about the entity, and the fix tool's preflight
        # refuses a whole write run over one entity it could not validate - so
        # without a retry budget one blip costs the entire pass. A 403 still fails
        # fast: with_retries never retries an authorisation failure.
        instance = with_retries(lambda: entity_instance(syn, entity_id),
                                max_retries=max_retries, label=entity_id, logger=LOG)
        binding = with_retries(lambda: bound_schema(syn, entity_id),
                               max_retries=max_retries, label=entity_id, logger=LOG)
    except Exception as error:  # noqa: BLE001
        result.status = 'error'
        result.error = f'{type(error).__name__}: {error}'[:250]
        # A 403 or a 404 here is a fact about this entity, so it is reported as one
        # and kept out of the abort guard's window; a 503 or a dropped connection is
        # what that guard exists to notice.
        result.breaker_sample = breaker_verdict(error)
        return result

    schema_name = binding.schema_name if binding else (fallback_component or '')
    if binding:
        result.schema_name = binding.schema_name
        result.bound_version = binding.semantic_version
        if repo_version:
            drift = version_drift(binding.semantic_version, repo_version)
            result.drift = '' if drift is None else f'{drift[0]} ({drift[1]} vs {drift[2]})'
    elif fallback_component:
        # No binding, but the Component annotation still says which template the
        # curator intended, which is worth checking against.
        result.schema_name = f'{fallback_component} (from Component, not bound)'
    else:
        result.status = 'unbound'
        return result

    schema = registry.load_schema(schema_name) if schema_name else None
    if schema is None:
        result.status = 'no_schema'
        result.error = f'no registered schema named {schema_name!r} in this checkout'
        return result

    if include_cached:
        # The same retry budget and the same guard as the two reads above: this is a
        # per-entity request like any other, and it was the one in this loop that was
        # neither retried nor sampled.
        try:
            cached = with_retries(lambda: synapse_validation_result(syn, entity_id),
                                  max_retries=max_retries, label=entity_id, logger=LOG)
        except Exception as error:  # noqa: BLE001 - the comparison is auxiliary
            LOG.warning('%s: could not read the cached validation result: %s', entity_id, error)
            result.cached_error = f'{type(error).__name__}: {error}'[:250]
            # The entity's own conformance verdict stands; only the comparison is
            # missing. A definitive answer leaves the two successful reads above
            # standing as the entity's sample rather than withdrawing it.
            if breaker_verdict(error):
                result.breaker_sample = True
        else:
            if cached is not None:
                result.synapse_cached_valid = cached.get('isValid')

    before = validate_instance(instance, schema)
    result.before_valid = before.is_valid
    result.before_messages = before.messages

    drop, rename = plan_from_decisions(decisions)
    if not drop and not rename:
        result.after_valid = before.is_valid
        result.status = 'clean' if before.is_valid else 'still_invalid'
        return result

    after = validate_instance(
        apply_key_changes(instance, drop=drop, rename=rename, schema=schema), schema)
    result.after_valid = after.is_valid
    result.after_messages = after.messages
    result.status = classify_transition(before.is_valid, after.is_valid)
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(
    results: Sequence[EntityConformance],
    path: Path,
    *,
    not_checked: Sequence[str] = (),
) -> None:
    """The per-entity conformance table for one pass.

    ``not_checked`` names the entities a pass the circuit breaker cut short never
    reached, written out as ``not_checked`` rows so the artifact says what it does not
    cover. A CSV that simply ended early reads as a complete pass over a smaller plan,
    which is the reading an operator must not take before running ``--apply``. Mirrors
    the ``not_attempted`` rows ``fix_annotation_keys.write_report`` writes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ['entity_id', 'project_id', 'schema_name', 'bound_version', 'drift', 'status',
              'before_valid', 'after_valid', 'synapse_cached_valid', 'synapse_cached_error',
              'before_messages', 'after_messages', 'error']
    with open(path, 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in results:
            writer.writerow({
                'entity_id': item.entity_id,
                'project_id': item.project_id,
                'schema_name': item.schema_name,
                'bound_version': item.bound_version,
                'drift': item.drift,
                'status': item.status,
                'before_valid': item.before_valid,
                'after_valid': item.after_valid,
                'synapse_cached_valid': item.synapse_cached_valid,
                'synapse_cached_error': item.cached_error or '',
                'before_messages': ' | '.join(item.before_messages[:5]),
                'after_messages': ' | '.join(item.after_messages[:5]),
                'error': item.error or '',
            })
        for entity_id in not_checked:
            writer.writerow({
                'entity_id': entity_id,
                'status': 'not_checked',
                'error': 'pass aborted by the circuit breaker before this entity',
            })


def summarize(results: Sequence[EntityConformance]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def format_markdown(results: Sequence[EntityConformance], *, not_checked: int = 0) -> str:
    counts = summarize(results)
    lines = ['# Annotation schema conformance', '',
             f'Entities checked: **{len(results)}**', '']
    if not_checked:
        # A pass the circuit breaker cut short covers part of the plan, and the
        # document has to say so: read on its own it looks like a complete verdict
        # over a smaller set of entities.
        lines += [f'**This pass was cut short: {not_checked} entities were never checked**, '
                  'so this report does not vouch for the whole plan.', '']
    labels = {
        'clean': 'Valid before and after the planned fix',
        'repaired': 'Invalid now, valid after the fix',
        'still_invalid': 'Invalid before and after (pre-existing, unrelated to key casing)',
        'regression': 'Valid now, INVALID after the fix - BLOCKER',
        'unbound': 'No schema bound and no Component annotation',
        'no_schema': 'Bound to a schema this checkout does not have',
        'error': 'Could not be checked',
    }
    lines += ['| Outcome | Entities |', '|---|---|']
    for status, label in labels.items():
        if counts.get(status):
            lines.append(f'| {label} | {counts[status]} |')
    lines.append('')

    blockers = [r for r in results if r.blocking]
    if blockers:
        lines += ['## Blockers', '',
                  ('The planned fix would make these entities fail schema validation. '
                   'Do not apply it until these are resolved.'), '',
                  '| Entity | Schema | Error after fix |', '|---|---|---|']
        for item in blockers:
            detail = item.after_messages[0] if item.after_messages else ''
            lines.append(f'| [{item.entity_id}](https://www.synapse.org/Synapse:{item.entity_id}) '
                         f'| {item.schema_name} | {detail[:100]} |')
        lines.append('')
    elif not_checked:
        # The sentence below is the one an operator quotes when deciding to run
        # --apply, so on a truncated pass it must not be said: the entities never
        # checked could hold any number of regressions.
        lines += ['## Blockers', '',
                  (f'None among the {len(results)} entities checked - but {not_checked} were '
                   'never checked, so this pass does not vouch for the whole plan. '
                   'Re-run it to completion before applying the fix.'), '']
    else:
        lines += ['## Blockers', '', 'None. The planned fix does not break conformance anywhere.', '']

    drifted = [r for r in results if r.drift]
    if drifted:
        by_drift: dict[str, int] = {}
        for item in drifted:
            by_drift[item.drift] = by_drift.get(item.drift, 0) + 1
        lines += ['## Schema version drift', '',
                  ('Entities bound to a schema version other than this checkout. '
                   'Local verdicts describe the version in this checkout.'), '',
                  '| Drift | Entities |', '|---|---|']
        lines += [f'| {drift} | {count} |' for drift, count in sorted(by_drift.items())]
        lines.append('')

    stale = [r for r in results
             if r.synapse_cached_valid is not None and r.before_valid is not None
             and r.synapse_cached_valid != r.before_valid]
    if stale:
        lines += ['## Synapse cached verdict disagrees with a fresh check', '',
                  ("Synapse's stored validation result was computed against an older schema "
                   'version. The fresh check reflects the schema currently bound.'), '',
                  '| Entity | Synapse cached | Fresh check |', '|---|---|---|']
        for item in stale[:40]:
            lines.append(f'| {item.entity_id} | {item.synapse_cached_valid} | {item.before_valid} |')
        lines.append('')

    cached_lost = [r for r in results if r.cached_error]
    if cached_lost:
        # A blank cached verdict has two meanings and only one of them is benign, so
        # the comparison above has to say how many entities it left out.
        lines += [(f"_Synapse's cached verdict could not be read for {len(cached_lost)} "
                   'entities, so the comparison above does not cover them; the reason is '
                   'in the `synapse_cached_error` column._'), '']

    invalid = [r for r in results if r.status == 'still_invalid']
    if invalid:
        reasons: dict[str, int] = {}
        for item in invalid:
            for message in item.before_messages[:3]:
                reasons[message] = reasons.get(message, 0) + 1
        lines += ['## Pre-existing validation failures', '',
                  'Not caused by annotation key casing, and not fixed by this cleanup.', '',
                  '| Message | Entities |', '|---|---|']
        lines += [f'| `{msg[:110]}` | {n} |'
                  for msg, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:20]]
        lines.append('')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def repo_schema_version(default: str | None = None) -> str | None:
    """This checkout's schema version, from the latest git tag."""
    import subprocess
    try:
        tag = subprocess.run(['git', 'describe', '--tags', '--abbrev=0'],
                             capture_output=True, text=True, check=True,
                             cwd=Path(__file__).resolve().parent.parent).stdout.strip()
        return tag.lstrip('v') or default
    except Exception:  # noqa: BLE001
        return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Check Synapse annotations against the current NF JSON schemas.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--findings', default=None,
                        help='entity_findings.jsonl from audit_annotation_keys.py --drill-down')
    parser.add_argument('--entity', action='append', default=[], metavar='SYNID')
    parser.add_argument('--project', action='append', default=[], metavar='SYNID',
                        help='restrict --findings to these projects')
    parser.add_argument('--schema-dir', default=str(SCHEMA_DIR))
    parser.add_argument('--repo-version', default=None,
                        help='schema version of this checkout (default: latest git tag)')
    parser.add_argument('--check-plan', action='store_true',
                        help='also validate the entity with the planned fix applied')
    parser.add_argument('--include-cached', action='store_true',
                        help="also fetch Synapse's own stored verdict for comparison")
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--max-retries', type=int, default=5,
                        help='retries per entity read on a transient failure (never on a 403)')
    parser.add_argument('--report', default=None, help='CSV output path')
    parser.add_argument('--markdown', default=None, help='markdown output path')
    parser.add_argument('--log-level', default='INFO')
    return parser


def _login():
    import synapseclient

    syn = synapseclient.Synapse()
    syn.login(authToken=os.environ.get('SYNAPSE_AUTH_TOKEN'), silent=True)
    syn.silent = True
    return syn


def load_findings(path: Path, projects: Sequence[str]) -> list[dict]:
    wanted = set(projects or [])
    entries = []
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if wanted and entry.get('project_id') not in wanted:
                continue
            entries.append(entry)
    return entries


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format='%(levelname)s %(message)s')
    logging.getLogger('synapseclient').setLevel(logging.ERROR)

    registry = SchemaRegistry.load(args.schema_dir)
    repo_version = args.repo_version or repo_schema_version()
    LOG.info('validating against %d schemas from %s (repo version %s)',
             len(registry.by_name), args.schema_dir, repo_version or 'unknown')

    targets: list[dict] = [{'entity_id': e, 'decisions': [], 'project_id': ''} for e in args.entity]
    if args.findings:
        for entry in load_findings(Path(args.findings), args.project):
            component = entry.get('annotations', {}).get('Component') \
                or entry.get('annotations', {}).get('component')
            if isinstance(component, list):
                component = component[0] if component else None
            targets.append({
                'entity_id': entry['entity_id'],
                'project_id': entry.get('project_id', ''),
                'decisions': entry.get('decisions', []) if args.check_plan else [],
                'component': component,
            })
    if not targets:
        LOG.error('nothing to check: pass --findings and/or --entity')
        return 1
    if args.limit:
        targets = targets[:args.limit]

    syn = _login()

    def check(position: int, target: dict) -> EntityConformance:
        outcome = check_entity(
            syn, target['entity_id'], registry=registry, repo_version=repo_version,
            decisions=target.get('decisions') or (), project_id=target.get('project_id', ''),
            fallback_component=target.get('component'), include_cached=args.include_cached,
            max_retries=args.max_retries,
        )
        if position % 25 == 0:
            LOG.info('... %d/%d', position, len(targets))
        return outcome

    # Guarded by the same circuit breaker as every other per-entity network loop:
    # each read carries a retry budget, so a systemic 503 costs over a minute of
    # jittered backoff per entity, which over the 13,150-entity findings file is
    # days of grinding to reach a report that is nothing but errors. Only a read the
    # service may have failed is a breaker sample - an `unbound` or `no_schema`
    # verdict, and a 403 or 404 on one entity, are facts about the data, which is what
    # this pass exists to surface.
    results, aborted = run_guarded(targets, check,
                                   failed=lambda outcome: outcome.breaker_sample,
                                   label='conformance', logger=LOG)

    # run_guarded works through targets in order, so whatever it did not return is
    # what an abort left unchecked.
    not_checked_ids = [target['entity_id'] for target in targets[len(results):]]
    report = format_markdown(results, not_checked=len(not_checked_ids))
    if args.markdown:
        Path(args.markdown).write_text(report + '\n')
    else:
        print(report)
    if args.report:
        write_report(results, Path(args.report), not_checked=not_checked_ids)
        LOG.info('CSV written to %s', args.report)

    counts = summarize(results)
    LOG.info('conformance: %s', counts)
    if any(r.blocking for r in results):
        LOG.error('%d entities would REGRESS; do not apply the fix',
                  sum(1 for r in results if r.blocking))
        return 1
    if aborted:
        LOG.error('the conformance pass was cut short after %d of %d entities; %d were never '
                  'checked, so nothing here vouches for the whole plan - re-run it',
                  len(results), len(targets), len(not_checked_ids))
        return 1
    if counts.get('error') or counts.get('no_schema'):
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
