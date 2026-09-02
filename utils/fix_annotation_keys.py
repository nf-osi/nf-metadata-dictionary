#!/usr/bin/env python3
"""
Repair mis-cased annotation keys on NF-OSI Synapse entities (issue #939).

Requires: synapseclient, pyyaml. Feed it the ``entity_findings.jsonl`` produced
by ``utils/audit_annotation_keys.py --drill-down``, or name projects directly.

Safety model
------------
* Dry run is the default. ``--apply`` alone is not enough: ``--actions`` has no
  default and must name each destructive action, so nothing is dropped or
  renamed that was not asked for by name.
* Every original annotation dict is written to a backup JSONL and fsynced
  *before* the entity is mutated, so a kill mid-write cannot lose the record.
* Decisions are recomputed from a fresh read at write time, never from the
  scan. If a value changed in between, the verdict flips to a reported conflict
  instead of a silent delete.
* Values are never re-serialised - not for a key the tool was not asked to
  touch, and not for one it only moved - which is what lets ``--verify`` prove
  nothing else changed.
* ``--rollback`` restores from the backup, and refuses to revert an entity that
  someone else has edited since the fix ran.

Note that annotations are versioned: dropping a key from the current version
does not remove it from earlier versions. "Fixed" means "fixed on the current
version".

Examples
--------
    # dry run - the default; shows what would change and writes nothing
    python utils/fix_annotation_keys.py --findings audit/entity_findings.jsonl \
        --actions drop_stray --log-dir annotation-fix-logs/dryrun

    # apply the low-risk cleanup only
    python utils/fix_annotation_keys.py --findings audit/entity_findings.jsonl \
        --actions drop_stray --apply --verify --log-dir annotation-fix-logs/drop-1

    # recover metadata hidden behind PascalCase keys, as a separate pass
    python utils/fix_annotation_keys.py --findings audit/entity_findings.jsonl \
        --actions rename_stray --apply --verify --log-dir annotation-fix-logs/rename-1

    # undo a run
    python utils/fix_annotation_keys.py --rollback annotation-fix-logs/drop-1 --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from annotation_key_policy import (  # noqa: E402
    CANONICAL_SCHEMA,
    WRITING_ACTIONS,
    Action,
    KeyIndex,
    apply_decisions,
    decide_entity,
    load_canonical_slots,
)
from synapse_annotation_io import (  # noqa: E402
    AnnotationRecord,
    read_annotations,
    write_annotations,
)
from validate_annotations import (  # noqa: E402
    SchemaRegistry,
    check_entity,
    repo_schema_version,
)

LOG = logging.getLogger('fix_annotation_keys')

#: Statuses that mean an entity needs no further attention on a resumed run.
SETTLED_STATUSES = frozenset({'ok', 'noop'})

#: Abort once more than this fraction of the most recent writes have failed. The
#: rate is measured over a trailing window rather than the whole run, so a
#: healthy prefix cannot dilute the signal: a run that degrades at entity 2,000
#: stops there rather than waiting for the cumulative rate to catch up.
ERROR_RATE_THRESHOLD = 0.10
#: How many of the most recent writes the rate is measured over.
ERROR_SAMPLE = 50


# ---------------------------------------------------------------------------
# Run logs
# ---------------------------------------------------------------------------

class RunLogs:
    """Durable backup and progress logs for one remediation run.

    Both are append-only JSONL and fsynced per line: a run that is killed must
    leave behind enough to roll back and to resume.
    """

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)
        self.backup_path = self.directory / 'backup.jsonl'
        self.progress_path = self.directory / 'progress.jsonl'
        self.report_path = self.directory / 'report.csv'

    def _append(self, path: Path, payload: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with open(path, 'a') as handle:
            handle.write(json.dumps(payload) + '\n')
            handle.flush()
            os.fsync(handle.fileno())

    def write_backup(self, record: AnnotationRecord) -> None:
        """Record the exact pre-write state, in wire form so it can be restored.

        ``annotations`` is the /annotations2 payload including declared types, so
        a rollback reproduces the original bit for bit rather than re-inferring
        types. ``decoded`` is the same data in readable form, for humans reading
        the backup during an incident.
        """
        self._append(self.backup_path, {
            'entity_id': record.entity_id,
            'etag': record.etag,
            'annotations': record.typed,
            'decoded': record.values,
            'backed_up_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        })

    def record_progress(self, entity_id: str, status: str, payload: dict) -> None:
        self._append(self.progress_path, {
            'entity_id': entity_id,
            'status': status,
            'recorded_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            **payload,
        })

    def progress_entries(self) -> list[dict]:
        return read_jsonl(self.progress_path)

    def backup_entries(self) -> list[dict]:
        return read_jsonl(self.backup_path)

    def completed_entities(self) -> set[str]:
        """Entities that do not need revisiting.

        An etag conflict is deliberately NOT settled - it means a concurrent
        writer won the race and the entity should be retried.
        """
        return {
            entry['entity_id'] for entry in self.progress_entries()
            if entry.get('status') in SETTLED_STATUSES
        }


def read_jsonl(path: Path | str) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    entries = []
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


# ---------------------------------------------------------------------------
# Applying decisions to one entity
# ---------------------------------------------------------------------------

@dataclass
class ApplyResult:
    entity_id: str
    status: str  # ok | noop | would_write | etag_conflict | error
    planned: dict | None = None
    applied: list[dict] = field(default_factory=list)
    reported: list[dict] = field(default_factory=list)
    error: str | None = None


def _is_etag_conflict(error: Exception) -> bool:
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    if status in (409, 412):
        return True
    text = str(error).lower()
    return 'precondition' in text or 'etag' in text or 'conflict' in text


def apply_entity(
    syn,
    entity_id: str,
    *,
    canon,
    index: KeyIndex,
    logs: RunLogs,
    allowed_actions: Iterable[Action],
    dry_run: bool = True,
    loose_compare: bool = False,
    max_retries: int = 3,
) -> ApplyResult:
    """Read, decide, back up and (optionally) write one entity."""
    allowed = {a for a in allowed_actions if a in WRITING_ACTIONS}

    for attempt in range(max_retries + 1):
        try:
            fresh = read_annotations(syn, entity_id)
        except Exception as error:  # noqa: BLE001
            result = ApplyResult(entity_id, 'error', error=f'{type(error).__name__}: {error}'[:300])
            logs.record_progress(entity_id, result.status, {'error': result.error})
            return result

        current = dict(fresh.values)
        # Recompute from what is on the entity right now. A decision made during
        # the audit can be invalidated by a concurrent writer, and acting on the
        # stale verdict is how a cleanup destroys the surviving copy of a value.
        decisions = decide_entity(current, canon=canon, index=index, loose_compare=loose_compare)
        writing = [d for d in decisions if d.action in allowed]
        reported = [d.as_dict() for d in decisions
                    if d.action not in WRITING_ACTIONS and d.action is not Action.SKIP]

        if not writing:
            result = ApplyResult(entity_id, 'noop', planned=current, reported=reported)
            logs.record_progress(entity_id, result.status, {'reported': reported})
            return result

        planned = apply_decisions(current, writing)
        if planned == current:
            result = ApplyResult(entity_id, 'noop', planned=current, reported=reported)
            logs.record_progress(entity_id, result.status, {'reported': reported})
            return result

        applied = [d.as_dict() for d in writing]
        if dry_run:
            return ApplyResult(entity_id, 'would_write', planned=planned,
                               applied=applied, reported=reported)

        # Backup before mutating, and fsync, so kill -9 between here and the
        # write still leaves a recoverable record.
        logs.write_backup(fresh)

        # Carry each surviving key's declared type and original wire strings
        # across, including for a renamed key: a rename moves metadata, it does
        # not retype or re-serialise it.
        planned_types = dict(fresh.types)
        planned_raw = dict(fresh.raw)
        for decision in writing:
            if decision.action is Action.RENAME_STRAY and decision.canonical_key:
                planned_types[decision.canonical_key] = fresh.types.get(decision.stray_key, 'STRING')
                stray_raw = fresh.raw.get(decision.stray_key)
                if stray_raw is not None:
                    planned_raw[decision.canonical_key] = stray_raw

        try:
            # `planned_raw` carries the original wire strings, so every key the
            # plan did not rewrite - including one it only moved - is emitted
            # exactly as Synapse served it rather than re-serialised from its
            # decoded value.
            write_annotations(syn, AnnotationRecord(entity_id, fresh.etag, planned,
                                                   planned_types, planned_raw))
        except Exception as error:  # noqa: BLE001
            if _is_etag_conflict(error) and attempt < max_retries:
                LOG.info('%s: etag conflict, re-reading (attempt %d/%d)',
                         entity_id, attempt + 1, max_retries)
                time.sleep(0.5 * (attempt + 1))
                continue
            status = 'etag_conflict' if _is_etag_conflict(error) else 'error'
            result = ApplyResult(entity_id, status, planned=planned, applied=applied,
                                 reported=reported, error=f'{type(error).__name__}: {error}'[:300])
            logs.record_progress(entity_id, status, {'error': result.error, 'applied': applied})
            return result

        result = ApplyResult(entity_id, 'ok', planned=planned, applied=applied, reported=reported)
        logs.record_progress(entity_id, 'ok', {
            'applied': applied, 'reported': reported, 'result': planned,
        })
        return result

    result = ApplyResult(entity_id, 'etag_conflict', error='retries exhausted')
    logs.record_progress(entity_id, result.status, {'error': result.error})
    return result


# ---------------------------------------------------------------------------
# Schema conformance preflight
# ---------------------------------------------------------------------------

#: Conformance statuses that mean the entity was never actually validated, so
#: the preflight has no verdict for it. ``error`` and ``no_schema`` are what
#: ``validate_annotations.main`` exits 2 for; ``unbound`` belongs here for the
#: same reason - nothing was checked, so nothing was proven.
UNVALIDATABLE_STATUSES = frozenset({'error', 'no_schema', 'unbound'})


def component_of(values: dict[str, list] | None) -> str | None:
    """The template an entity's ``Component`` annotation names, if any.

    An entity with no schema binding can still record which template the curator
    intended, and that is the only thing left to validate it against.
    """
    raw = (values or {}).get('Component') or (values or {}).get('component')
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    text = str(raw).strip() if raw is not None else ''
    return text or None


@dataclass
class PreflightReport:
    checked: int = 0
    #: entities that would go from valid to invalid
    blockers: list = field(default_factory=list)
    #: entities the check could not reach a verdict on at all
    unvalidatable: list = field(default_factory=list)
    #: entities valid before and after the plan
    clean: list = field(default_factory=list)
    #: entities invalid now and valid once the plan is applied
    repaired: list = field(default_factory=list)
    #: entities invalid both before and after - a pre-existing failure this
    #: cleanup does not claim to fix, so not a blocker, but not proven either
    still_invalid: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers and not self.unvalidatable

    @property
    def proven(self) -> int:
        """Entities the check actually vouched for."""
        return len(self.clean) + len(self.repaired)


def schema_preflight(
    syn,
    plans: dict[str, list[dict]],
    *,
    registry: SchemaRegistry,
    repo_version: str | None = None,
    components: dict[str, str | None] | None = None,
) -> PreflightReport:
    """Whether the planned fix keeps every entity JSON-schema conformant.

    Key-casing repair is supposed to leave metadata *more* conformant, never
    less. This validates each entity against the schema bound to it - using this
    checkout's ``registered-json-schemas/``, i.e. the current version of the
    model - both as it stands and with the plan applied.

    Two outcomes must stop the run, and they are reported separately because the
    remedy differs. A blocker is a proven regression: discovering it after the
    write means hand-repairing entities from the backup. An unvalidatable entity
    is worse in one respect - the gate has no verdict at all, so treating it as
    a pass would make "every entity proven safe" indistinguishable from "nothing
    could be checked".

    ``components`` supplies each entity's ``Component`` annotation, so an entity
    with no binding is still checked against the template its curator named
    rather than counted as unvalidatable for want of a lookup.
    """
    components = components or {}
    report = PreflightReport()
    for entity_id, decisions in plans.items():
        outcome = check_entity(
            syn, entity_id, registry=registry, repo_version=repo_version, decisions=decisions,
            fallback_component=components.get(entity_id),
        )
        report.checked += 1
        if outcome.blocking:
            report.blockers.append(outcome)
        elif outcome.status in UNVALIDATABLE_STATUSES:
            report.unvalidatable.append(outcome)
        elif outcome.status == 'still_invalid':
            report.still_invalid.append(outcome)
        elif outcome.status == 'repaired':
            report.repaired.append(outcome)
        else:
            report.clean.append(outcome)
    return report


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass
class VerifyReport:
    checked: int = 0
    failures: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def verify_run(syn, logs: RunLogs) -> VerifyReport:
    """Re-read every mutated entity and prove only the intended keys changed.

    The strong assertion is the last one: every key the run did not name must
    still hold exactly the value recorded in the backup. That is what catches an
    accidental clobber, which no amount of "the stray key is gone" checking will.
    """
    report = VerifyReport()
    backups = {}
    for entry in logs.backup_entries():
        backups.setdefault(entry['entity_id'], entry.get('decoded') or {})

    for entry in logs.progress_entries():
        if entry.get('status') != 'ok' or 'result' not in entry:
            continue
        entity_id = entry['entity_id']
        expected = entry['result']
        try:
            current = dict(read_annotations(syn, entity_id).values)
        except Exception as error:  # noqa: BLE001
            report.failures.append({'entity_id': entity_id, 'detail': f'read failed: {error}'})
            continue

        report.checked += 1
        missing = sorted(set(expected) - set(current))
        extra = sorted(set(current) - set(expected))
        changed = sorted(k for k in set(expected) & set(current) if current[k] != expected[k])
        if missing or extra or changed:
            report.failures.append({
                'entity_id': entity_id,
                'detail': f'missing={missing} unexpected={extra} changed={changed}',
            })
            continue

        # Key-set algebra against the pre-run state.
        backup = backups.get(entity_id)
        if backup is None:
            continue
        dropped = {d['stray_key'] for d in entry.get('applied', [])
                   if d['action'] == Action.DROP_STRAY.value}
        renamed = {d['stray_key']: d['canonical_key'] for d in entry.get('applied', [])
                   if d['action'] == Action.RENAME_STRAY.value}
        expected_keys = (set(backup) - dropped - set(renamed)) | set(renamed.values())
        if expected_keys != set(current):
            report.failures.append({
                'entity_id': entity_id,
                'detail': f'key algebra mismatch: expected {sorted(expected_keys)}, '
                          f'found {sorted(current)}',
            })
    return report


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RollbackStep:
    entity_id: str
    #: the /annotations2 wire payload to restore, types included
    annotations: dict
    #: the same data decoded, for comparing against the current state
    decoded: dict = field(default_factory=dict)


@dataclass
class RollbackReport:
    restored: int = 0
    would_restore: int = 0
    skipped: int = 0
    failures: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def plan_rollback(backup_entries: Sequence[dict]) -> list[RollbackStep]:
    """One step per entity, restoring the earliest recorded state.

    An entity touched twice in one run has two backup lines; only the first is
    the true pre-run state. Steps come back reverse-chronologically so a partial
    rollback unwinds in the opposite order to the fix.
    """
    earliest: dict[str, dict] = {}
    order: list[str] = []
    for entry in backup_entries:
        entity_id = entry['entity_id']
        if entity_id not in earliest:
            earliest[entity_id] = entry
            order.append(entity_id)
    return [
        RollbackStep(
            entity_id,
            earliest[entity_id]['annotations'],
            earliest[entity_id].get('decoded') or {},
        )
        for entity_id in reversed(order)
    ]


def rollback(
    syn,
    logs: RunLogs,
    *,
    dry_run: bool = True,
    force: bool = False,
    sleep: float = 0.0,
) -> RollbackReport:
    """Restore the annotations recorded in this run's backup.

    Two things make this subtler than it looks:

    * The backed-up etag is the *pre-write* etag and is stale as soon as the fix
      wrote, so the restore has to read the current etag first.
    * That means the restore has no optimistic concurrency and it replaces the
      whole dict, so an entity edited by someone else since the fix would have
      that edit silently reverted. Such entities are skipped unless ``force``.
    """
    report = RollbackReport()
    steps = plan_rollback(logs.backup_entries())
    written_by_run = {
        entry['entity_id']: entry['result']
        for entry in logs.progress_entries()
        if entry.get('status') == 'ok' and 'result' in entry
    }

    for step in steps:
        try:
            live = read_annotations(syn, step.entity_id)
        except Exception as error:  # noqa: BLE001
            report.failures.append({'entity_id': step.entity_id, 'detail': str(error)[:200]})
            continue

        current = dict(live.values)
        if current == step.decoded:
            continue  # already at the pre-run state

        expected = written_by_run.get(step.entity_id)
        if expected is not None and current != expected and not force:
            LOG.warning('%s: changed since the fix ran; skipping (use --force-rollback)',
                        step.entity_id)
            report.skipped += 1
            continue

        if dry_run:
            report.would_restore += 1
            continue

        try:
            # The backed-up etag is the pre-write etag and is stale; the restore
            # has to use the etag Synapse holds right now.
            body = json.dumps({
                'id': step.entity_id,
                'etag': live.etag,
                'annotations': step.annotations,
            })
            syn.restPUT(f'/entity/{step.entity_id}/annotations2', body=body)
        except Exception as error:  # noqa: BLE001
            report.failures.append({'entity_id': step.entity_id, 'detail': str(error)[:200]})
            continue
        report.restored += 1
        if sleep:
            time.sleep(sleep)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_actions(spec: str | None) -> set[Action]:
    """Turn ``drop_stray,rename_stray`` into policy actions.

    There is no default: nothing destructive happens unless the action is named,
    so an omitted ``--actions`` is a usage error rather than an implicit drop
    pass. Only mutating actions may be requested; naming a report-only action is
    likewise a usage error rather than a silent no-op.
    """
    requested = {part.strip() for part in (spec or '').split(',') if part.strip()}
    if not requested:
        raise SystemExit(
            '--actions is required and must name at least one of: drop_stray, rename_stray'
        )
    allowed = {a.value: a for a in WRITING_ACTIONS}
    unknown = requested - set(allowed)
    if unknown:
        raise SystemExit(
            f"--actions only accepts {', '.join(sorted(allowed))}; got {', '.join(sorted(unknown))}"
        )
    return {allowed[name] for name in requested}


def entity_ids_from_findings(path: Path, projects: Sequence[str] | None = None) -> list[str]:
    wanted = set(projects or [])
    ids: list[str] = []
    seen: set[str] = set()
    for entry in read_jsonl(path):
        if wanted and entry.get('project_id') not in wanted:
            continue
        entity_id = entry['entity_id']
        if entity_id not in seen:
            seen.add(entity_id)
            ids.append(entity_id)
    return ids


def check_write_permission(syn, entity_id: str) -> bool:
    """Fail fast rather than discovering a 403 after thousands of writes."""
    try:
        permissions = syn.restGET(f'/entity/{entity_id}/permissions')
    except Exception as error:  # noqa: BLE001
        LOG.warning('could not read permissions for %s: %s', entity_id, error)
        return False
    return bool(permissions.get('canEdit') or permissions.get('canCertifiedUserEdit'))


def write_report(results: Sequence[ApplyResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ['entity_id', 'status', 'action', 'stray_key', 'canonical_key', 'reason',
              'stray_value', 'canonical_value']
    with open(path, 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            rows = result.applied + result.reported
            if not rows:
                writer.writerow({'entity_id': result.entity_id, 'status': result.status})
                continue
            for row in rows:
                writer.writerow({
                    'entity_id': result.entity_id,
                    'status': result.status,
                    'action': row.get('action'),
                    'stray_key': row.get('stray_key'),
                    'canonical_key': row.get('canonical_key'),
                    'reason': row.get('reason'),
                    'stray_value': json.dumps(row.get('stray_value')),
                    'canonical_value': json.dumps(row.get('canonical_value')),
                })


def summarize(results: Sequence[ApplyResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Repair mis-cased annotation keys on NF-OSI Synapse entities.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--schema', default=str(CANONICAL_SCHEMA))
    parser.add_argument('--findings', default=None,
                        help='entity_findings.jsonl from audit_annotation_keys.py --drill-down')
    parser.add_argument('--project', action='append', default=[], metavar='SYNID',
                        help='restrict to this project (repeatable)')
    parser.add_argument('--entity', action='append', default=[], metavar='SYNID',
                        help='fix this entity directly (repeatable)')
    parser.add_argument('--actions', default=None,
                        help='required for a fix run; comma-separated: drop_stray, rename_stray')
    parser.add_argument('--apply', action='store_true',
                        help='actually write; omitted means dry run')
    parser.add_argument('--log-dir', default=None,
                        help='backup/progress/report directory (default annotation-fix-logs/<ts>)')
    parser.add_argument('--resume', action='store_true', help='skip entities already settled')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--max-entities-per-run', type=int, default=5000)
    parser.add_argument('--batch-size', type=int, default=50)
    parser.add_argument('--sleep', type=float, default=0.4, help='seconds between writes')
    parser.add_argument('--batch-pause', type=float, default=2.0)
    parser.add_argument('--max-retries', type=int, default=3)
    parser.add_argument('--loose-compare', action='store_true',
                        help='treat values equal across types as duplicates')
    parser.add_argument('--validate-schema', action='store_true',
                        help='before writing, confirm the plan does not break JSON schema '
                             'validation against this checkout of registered-json-schemas/')
    parser.add_argument('--allow-unvalidatable', action='store_true',
                        help='proceed even when --validate-schema could not reach a verdict on '
                             'some entities (unreadable, bound to a schema this checkout does '
                             'not have, or with neither a binding nor a Component annotation)')
    parser.add_argument('--verify', action='store_true', help='verify after applying')
    parser.add_argument('--verify-only', action='store_true', help='verify a previous run and exit')
    parser.add_argument('--rollback', default=None, metavar='LOGDIR',
                        help='restore annotations from a previous run')
    parser.add_argument('--force-rollback', action='store_true',
                        help='roll back even entities edited since the fix ran')
    parser.add_argument('--yes', action='store_true', help='skip the confirmation prompt')
    parser.add_argument('--log-level', default='INFO')
    return parser


def _login():
    # Imported lazily so the decision and rollback logic stays importable - and
    # therefore testable in CI - without synapseclient installed.
    import synapseclient

    syn = synapseclient.Synapse()
    syn.login(authToken=os.environ.get('SYNAPSE_AUTH_TOKEN'), silent=True)
    syn.silent = True
    return syn


def main(argv: Sequence[str] | None = None) -> int:  # noqa: C901 - CLI dispatch
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format='%(levelname)s %(message)s')
    logging.getLogger('synapseclient').setLevel(logging.ERROR)

    if args.rollback:
        logs = RunLogs(args.rollback)
        if not logs.backup_path.exists():
            LOG.error('no backup.jsonl in %s', args.rollback)
            return 1
        syn = _login()
        report = rollback(syn, logs, dry_run=not args.apply, force=args.force_rollback,
                          sleep=args.sleep if args.apply else 0.0)
        LOG.info('rollback: restored=%d would_restore=%d skipped=%d failures=%d',
                 report.restored, report.would_restore, report.skipped, len(report.failures))
        for failure in report.failures:
            LOG.error('rollback failed for %s: %s', failure['entity_id'], failure['detail'])
        return 0 if report.ok else 1

    log_dir = Path(args.log_dir) if args.log_dir else \
        Path('annotation-fix-logs') / time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    logs = RunLogs(log_dir)

    if args.verify_only:
        syn = _login()
        report = verify_run(syn, logs)
        LOG.info('verify: checked=%d failures=%d', report.checked, len(report.failures))
        for failure in report.failures:
            LOG.error('%s: %s', failure['entity_id'], failure['detail'])
        return 0 if report.ok else 1

    allowed_actions = parse_actions(args.actions)
    canon = load_canonical_slots(args.schema)
    index = KeyIndex.build(canon)

    entity_ids = list(args.entity)
    if args.findings:
        entity_ids.extend(entity_ids_from_findings(Path(args.findings), args.project))
    if not entity_ids:
        LOG.error('nothing to do: pass --findings and/or --entity')
        return 1

    # De-duplicate while preserving order.
    seen: set[str] = set()
    entity_ids = [e for e in entity_ids if not (e in seen or seen.add(e))]

    if args.resume:
        settled = logs.completed_entities()
        before = len(entity_ids)
        entity_ids = [e for e in entity_ids if e not in settled]
        LOG.info('resuming: %d of %d entities already settled', before - len(entity_ids), before)
    if args.limit:
        entity_ids = entity_ids[:args.limit]
    if len(entity_ids) > args.max_entities_per_run:
        LOG.error('%d entities exceeds --max-entities-per-run=%d; narrow the scope or raise it',
                  len(entity_ids), args.max_entities_per_run)
        return 1

    dry_run = not args.apply
    mode = 'DRY RUN' if dry_run else 'APPLY'
    LOG.info('%s: %d entities, actions=%s, logs=%s', mode, len(entity_ids),
             ','.join(sorted(a.value for a in allowed_actions)), log_dir)

    if args.validate_schema:
        # Build the plan without writing, then prove it does not reduce schema
        # conformance anywhere. This runs before the confirmation prompt so a
        # blocked plan is never offered for approval.
        syn = _login_cached()
        registry = SchemaRegistry.load()
        repo_version = repo_schema_version()
        LOG.info('schema preflight: %d entities against %d schemas (repo version %s)',
                 len(entity_ids), len(registry.by_name), repo_version or 'unknown')
        plans: dict[str, list[dict]] = {}
        components: dict[str, str | None] = {}
        for entity_id in entity_ids:
            planned = apply_entity(
                syn, entity_id, canon=canon, index=index, logs=logs,
                allowed_actions=allowed_actions, dry_run=True,
                loose_compare=args.loose_compare, max_retries=args.max_retries,
            )
            if planned.applied:
                plans[entity_id] = planned.applied
                components[entity_id] = component_of(planned.planned)
        preflight = schema_preflight(syn, plans, registry=registry, repo_version=repo_version,
                                     components=components)
        if preflight.blockers:
            LOG.error('%d entities would fail schema validation after the fix; refusing to proceed',
                      len(preflight.blockers))
            for blocker in preflight.blockers[:20]:
                detail = blocker.after_messages[0] if blocker.after_messages else ''
                LOG.error('  %s (%s): %s', blocker.entity_id, blocker.schema_name, detail[:160])
            return 1
        if preflight.unvalidatable and not args.allow_unvalidatable:
            LOG.error('%d of %d entities in the plan could not be validated at all, so the '
                      'preflight cannot vouch for them; refusing to proceed '
                      '(--allow-unvalidatable to accept the gap, or drop --validate-schema)',
                      len(preflight.unvalidatable), preflight.checked)
            for skipped in preflight.unvalidatable[:20]:
                LOG.error('  %s: %s (%s)', skipped.entity_id, skipped.status, skipped.error or '')
            return 1
        if preflight.unvalidatable:
            LOG.warning('%d entities could not be validated; proceeding on --allow-unvalidatable',
                        len(preflight.unvalidatable))
        if preflight.still_invalid:
            LOG.warning('%d entities fail validation both before and after the plan; those '
                        'failures are pre-existing and unrelated to key casing, so the preflight '
                        'does not vouch for them', len(preflight.still_invalid))
            for unchanged in preflight.still_invalid[:20]:
                detail = unchanged.after_messages[0] if unchanged.after_messages else ''
                LOG.warning('  %s (%s): %s', unchanged.entity_id, unchanged.schema_name,
                            detail[:160])
        LOG.info('schema preflight passed: %d of %d planned changes proven to leave the entity '
                 'conformant (%d already clean, %d repaired, %d unchanged and still invalid, '
                 '%d unvalidatable)', preflight.proven, len(plans), len(preflight.clean),
                 len(preflight.repaired), len(preflight.still_invalid),
                 len(preflight.unvalidatable))

    if not dry_run:
        if logs.backup_path.exists() and not args.resume:
            LOG.error('%s already contains a backup; use --resume or a fresh --log-dir',
                      logs.backup_path)
            return 1
        if entity_ids and not check_write_permission(_login_cached(), entity_ids[0]):
            LOG.error('no write access to %s; aborting before any changes', entity_ids[0])
            return 1
        if not args.yes:
            answer = input(f'Apply {sorted(a.value for a in allowed_actions)} to '
                           f'{len(entity_ids)} entities? [y/N] ')
            if answer.strip().lower() not in ('y', 'yes'):
                LOG.info('aborted')
                return 0

    syn = _login_cached()
    results: list[ApplyResult] = []
    recent_failures: deque[bool] = deque(maxlen=ERROR_SAMPLE)
    for position, entity_id in enumerate(entity_ids, 1):
        result = apply_entity(
            syn, entity_id, canon=canon, index=index, logs=logs,
            allowed_actions=allowed_actions, dry_run=dry_run,
            loose_compare=args.loose_compare, max_retries=args.max_retries,
        )
        results.append(result)
        recent_failures.append(result.status in ('error', 'etag_conflict'))
        # Circuit breaker: a systemic problem - a revoked token, a service
        # degradation, an ACL changed mid-run - should stop the run when it
        # starts, whether that is at entity 50 or at entity 2,000. Hence the
        # trailing window: the whole-run rate would take hundreds more failures
        # to clear the threshold once a long healthy prefix has diluted it.
        failures = sum(recent_failures)
        if (len(recent_failures) == ERROR_SAMPLE
                and failures / ERROR_SAMPLE > ERROR_RATE_THRESHOLD):
            LOG.error('aborting at entity %d: %d of the last %d failed',
                      position, failures, ERROR_SAMPLE)
            break
        if not dry_run:
            time.sleep(args.sleep)
            if position % args.batch_size == 0:
                LOG.info('... %d/%d', position, len(entity_ids))
                time.sleep(args.batch_pause)

    write_report(results, logs.report_path)
    counts = summarize(results)
    LOG.info('%s complete: %s', mode, counts)
    LOG.info('report written to %s', logs.report_path)

    exit_code = 0
    if counts.get('error') or counts.get('etag_conflict'):
        exit_code = 1
    elif any(r.reported for r in results):
        exit_code = 2  # conflicts that need a human

    if args.verify and not dry_run:
        report = verify_run(syn, logs)
        LOG.info('verify: checked=%d failures=%d', report.checked, len(report.failures))
        for failure in report.failures:
            LOG.error('%s: %s', failure['entity_id'], failure['detail'])
        if not report.ok:
            exit_code = 1
    return exit_code


_SYN = None


def _login_cached():
    global _SYN
    if _SYN is None:
        _SYN = _login()
    return _SYN


if __name__ == '__main__':
    sys.exit(main())
