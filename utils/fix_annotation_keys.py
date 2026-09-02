#!/usr/bin/env python3
"""
Repair mis-cased annotation keys on NF-OSI Synapse entities (issue #939).

Requires: synapseclient, pyyaml. Feed it the ``entity_findings.jsonl`` produced
by ``utils/audit_annotation_keys.py --drill-down``, or name projects directly.

Safety model
------------
* Dry run is the default. ``--apply`` alone is not enough: ``--actions`` must
  name each destructive action, so a rename can never happen silently alongside
  a drop.
* Every original annotation dict is written to a backup JSONL and fsynced
  *before* the entity is mutated, so a kill mid-write cannot lose the record.
* Decisions are recomputed from a fresh read at write time, never from the
  scan. If a value changed in between, the verdict flips to a reported conflict
  instead of a silent delete.
* Keys the tool was not asked to touch are copied verbatim, which is what lets
  ``--verify`` prove nothing else changed.
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

LOG = logging.getLogger('fix_annotation_keys')

#: Statuses that mean an entity needs no further attention on a resumed run.
SETTLED_STATUSES = frozenset({'ok', 'noop'})

#: Abort if more than this fraction of the first ERROR_SAMPLE writes fail.
ERROR_RATE_THRESHOLD = 0.10
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

        # Carry each surviving key's declared type across, including for a
        # renamed key, so nothing is silently retyped.
        planned_types = dict(fresh.types)
        for decision in writing:
            if decision.action is Action.RENAME_STRAY and decision.canonical_key:
                planned_types[decision.canonical_key] = fresh.types.get(decision.stray_key, 'STRING')

        try:
            write_annotations(syn, AnnotationRecord(entity_id, fresh.etag, planned, planned_types))
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

def parse_actions(spec: str) -> set[Action]:
    """Turn ``drop_stray,rename_stray`` into policy actions.

    Only mutating actions may be requested; naming a report-only action is a
    usage error rather than a silent no-op.
    """
    requested = {part.strip() for part in spec.split(',') if part.strip()}
    if not requested:
        raise SystemExit('--actions must name at least one of: drop_stray, rename_stray')
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
    parser.add_argument('--actions', default='drop_stray',
                        help='comma-separated: drop_stray, rename_stray')
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
    errors = 0
    for position, entity_id in enumerate(entity_ids, 1):
        result = apply_entity(
            syn, entity_id, canon=canon, index=index, logs=logs,
            allowed_actions=allowed_actions, dry_run=dry_run,
            loose_compare=args.loose_compare, max_retries=args.max_retries,
        )
        results.append(result)
        if result.status in ('error', 'etag_conflict'):
            errors += 1
        # Circuit breaker: a systemic problem should stop after 50 writes, not
        # after 3,000.
        if position == ERROR_SAMPLE and errors / ERROR_SAMPLE > ERROR_RATE_THRESHOLD:
            LOG.error('aborting: %d of the first %d entities failed', errors, ERROR_SAMPLE)
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
