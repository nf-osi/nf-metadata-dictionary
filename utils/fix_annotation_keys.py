#!/usr/bin/env python3
"""
Repair mis-cased annotation keys on NF-OSI Synapse entities (issue #939).

Requires: synapseclient, pyyaml. Feed it the ``entity_findings.jsonl`` produced
by ``utils/audit_annotation_keys.py --drill-down``, or name projects directly. The
findings file is the only input, so its sidecar manifest is read too: a file left
by a drill-down the circuit breaker cut short covers a subset of the audit, and
repairing part of the work while believing it was all of it is exactly the mistake
that has to be impossible. ``--apply`` refuses such a file unless
``--allow-incomplete-findings`` accepts the gap; a dry run proceeds and reports it.

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
from collections import Counter
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
from audit_annotation_keys import read_findings_manifest  # noqa: E402
from synapse_annotation_io import (  # noqa: E402
    AnnotationRecord,
    read_annotations,
    run_guarded,
    write_annotations,
)
from validate_annotations import (  # noqa: E402
    EntityConformance,
    SchemaRegistry,
    check_entity,
    repo_schema_version,
)

LOG = logging.getLogger('fix_annotation_keys')

#: Statuses that mean an entity needs no further attention on a resumed run.
SETTLED_STATUSES = frozenset({'ok', 'noop'})

# ``run_guarded`` and its circuit breaker live in synapse_annotation_io alongside
# the retry policy, so the audit's drill-down and every loop here are guarded by
# one implementation rather than by copies that drift apart. Every per-entity loop
# in this module - the preflight's planning pass, its conformance pass, the write
# pass, and the rollback and verify passes - goes through it, so none can be left
# unguarded by accident.


def _is_failure(result: ApplyResult) -> bool:
    return result.status in ('error', 'etag_conflict')


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

    def record_run_note(self, status: str, detail: str) -> None:
        """A fact about the run rather than about one entity.

        Goes in the progress log so it outlives the terminal scrollback: the log is
        what a curator reads back when working out what a run covered, and a
        coverage gap that only ever appeared as a log line was invisible there.
        Carries no entity id, so it can never be read back as a settled entity.
        """
        self._append(self.progress_path, {
            'entity_id': '',
            'status': status,
            'detail': detail,
            'recorded_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
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
            # The read gets the same retry budget as the write. A rate limit or a
            # 503 on a read is not a verdict about the entity, and the preflight
            # refuses the whole run on an entity it could not read, so one blip
            # would otherwise abort a plan of thousands. A 403 still fails fast.
            fresh = read_annotations(syn, entity_id, max_retries=max_retries)
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
    #: every entity the write pass would touch, in the order it was offered
    considered: list[str] = field(default_factory=list)
    #: entities with no planned change, so the write pass has nothing to break
    unchanged: list[str] = field(default_factory=list)
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
    #: set when the conformance pass was cut short by the circuit breaker, so the
    #: buckets describe only the entities it got through
    aborted: bool = False

    @property
    def outcomes(self) -> list:
        """Every entity a conformance verdict was attempted for."""
        return [*self.clean, *self.repaired, *self.still_invalid,
                *self.blockers, *self.unvalidatable]

    @property
    def checked(self) -> int:
        return len(self.outcomes)

    @property
    def proven(self) -> int:
        """Entities the check actually vouched for."""
        return len(self.clean) + len(self.repaired)

    @property
    def without_verdict(self) -> list[str]:
        """Entities the preflight reached no conformance verdict on.

        Both the ones it reached and could not validate and the ones it never got
        to, because the write pass would touch either with nothing behind it.
        Reporting only ``unvalidatable`` understates an abort badly: a 5,000-entity
        run cut short at the floor would claim 6 rather than 4,990, which is the
        opposite of the impression an operator needs during an outage.
        """
        settled = set(self.unchanged) | {
            o.entity_id for o in
            (*self.clean, *self.repaired, *self.still_invalid, *self.blockers)
        }
        return [e for e in self.considered if e not in settled]

    @property
    def unaccounted(self) -> list[str]:
        """Entities that landed in no bucket, or in more than one.

        The gate is only worth anything if every entity the write pass will touch
        sits in exactly one bucket, so that is reconciled rather than assumed. An
        entity missing from every bucket is the dangerous direction: it would be
        mutated with no conformance verdict behind it while the success line,
        counting only what it can see, still reads as a clean pass.
        """
        bucketed = Counter([*self.unchanged, *(o.entity_id for o in self.outcomes)])
        offered = set(self.considered)
        return sorted({e for e in offered if bucketed[e] != 1}
                      | {e for e in bucketed if e not in offered})

    @property
    def ok(self) -> bool:
        return (not self.aborted and not self.blockers
                and not self.unvalidatable and not self.unaccounted)


def schema_preflight(
    syn,
    dry_runs: Sequence[ApplyResult],
    *,
    registry: SchemaRegistry,
    repo_version: str | None = None,
    max_retries: int = 3,
) -> PreflightReport:
    """Whether the planned fix keeps every entity JSON-schema conformant.

    Key-casing repair is supposed to leave metadata *more* conformant, never
    less. This validates each entity against the schema bound to it - using this
    checkout's ``registered-json-schemas/``, i.e. the current version of the
    model - both as it stands and with the plan applied.

    It takes the dry-run results for *every* entity the run would touch, not a
    pre-filtered plan, so the caller cannot narrow what the gate sees. Anything
    that produced no plan is bucketed here: a genuine no-op is harmless, while a
    dry run that failed before it could build a plan is unvalidatable, because
    the write pass will read that entity again and act on whatever it finds.

    Three outcomes stop a write run, and they are reported separately because the
    remedy differs. A blocker is a proven regression: discovering it after the
    write means hand-repairing entities from the backup. An unvalidatable entity
    is worse in one respect - the gate has no verdict at all, so treating it as
    a pass would make "every entity proven safe" indistinguishable from "nothing
    could be checked"; a dry run reports those and carries on, since nothing will
    be mutated and the report is what a curator triages them from. An unaccounted
    entity means the bucketing itself is broken, and no count the report prints
    can be trusted.

    An entity with no binding is checked against the template its ``Component``
    annotation names rather than written off for want of a lookup.

    This is a per-entity network loop of its own - two reads per planned entity,
    each with the retry budget - so it is guarded by the same circuit breaker as
    the planning and write passes. A degradation that starts after the planning
    pass finishes stops here rather than burning the whole backoff budget on every
    remaining entity to reach the same refusal days later.
    """
    report = PreflightReport(considered=[r.entity_id for r in dry_runs])

    def check(_position: int, result: ApplyResult) -> EntityConformance | None:
        """Bucket one entity, returning its outcome only if a read was issued.

        Both no-plan cases are bucketed without touching the network - an
        unchanged entity as ``unchanged``, one whose planning read already failed
        as ``unvalidatable`` - so both come back as None and the breaker does not
        sample them. The failed planning read was sampled by the planning pass; a
        second sample here would count one outage twice.
        """
        if not result.applied:
            if result.status == 'noop':
                report.unchanged.append(result.entity_id)
            else:
                report.unvalidatable.append(EntityConformance(
                    entity_id=result.entity_id,
                    status='error',
                    error=result.error or f'dry run returned {result.status} with no plan',
                ))
            return None
        outcome = check_entity(
            syn, result.entity_id, registry=registry, repo_version=repo_version,
            decisions=result.applied, fallback_component=component_of(result.planned),
            max_retries=max_retries,
        )
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
        return outcome

    # Only 'error' counts against the breaker: a bound schema this checkout does
    # not have, or an entity with no binding at all, is a verdict about the data
    # rather than a sign that the service is failing. An entity this loop issued no
    # request for - an unchanged one, or one whose plan already failed in the
    # planning pass, which sampled it there - is not sampled at all, so a run that
    # is mostly no-ops cannot dilute the window away from the reads it is guarding.
    _, report.aborted = run_guarded(
        dry_runs, check, failed=_conformance_request_failed,
        label='schema preflight conformance',
    )
    return report


def _conformance_request_failed(outcome: EntityConformance | None) -> bool | None:
    """Whether a conformance read failed, or None when no read was issued."""
    return None if outcome is None else outcome.status == 'error'


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass
class VerifyReport:
    checked: int = 0
    failures: list[dict] = field(default_factory=list)
    #: How many entities the pass reached, of how many it was given, and whether the
    #: circuit breaker cut it short - so an aborted pass cannot read as a finished
    #: one. See :func:`log_pass_summary`.
    attempted: int = 0
    considered: int = 0
    aborted: bool = False

    @property
    def ok(self) -> bool:
        return not self.failures and not self.aborted


def verify_run(syn, logs: RunLogs, *, max_retries: int = 3) -> VerifyReport:
    """Re-read every mutated entity and prove only the intended keys changed.

    The strong assertion is the last one: every key the run did not name must
    still hold exactly the value recorded in the backup. That is what catches an
    accidental clobber, which no amount of "the stray key is gone" checking will.
    """
    report = VerifyReport()
    backups = {}
    for entry in logs.backup_entries():
        backups.setdefault(entry['entity_id'], entry.get('decoded') or {})

    written = [entry for entry in logs.progress_entries()
               if entry.get('status') == 'ok' and 'result' in entry]

    def check(_position: int, entry: dict) -> bool:
        """Verify one entity, reporting whether the *read* failed.

        Only a failed read is a breaker sample: a mismatch is a verdict about the
        data - exactly what this pass exists to surface - and must not abort the
        walk over the rest of the run.
        """
        entity_id = entry['entity_id']
        expected = entry['result']
        try:
            current = dict(read_annotations(syn, entity_id, max_retries=max_retries).values)
        except Exception as error:  # noqa: BLE001
            report.failures.append({'entity_id': entity_id, 'detail': f'read failed: {error}'})
            return True

        report.checked += 1
        missing = sorted(set(expected) - set(current))
        extra = sorted(set(current) - set(expected))
        changed = sorted(k for k in set(expected) & set(current) if current[k] != expected[k])
        if missing or extra or changed:
            report.failures.append({
                'entity_id': entity_id,
                'detail': f'missing={missing} unexpected={extra} changed={changed}',
            })
            return False

        # Key-set algebra against the pre-run state.
        backup = backups.get(entity_id)
        if backup is None:
            return False
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
        return False

    attempted, report.aborted = run_guarded(written, check, failed=bool, label='verify')
    report.attempted = len(attempted)
    report.considered = len(written)
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
    #: As on :class:`VerifyReport`: an aborted rollback must say how many entities
    #: it never reached, because those are still in the fixed state. This is the
    #: recovery path from a bad write, so "restored=0" alone is the wrong impression.
    attempted: int = 0
    considered: int = 0
    aborted: bool = False

    @property
    def ok(self) -> bool:
        return not self.failures and not self.aborted


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
    max_retries: int = 3,
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

    def restore(_position: int, step: RollbackStep) -> bool:
        """Restore one entity, reporting whether a request to Synapse failed.

        Guarded like every other per-entity loop here: a rollback driven into a
        systemic outage should stop and say so rather than spend the retry budget
        on thousands of entities. Stopping early is safe because the backup is
        still on disk and a re-run skips whatever is already back at its pre-run
        state.
        """
        try:
            live = read_annotations(syn, step.entity_id, max_retries=max_retries)
        except Exception as error:  # noqa: BLE001
            report.failures.append({'entity_id': step.entity_id, 'detail': str(error)[:200]})
            return True

        current = dict(live.values)
        if current == step.decoded:
            return False  # already at the pre-run state

        expected = written_by_run.get(step.entity_id)
        if expected is not None and current != expected and not force:
            LOG.warning('%s: changed since the fix ran; skipping (use --force-rollback)',
                        step.entity_id)
            report.skipped += 1
            return False

        if dry_run:
            report.would_restore += 1
            return False

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
            return True
        report.restored += 1
        if sleep:
            time.sleep(sleep)
        return False

    attempted, report.aborted = run_guarded(steps, restore, failed=bool, label='rollback')
    report.attempted = len(attempted)
    report.considered = len(steps)
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


def findings_gap(path: Path) -> str:
    """How a findings file falls short of a completed drill-down, if it does.

    The findings file is this tool's only input, so a file produced by a drill-down
    the circuit breaker cut short would otherwise plan a subset of the work while
    looking exactly like a complete plan. The audit writes a manifest beside the
    file; when it says the pass did not finish, this is the sentence that says so -
    returned rather than only logged, so the gate can refuse a write run with it and
    the report and the progress log can record it.
    """
    manifest = read_findings_manifest(path)
    if manifest is None or manifest.get('complete', True):
        return ''
    missed = manifest.get('projects_not_inspected') or []
    partial = manifest.get('projects_partially_inspected') or []
    return (f'{path} comes from a drill-down that did not complete: '
            f'{len(manifest.get("projects_inspected") or [])} projects inspected, '
            f'{len(missed)} never inspected ({", ".join(missed) or "none"}), '
            f'{len(partial)} cut short part-way ({", ".join(partial) or "none"})')


def entity_ids_from_findings(path: Path, projects: Sequence[str] | None = None) -> list[str]:
    """The entities to work on, as named by a drill-down's findings file."""
    gap = findings_gap(path)
    if gap:
        LOG.error('%s. Re-run the audit drill-down for a complete plan.', gap)
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


def write_report(
    results: Sequence[ApplyResult],
    path: Path,
    *,
    not_attempted: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> None:
    """The per-entity outcome table for one pass.

    ``not_attempted`` names the entities a pass cut short by the circuit breaker
    never reached, written out as ``not_attempted`` rows. A report that simply
    ended early reads as a complete run over a smaller plan, which is the opposite
    of what an operator needs to know during an outage.

    ``notes`` are facts about the run rather than about an entity - a findings file
    that covered only part of the audit, say - written as ``run_note`` rows so the
    artifact carries them too and not only the terminal.
    """
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
        for entity_id in not_attempted:
            writer.writerow({'entity_id': entity_id, 'status': 'not_attempted',
                             'reason': 'run aborted by the circuit breaker before this entity'})
        for note in notes:
            writer.writerow({'entity_id': '', 'status': 'run_note', 'reason': note})


def log_pass_summary(
    label: str,
    detail: str,
    *,
    attempted: int,
    total: int,
    aborted: bool,
    note: str = '',
) -> None:
    """The one summary line a per-entity pass ends with.

    Every pass reports through here so an aborted one cannot read as a finished one
    in any of them. Each pass had its own line and only the write pass named what it
    never attempted, so a rollback stopped by an outage said ``restored=0`` without
    ever mentioning that thousands of entities were still in the fixed state, and a
    verify said ``checked=0`` as if there had been nothing to check.
    """
    if not aborted:
        LOG.info('%s complete: %s', label, detail)
        return
    LOG.error('%s cut short by the circuit breaker after %d of %d entities (%s); '
              '%d were never attempted%s',
              label, attempted, total, detail, total - attempted, note)


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
    parser.add_argument('--max-retries', type=int, default=3,
                        help='attempts to ride out a transient read failure or an etag '
                             'conflict on write; a 403 is never retried')
    parser.add_argument('--loose-compare', action='store_true',
                        help='treat values equal across types as duplicates')
    parser.add_argument('--validate-schema', action='store_true',
                        help='before writing, confirm the plan does not break JSON schema '
                             'validation against this checkout of registered-json-schemas/')
    parser.add_argument('--allow-unvalidatable', action='store_true',
                        help='proceed even when --validate-schema could not reach a verdict on '
                             'some entities (unreadable, bound to a schema this checkout does '
                             'not have, or with neither a binding nor a Component annotation)')
    parser.add_argument('--allow-incomplete-findings', action='store_true',
                        help='proceed even when the findings file comes from a drill-down that '
                             'did not complete, so the plan covers only part of the audit')
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
                          sleep=args.sleep if args.apply else 0.0,
                          max_retries=args.max_retries)
        log_pass_summary(
            'rollback',
            f'restored={report.restored} would_restore={report.would_restore} '
            f'skipped={report.skipped} failures={len(report.failures)}',
            attempted=report.attempted, total=report.considered, aborted=report.aborted,
            note='; those entities are still in the state the fix left them in, and the '
                 'backup is still on disk, so a re-run picks up where this stopped')
        for failure in report.failures:
            LOG.error('rollback failed for %s: %s', failure['entity_id'], failure['detail'])
        return 0 if report.ok else 1

    log_dir = Path(args.log_dir) if args.log_dir else \
        Path('annotation-fix-logs') / time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    logs = RunLogs(log_dir)

    if args.verify_only:
        syn = _login()
        report = verify_run(syn, logs, max_retries=args.max_retries)
        _log_verify_summary(report)
        return 0 if report.ok else 1

    allowed_actions = parse_actions(args.actions)
    canon = load_canonical_slots(args.schema)
    index = KeyIndex.build(canon)

    entity_ids = list(args.entity)
    coverage_gap = ''
    if args.findings:
        coverage_gap = findings_gap(Path(args.findings))
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

    if coverage_gap and not dry_run and not args.allow_incomplete_findings:
        # The same gate as --allow-unvalidatable, for the same reason: a write run
        # that covers part of the audit while reading as the whole of it is not one
        # a scripted --apply --yes should be able to take by accident. A dry run is
        # let through - there is nothing to protect when nothing is written, and its
        # report is what a curator triages the gap from.
        LOG.error('%s; refusing to apply a plan built from part of the audit '
                  '(--allow-incomplete-findings to accept the gap, or re-run the drill-down)',
                  coverage_gap)
        return 1
    if coverage_gap:
        logs.record_run_note('incomplete_findings', coverage_gap)

    # Set when a dry run carried on past entities the preflight could not vouch
    # for, so the exit code can still say the plan is not one --apply would take.
    unvalidatable_in_dry_run = False
    #: The preflight's dry-run plans, kept so a dry run does not compute them twice.
    dry_runs: list[ApplyResult] = []
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
        # Every entity goes to the preflight, planned or not. Filtering here is
        # what let a failed dry-run read skip the gate and reach the write pass
        # with no verdict behind it.
        dry_runs, aborted = run_guarded(
            entity_ids,
            lambda _position, entity_id: apply_entity(
                syn, entity_id, canon=canon, index=index, logs=logs,
                allowed_actions=allowed_actions, dry_run=True,
                loose_compare=args.loose_compare, max_retries=args.max_retries,
            ),
            failed=_is_failure,
            label='schema preflight planning',
        )
        if aborted:
            LOG.error('no plan was validated, so nothing is offered for approval')
            return 1
        preflight = schema_preflight(syn, dry_runs, registry=registry,
                                     repo_version=repo_version,
                                     max_retries=args.max_retries)
        if preflight.aborted:
            LOG.error('the schema preflight could not reach a verdict on %d of %d entities before '
                      'it was cut short; no plan was validated, so nothing is offered for approval',
                      len(preflight.without_verdict), len(entity_ids))
            return 1
        if preflight.unaccounted:
            LOG.error('schema preflight bucketed %d of %d entities; %d unaccounted for, so no '
                      'count it reports can be trusted; refusing to proceed: %s',
                      preflight.checked + len(preflight.unchanged), len(entity_ids),
                      len(preflight.unaccounted), ', '.join(preflight.unaccounted[:20]))
            return 1
        if preflight.blockers:
            LOG.error('%d entities would fail schema validation after the fix; refusing to proceed',
                      len(preflight.blockers))
            for blocker in preflight.blockers[:20]:
                detail = blocker.after_messages[0] if blocker.after_messages else ''
                LOG.error('  %s (%s): %s', blocker.entity_id, blocker.schema_name, detail[:160])
            return 1
        if preflight.unvalidatable and not args.allow_unvalidatable:
            # Only a write run is refused. In a dry run there is nothing for the
            # gate to protect, and report.csv is the artifact a curator needs in
            # order to triage the very entity that could not be validated - so
            # withholding it would make the escape hatch the path of least
            # resistance, and that habit then carries into the --apply run.
            if not dry_run:
                LOG.error('%d of %d entities could not be validated at all, so the preflight '
                          'cannot vouch for them; refusing to apply '
                          '(--allow-unvalidatable to accept the gap, or drop --validate-schema)',
                          len(preflight.unvalidatable), len(entity_ids))
                for skipped in preflight.unvalidatable[:20]:
                    LOG.error('  %s: %s (%s)',
                              skipped.entity_id, skipped.status, skipped.error or '')
                return 1
            unvalidatable_in_dry_run = True
            LOG.warning('%d of %d entities could not be validated at all; --apply would refuse '
                        'this plan. Continuing the dry run so the report lists them.',
                        len(preflight.unvalidatable), len(entity_ids))
            for skipped in preflight.unvalidatable[:20]:
                LOG.warning('  %s: %s (%s)', skipped.entity_id, skipped.status, skipped.error or '')
        elif preflight.unvalidatable:
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
        verdict = 'incomplete' if unvalidatable_in_dry_run else 'passed'
        LOG.info('schema preflight %s: %d of %d planned changes proven to leave the entity '
                 'conformant (%d already clean, %d repaired, %d unchanged and still invalid, '
                 '%d unvalidatable); %d of %d entities have nothing to change',
                 verdict, preflight.proven, preflight.checked, len(preflight.clean),
                 len(preflight.repaired), len(preflight.still_invalid),
                 len(preflight.unvalidatable), len(preflight.unchanged), len(entity_ids))

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
    aborted = False
    if dry_run and dry_runs:
        # The preflight already planned every one of these entities from a fresh
        # read and recorded its progress line. Planning them again would double the
        # reads and write a second progress line per unchanged entity, inflating
        # what --resume later reads back. A write run is different: it deliberately
        # re-reads and re-decides, because acting on the preflight's now-stale
        # verdict is how a cleanup destroys a concurrently written value.
        results = dry_runs
    else:
        def fix_one(position: int, entity_id: str) -> ApplyResult:
            result = apply_entity(
                syn, entity_id, canon=canon, index=index, logs=logs,
                allowed_actions=allowed_actions, dry_run=dry_run,
                loose_compare=args.loose_compare, max_retries=args.max_retries,
            )
            if not dry_run:
                time.sleep(args.sleep)
                if position % args.batch_size == 0:
                    LOG.info('... %d/%d', position, len(entity_ids))
                    time.sleep(args.batch_pause)
            return result

        results, aborted = run_guarded(entity_ids, fix_one, failed=_is_failure,
                                       label=mode.lower())

    # An aborted pass must not read as a finished one. Without this the log said
    # "APPLY complete: {'ok': 40, 'error': 10}" for a 5,000-entity plan and
    # report.csv held 50 rows, both of which look like a clean, complete run.
    attempted = {result.entity_id for result in results}
    not_attempted = [e for e in entity_ids if e not in attempted]
    write_report(results, logs.report_path, not_attempted=not_attempted,
                 notes=[coverage_gap] if coverage_gap else [])
    counts = summarize(results)
    log_pass_summary(mode, str(counts),
                     attempted=len(attempted), total=len(entity_ids), aborted=aborted,
                     note=' and report.csv covers only the truncated run')
    LOG.info('report written to %s', logs.report_path)

    exit_code = 0
    if counts.get('error') or counts.get('etag_conflict'):
        exit_code = 1
    elif unvalidatable_in_dry_run or any(r.reported for r in results) \
            or (dry_run and coverage_gap and not args.allow_incomplete_findings):
        # 2 is this tool's "the report is written, a human has to look at it":
        # value conflicts the policy will not decide, a plan --apply would refuse
        # because some entity could not be validated, and a dry run over a findings
        # file that covers only part of the audit - which --apply also refuses,
        # unless the same escape hatch says the gap is accepted.
        exit_code = 2

    if args.verify and not dry_run:
        report = verify_run(syn, logs, max_retries=args.max_retries)
        _log_verify_summary(report)
        if not report.ok:
            exit_code = 1
    return exit_code


def _log_verify_summary(report: VerifyReport) -> None:
    log_pass_summary('verify', f'checked={report.checked} failures={len(report.failures)}',
                     attempted=report.attempted, total=report.considered,
                     aborted=report.aborted,
                     note='; the entities it did not reach were not proven unclobbered')
    for failure in report.failures:
        LOG.error('%s: %s', failure['entity_id'], failure['detail'])


_SYN = None


def _login_cached():
    global _SYN
    if _SYN is None:
        _SYN = _login()
    return _SYN


if __name__ == '__main__':
    sys.exit(main())
