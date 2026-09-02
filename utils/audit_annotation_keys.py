#!/usr/bin/env python3
"""
Audit NF-OSI Synapse projects for mis-cased annotation keys (issue #939).

Requires: synapseclient, pyyaml. Read-only - this script never writes to
Synapse. Use ``utils/fix_annotation_keys.py`` to repair what it finds.

How the scan works
------------------
The async REST job ``POST /column/view/scope/async`` returns the complete
annotation-key inventory for an arbitrary scope *without creating an entity*.
One call per project is enough to triage the whole portal in about a minute,
which is what makes a recurring audit cheap enough to run weekly.

The inventory reports presence, not counts: one bad file out of 6,000 looks
identical to wholesale corruption. Use ``--drill-down`` to resolve a project
down to the individual affected entities.

Examples
--------
    # triage every portal study
    python utils/audit_annotation_keys.py --projects-table syn52694652 \
        --extra-project syn35221462 --out-dir audit

    # a couple of known-bad projects, with the affected entities listed
    python utils/audit_annotation_keys.py --project syn25881328 --drill-down

    # regenerate the reports from a previous run, no network
    python utils/audit_annotation_keys.py --out-dir audit --report-only
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
import time
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from annotation_key_policy import (  # noqa: E402
    CANONICAL_SCHEMA,
    KeyIndex,
    classify_key_inventory,
    decide_entity,
    load_canonical_slots,
)
from synapse_annotation_io import read_annotations  # noqa: E402

LOG = logging.getLogger('audit_annotation_keys')

#: file | table | folder | dataset. Deliberately excludes PROJECT(2): project
#: entity annotations are invisible to a view scope and need --include-project-entity.
DEFAULT_VIEW_TYPE_MASK = 0x01 | 0x04 | 0x08 | 0x80  # 141

DEFAULT_PROJECTS_TABLE = 'syn52694652'  # Portal - MV Studies (Production)
DEFAULT_ALLOWLIST = Path(__file__).resolve().parent / 'annotation_key_allowlist.yaml'
PORTAL_FILE_VIEW = 'syn52702673'  # Portal - Files

RETRYABLE_STATUS = (429, 500, 502, 503, 504)


# ---------------------------------------------------------------------------
# Triage allowlist
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Allowlist:
    """Findings a human has looked at and accepted.

    Suppression applies to the exit code only - reports always show everything.
    Without this, a single accepted finding leaves the weekly audit permanently
    red, and a permanently red gate gets ignored.
    """

    #: (key, scope, classification) triples; scope 'global' and classification
    #: 'any' act as wildcards
    entries: frozenset[tuple[str, str, str]] = frozenset()

    def suppresses(self, key: str, project_id: str, classification: str) -> bool:
        for scope in (project_id, 'global'):
            for kind in (classification, 'any'):
                if (key, scope, kind) in self.entries:
                    return True
        return False


def load_allowlist(path: Path | str | None) -> Allowlist:
    if not path:
        return Allowlist()
    path = Path(path)
    if not path.exists():
        LOG.info('no allowlist at %s; nothing suppressed', path)
        return Allowlist()

    with open(path) as handle:
        document = yaml.safe_load(handle) or {}

    today = datetime.now(timezone.utc).date()
    entries: set[tuple[str, str, str]] = set()
    for entry in document.get('entries') or []:
        key = entry.get('key')
        if not key:
            continue
        expires = entry.get('expires')
        if expires is not None:
            if isinstance(expires, str):
                try:
                    expires = date.fromisoformat(expires)
                except ValueError:
                    LOG.warning('allowlist entry for %s has an unparseable expires: %r', key, expires)
                    continue
            if isinstance(expires, datetime):
                expires = expires.date()
            if expires < today:
                # A time-boxed acceptance has to resurface, or "temporary"
                # becomes permanent by neglect.
                LOG.info('allowlist entry for %s expired on %s; finding will resurface',
                         key, expires)
                continue
        entries.add((key, str(entry.get('scope') or 'global'),
                     str(entry.get('classification') or 'any')))
    return Allowlist(frozenset(entries))


# ---------------------------------------------------------------------------
# Synapse access
# ---------------------------------------------------------------------------

def login(auth_token: str | None = None):
    # Imported lazily so the classification and reporting code stays importable -
    # and therefore testable in CI - without synapseclient installed.
    import synapseclient

    syn = synapseclient.Synapse()
    syn.login(authToken=auth_token or os.environ.get('SYNAPSE_AUTH_TOKEN'), silent=True)
    syn.silent = True
    return syn


def _is_forbidden(error: Exception) -> bool:
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    return status in (401, 403) or 'Forbidden' in str(error) or '403' in str(error)[:8]


def _is_retryable(error: Exception) -> bool:
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    if status in RETRYABLE_STATUS:
        return True
    return isinstance(error, (TimeoutError, ConnectionError))


def scope_columns(
    syn,
    scope_id: str,
    *,
    view_type_mask: int = DEFAULT_VIEW_TYPE_MASK,
    async_mode: str = 'auto',
    max_pages: int = 100,
) -> dict[str, set[str]]:
    """Every annotation key in ``scope_id``, mapped to the column types seen.

    A key appearing with more than one column type means the same annotation is
    stored with conflicting value types across entities.
    """
    names: dict[str, set[str]] = {}
    token = None
    for _ in range(max_pages):
        request: dict[str, Any] = {
            'viewScope': {
                'scope': [scope_id],
                'viewEntityType': 'entityview',
                'viewTypeMask': view_type_mask,
            }
        }
        if token:
            request['nextPageToken'] = token
        result = _run_scope_job(syn, request, async_mode=async_mode)
        for column in result.get('results', []):
            names.setdefault(column['name'], set()).add(column['columnType'])
        token = result.get('nextPageToken')
        if not token:
            break
    else:
        raise RuntimeError(f'{scope_id}: scope pagination did not terminate after {max_pages} pages')
    return names


def _run_scope_job(syn, request: dict, *, async_mode: str) -> dict:
    """Run the scope job, preferring the client helper but not depending on it.

    ``syn._waitForAsync`` is private API; a synapseclient upgrade could remove
    it and silently break the audit. The REST fallback uses the same two-step
    pattern as ``utils/register-schemas.py``.
    """
    if async_mode in ('auto', 'client'):
        try:
            return syn._waitForAsync('/column/view/scope/async', request=request)
        except AttributeError:
            if async_mode == 'client':
                raise
        except Exception:
            # A real service error must surface; only a missing helper falls back.
            raise
    return _run_scope_job_rest(syn, request)


def _run_scope_job_rest(syn, request: dict, *, timeout: int = 300) -> dict:
    started = syn.restPOST('/column/view/scope/async/start', body=json.dumps(request))
    token = started['token']
    deadline = time.time() + timeout
    delay = 0.5
    while True:
        status = syn.restGET(f'/asynchronous/job/{token}')
        state = status.get('jobState')
        if state == 'FAILED':
            raise RuntimeError(status.get('errorMessage', 'scope job failed'))
        if state != 'PROCESSING':
            return status
        if time.time() > deadline:
            raise TimeoutError(f'scope job {token} still processing after {timeout}s')
        time.sleep(delay)
        delay = min(delay * 1.5, 5.0)


def list_portal_projects(syn, table_id: str) -> list[dict]:
    """Study projects from the portal studies table."""
    query = syn.tableQuery(
        f'SELECT studyId, studyName, studyStatus FROM {table_id}', resultsAs='csv'
    )
    projects: dict[str, dict] = {}
    with open(query.filepath, newline='') as handle:
        for row in csv.DictReader(handle):
            study_id = (row.get('studyId') or '').strip()
            if not study_id:
                continue
            projects.setdefault(study_id, {
                'project_id': study_id,
                'project_name': (row.get('studyName') or '').strip(),
                'status': (row.get('studyStatus') or '').strip(),
            })
    return sorted(projects.values(), key=lambda p: p['project_id'])


# ---------------------------------------------------------------------------
# Per-project audit
# ---------------------------------------------------------------------------

@dataclass
class ProjectAudit:
    project_id: str
    project_name: str = ''
    status: str = 'ok'  # ok | forbidden | error
    error: str | None = None
    key_types: dict[str, list[str]] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    multitype: dict[str, list[str]] = field(default_factory=dict)
    elapsed_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            'project_id': self.project_id,
            'project_name': self.project_name,
            'status': self.status,
            'error': self.error,
            'key_types': {k: sorted(v) for k, v in self.key_types.items()},
            'summary': self.summary,
            'multitype': self.multitype,
            'elapsed_s': round(self.elapsed_s, 2),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> ProjectAudit:
        return cls(
            project_id=payload['project_id'],
            project_name=payload.get('project_name', ''),
            status=payload.get('status', 'ok'),
            error=payload.get('error'),
            key_types=payload.get('key_types', {}),
            summary=payload.get('summary', {}),
            multitype=payload.get('multitype', {}),
            elapsed_s=payload.get('elapsed_s', 0.0),
        )

    @property
    def finding_counts(self) -> dict[str, int]:
        return {
            bucket: len(self.summary.get(bucket, {}) or {})
            for bucket in ('duplicates', 'orphans', 'case_variants', 'reserved', 'near_misses')
        }

    @property
    def has_findings(self) -> bool:
        counts = self.finding_counts
        return bool(counts['duplicates'] or counts['orphans'] or counts['case_variants'])


def audit_project(
    syn,
    project: dict,
    *,
    canon,
    index: KeyIndex,
    view_type_mask: int,
    include_project_entity: bool,
    async_mode: str,
    max_retries: int,
) -> ProjectAudit:
    audit = ProjectAudit(project_id=project['project_id'], project_name=project.get('project_name', ''))
    started = time.time()
    try:
        key_types = _with_retries(
            lambda: scope_columns(
                syn, audit.project_id, view_type_mask=view_type_mask, async_mode=async_mode
            ),
            max_retries=max_retries,
            label=audit.project_id,
        )
        if include_project_entity:
            # A view scope cannot see the project entity's own annotations.
            for key in _project_entity_keys(syn, audit.project_id):
                key_types.setdefault(key, set()).add('STRING')
    except Exception as error:  # noqa: BLE001 - the failure mode is the finding
        audit.status = 'forbidden' if _is_forbidden(error) else 'error'
        audit.error = f'{type(error).__name__}: {error}'[:300]
        audit.elapsed_s = time.time() - started
        LOG.warning('%s: %s (%s)', audit.project_id, audit.status, audit.error)
        return audit

    audit.key_types = {k: sorted(v) for k, v in key_types.items()}
    audit.multitype = {k: v for k, v in audit.key_types.items() if len(v) > 1}
    audit.summary = classify_key_inventory(key_types, canon=canon, index=index).as_dict()
    audit.elapsed_s = time.time() - started
    return audit


def _project_entity_keys(syn, project_id: str) -> list[str]:
    try:
        return list(read_annotations(syn, project_id).values)
    except Exception as error:  # noqa: BLE001
        LOG.warning('%s: could not read project annotations: %s', project_id, error)
        return []


def _with_retries(call, *, max_retries: int, label: str):
    """Retry transient failures with jittered backoff. Never retries a 403."""
    delay = 2.0
    for attempt in range(max_retries + 1):
        try:
            return call()
        except Exception as error:  # noqa: BLE001
            if _is_forbidden(error) or not _is_retryable(error) or attempt == max_retries:
                raise
            sleep_for = delay + random.uniform(0, delay / 2)
            LOG.info('%s: retry %d/%d after %.1fs (%s)', label, attempt + 1, max_retries,
                     sleep_for, type(error).__name__)
            time.sleep(sleep_for)
            delay = min(delay * 2, 30.0)
    raise AssertionError('unreachable')


# ---------------------------------------------------------------------------
# Entity-level drill-down
# ---------------------------------------------------------------------------

def drill_down_project(
    syn,
    audit: ProjectAudit,
    *,
    canon,
    index: KeyIndex,
    loose_compare: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """Resolve a flagged project down to the individual affected entities.

    Decisions are always made from the entity's own annotations, never from a
    view row: view STRING columns are declared at maximum_size=80 so long values
    come back truncated, a view forces one type per column so the LONG-vs-STRING
    pairs are coerced, lists do not round-trip, and views are eventually
    consistent. Deciding "these are equal, drop one" from any of that could
    destroy the only surviving copy.
    """
    flagged = set(audit.summary.get('duplicates', {})) \
        | set(audit.summary.get('orphans', {})) \
        | set(audit.summary.get('case_variants', {})) \
        | set(audit.summary.get('reserved', {}))
    if not flagged:
        return []

    findings = []
    for entity_id, entity_type in _iter_project_entities(syn, audit.project_id, limit=limit):
        try:
            record = read_annotations(syn, entity_id)
        except Exception as error:  # noqa: BLE001
            LOG.warning('%s: could not read annotations: %s', entity_id, error)
            continue
        annotations = dict(record.values)
        if not flagged & set(annotations):
            continue
        decisions = [
            d for d in decide_entity(annotations, canon=canon, index=index, loose_compare=loose_compare)
            if d.action.value != 'skip'
        ]
        if not decisions:
            continue
        findings.append({
            'project_id': audit.project_id,
            'entity_id': entity_id,
            'entity_type': entity_type,
            'scanned_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'annotations': _jsonable(annotations),
            'value_types': record.types,
            'decisions': [d.as_dict() for d in decisions],
        })
    return findings


def _iter_project_entities(syn, project_id: str, *, limit: int | None = None):
    """Walk files, folders, tables and datasets under a project."""
    seen = 0
    stack = [project_id]
    types = ['file', 'folder', 'table', 'dataset']
    while stack:
        parent = stack.pop()
        try:
            children = list(syn.getChildren(parent, includeTypes=types))
        except Exception as error:  # noqa: BLE001
            LOG.warning('%s: could not list children: %s', parent, error)
            continue
        for child in children:
            entity_type = child['type'].rsplit('.', 1)[-1]
            if entity_type == 'Folder':
                stack.append(child['id'])
            yield child['id'], entity_type
            seen += 1
            if limit is not None and seen >= limit:
                return


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# ---------------------------------------------------------------------------
# State and reports
# ---------------------------------------------------------------------------

def load_state(path: Path) -> dict[str, ProjectAudit]:
    if not path.exists():
        return {}
    audits: dict[str, ProjectAudit] = {}
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            audit = ProjectAudit.from_dict(json.loads(line))
            audits[audit.project_id] = audit
    return audits


def append_state(path: Path, audit: ProjectAudit) -> None:
    """Append one settled project, durably, so a killed run can resume."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as handle:
        handle.write(json.dumps(audit.as_dict()) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


def write_key_rows_csv(audits: Sequence[ProjectAudit], path: Path) -> None:
    fields = ['project_id', 'project_name', 'classification', 'key', 'canonical_key',
              'column_types', 'canonical_present', 'type_conflict']
    with open(path, 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for audit in audits:
            for bucket in ('duplicates', 'orphans', 'case_variants', 'reserved', 'near_misses'):
                for key, canonical in sorted((audit.summary.get(bucket) or {}).items()):
                    writer.writerow({
                        'project_id': audit.project_id,
                        'project_name': audit.project_name,
                        'classification': bucket,
                        'key': key,
                        'canonical_key': canonical,
                        'column_types': '|'.join(audit.key_types.get(key, [])),
                        'canonical_present': canonical in audit.key_types,
                        'type_conflict': len(audit.key_types.get(key, [])) > 1,
                    })


def write_project_rows_csv(audits: Sequence[ProjectAudit], path: Path) -> None:
    fields = ['project_id', 'project_name', 'status', 'total_keys', 'duplicates', 'orphans',
              'case_variants', 'reserved', 'near_misses', 'unknown', 'multitype',
              'elapsed_s', 'error']
    with open(path, 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for audit in sorted(audits, key=lambda a: a.project_id):
            counts = audit.finding_counts
            writer.writerow({
                'project_id': audit.project_id,
                'project_name': audit.project_name,
                'status': audit.status,
                'total_keys': len(audit.key_types),
                'duplicates': counts['duplicates'],
                'orphans': counts['orphans'],
                'case_variants': counts['case_variants'],
                'reserved': counts['reserved'],
                'near_misses': counts['near_misses'],
                'unknown': len(audit.summary.get('unknown') or []),
                'multitype': len(audit.multitype),
                'elapsed_s': round(audit.elapsed_s, 2),
                'error': audit.error or '',
            })


def build_summary(audits: Sequence[ProjectAudit]) -> dict:
    scanned = [a for a in audits if a.status == 'ok']
    forbidden = [a for a in audits if a.status == 'forbidden']
    failed = [a for a in audits if a.status == 'error']
    return {
        'projects_total': len(audits),
        'projects_scanned': len(scanned),
        'projects_forbidden': len(forbidden),
        'projects_failed': len(failed),
        'projects_with_duplicates': sum(1 for a in scanned if a.finding_counts['duplicates']),
        'projects_with_orphans': sum(1 for a in scanned if a.finding_counts['orphans']),
        'projects_with_case_variants': sum(1 for a in scanned if a.finding_counts['case_variants']),
        'projects_with_multitype': sum(1 for a in scanned if a.multitype),
        'projects_with_findings': sum(1 for a in scanned if a.has_findings),
        'key_frequency': {
            bucket: Counter(
                key for a in scanned for key in (a.summary.get(bucket) or {})
            ).most_common()
            for bucket in ('duplicates', 'orphans', 'case_variants', 'reserved', 'near_misses')
        },
        'unscanned': [
            {'project_id': a.project_id, 'status': a.status, 'error': a.error}
            for a in forbidden + failed
        ],
    }


def format_markdown(audits: Sequence[ProjectAudit]) -> str:
    stats = build_summary(audits)
    lines = ['# Annotation key audit', '']

    # Coverage first, deliberately: "0 findings" is meaningless without knowing
    # how many projects were actually readable.
    lines += [
        '## Coverage', '',
        f"- Projects in scope: **{stats['projects_total']}**",
        f"- Scanned: **{stats['projects_scanned']}**",
        f"- Not readable (403): **{stats['projects_forbidden']}**",
        f"- Failed: **{stats['projects_failed']}**",
        '',
    ]
    if stats['projects_forbidden'] or stats['projects_failed']:
        lines += ['> Findings below cover only the scanned projects.', '']

    if not stats['projects_with_findings'] and not stats['projects_with_multitype']:
        lines += ['## Findings', '', 'No mis-cased annotation keys found in any scanned project.', '']
        return '\n'.join(lines)

    lines += [
        '## Findings', '',
        f"- Projects with PascalCase duplicates: **{stats['projects_with_duplicates']}**",
        f"- Projects with PascalCase orphans: **{stats['projects_with_orphans']}**",
        f"- Projects with case-variant drift: **{stats['projects_with_case_variants']}**",
        f"- Projects with conflicting value types: **{stats['projects_with_multitype']}**",
        '',
    ]

    affected = sorted(
        (a for a in audits if a.status == 'ok' and a.has_findings),
        key=lambda a: (-(a.finding_counts['duplicates'] + a.finding_counts['orphans']
                         + a.finding_counts['case_variants']), a.project_id),
    )
    lines += [
        '### Affected projects', '',
        '| Project | Duplicates | Orphans | Case variants | Reserved | Name |',
        '|---|---|---|---|---|---|',
    ]
    for audit in affected:
        counts = audit.finding_counts
        lines.append(
            f"| [{audit.project_id}](https://www.synapse.org/Synapse:{audit.project_id}) "
            f"| {counts['duplicates']} | {counts['orphans']} | {counts['case_variants']} "
            f"| {counts['reserved']} | {audit.project_name[:60]} |"
        )
    lines.append('')

    titles = {
        'duplicates': 'PascalCase duplicates (stray key can be dropped)',
        'orphans': 'PascalCase orphans (metadata invisible to the portal; rename)',
        'case_variants': 'Case-variant drift from former slot names (rename)',
        'reserved': 'Stray keys whose target is a Synapse reserved field (manual review only)',
        'near_misses': 'Probable misspellings of a schema slot (manual review only)',
    }
    for bucket, title in titles.items():
        frequency = stats['key_frequency'][bucket]
        if not frequency:
            continue
        lines += [f'### {title}', '', '| Key | Projects |', '|---|---|']
        lines += [f'| `{key}` | {count} |' for key, count in frequency]
        lines.append('')

    multitype = [a for a in audits if a.multitype]
    if multitype:
        lines += [
            '### Conflicting value types', '',
            ('Same key stored with different column types across entities. Separate root '
             'cause from key casing; tracked separately.'), '',
            '| Project | Key | Types |', '|---|---|---|',
        ]
        for audit in sorted(multitype, key=lambda a: a.project_id):
            for key, types in sorted(audit.multitype.items()):
                lines.append(f"| {audit.project_id} | `{key}` | {', '.join(types)} |")
        lines.append('')

    return '\n'.join(lines)


def write_reports(audits: Sequence[ProjectAudit], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_key_rows_csv(audits, out_dir / 'annotation_key_audit.csv')
    write_project_rows_csv(audits, out_dir / 'annotation_key_audit_projects.csv')
    (out_dir / 'summary.json').write_text(json.dumps(build_summary(audits), indent=2) + '\n')
    (out_dir / 'summary.md').write_text(format_markdown(audits) + '\n')


def exit_code_for(
    audits: Sequence[ProjectAudit],
    *,
    fail_on_findings: bool,
    max_unscanned: int,
    fail_on_unknown: bool = False,
    allowlist: Allowlist | None = None,
) -> int:
    """0 clean, 1 repairable findings, 2 warnings. Mirrors utils/check_schema_limits.py.

    Unrecognised keys do NOT warn by default. Synapse projects legitimately
    carry custom annotations outside the schema (`tissue`, `sampleSite`,
    `dspDatasetIndex`), so gating on them would leave the weekly audit
    permanently yellow - and a permanently yellow gate gets ignored. Probable
    misspellings are different: they are real bugs, so they do warn.
    """
    allowlist = allowlist or Allowlist()
    stats = build_summary(audits)
    unscanned = stats['projects_forbidden'] + stats['projects_failed']

    def unsuppressed(bucket: str) -> bool:
        for audit in audits:
            for key in (audit.summary.get(bucket) or {}):
                if not allowlist.suppresses(key, audit.project_id, bucket):
                    return True
        return False

    if fail_on_findings and any(
        unsuppressed(bucket) for bucket in ('duplicates', 'orphans', 'case_variants')
    ):
        return 1
    if unscanned > max_unscanned:
        return 2
    if unsuppressed('near_misses'):
        return 2
    if fail_on_unknown and any(
        not allowlist.suppresses(key, audit.project_id, 'unknown')
        for audit in audits for key in (audit.summary.get('unknown') or [])
    ):
        return 2
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Audit NF-OSI Synapse projects for mis-cased annotation keys.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--schema', default=str(CANONICAL_SCHEMA), help='path to dist/NF.yaml')
    parser.add_argument('--allowlist', default=str(DEFAULT_ALLOWLIST),
                        help='YAML of findings a human has accepted (exit code only)')
    parser.add_argument('--projects-table', default=None,
                        help=f'portal studies table (default {DEFAULT_PROJECTS_TABLE} '
                             'when no --project is given)')
    parser.add_argument('--project', action='append', default=[], metavar='SYNID',
                        help='audit this project (repeatable)')
    parser.add_argument('--extra-project', action='append', default=[], metavar='SYNID',
                        help='add a project not present in the studies table (repeatable)')
    parser.add_argument('--limit', type=int, default=None, help='audit at most N projects')
    parser.add_argument('--workers', type=int, default=10)
    parser.add_argument('--view-type-mask', type=int, default=DEFAULT_VIEW_TYPE_MASK)
    parser.add_argument('--include-project-entity', action='store_true',
                        help="also read the project entity's own annotations")
    parser.add_argument('--async-mode', choices=['auto', 'client', 'rest'], default='auto')
    parser.add_argument('--max-retries', type=int, default=5)
    parser.add_argument('--max-unscanned', type=int, default=0,
                        help='tolerate this many unreadable projects before exiting 2')
    parser.add_argument('--out-dir', default='audit', help='directory for state and reports')
    parser.add_argument('--state', default=None, help='state file (default <out-dir>/state.jsonl)')
    parser.add_argument('--resume', action='store_true', help='skip projects already scanned')
    parser.add_argument('--report-only', action='store_true',
                        help='regenerate reports from the state file without any network calls')
    parser.add_argument('--drill-down', action='store_true',
                        help='resolve affected projects to individual entities (read-only)')
    parser.add_argument('--drill-down-limit', type=int, default=None,
                        help='stop after walking N entities per project')
    parser.add_argument('--loose-compare', action='store_true',
                        help='treat values equal across types as duplicates')
    parser.add_argument('--fail-on-findings', action='store_true',
                        help='exit 1 when any repairable finding is present')
    parser.add_argument('--fail-on-unknown', action='store_true',
                        help='also exit 2 for annotation keys outside the schema')
    parser.add_argument('--log-level', default='INFO')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format='%(levelname)s %(message)s')
    logging.getLogger('synapseclient').setLevel(logging.ERROR)

    out_dir = Path(args.out_dir)
    state_path = Path(args.state) if args.state else out_dir / 'state.jsonl'
    canon = load_canonical_slots(args.schema)
    index = KeyIndex.build(canon)
    allowlist = load_allowlist(args.allowlist)

    if args.report_only:
        audits = list(load_state(state_path).values())
        if not audits:
            LOG.error('no state found at %s; nothing to report', state_path)
            return 1
        write_reports(audits, out_dir)
        print(format_markdown(audits))
        return exit_code_for(audits, fail_on_findings=args.fail_on_findings,
                             max_unscanned=args.max_unscanned,
                             fail_on_unknown=args.fail_on_unknown,
                             allowlist=allowlist)

    syn = login()

    projects: list[dict] = [{'project_id': p, 'project_name': ''} for p in args.project]
    if not projects or args.projects_table:
        table = args.projects_table or DEFAULT_PROJECTS_TABLE
        LOG.info('listing projects from %s', table)
        projects.extend(list_portal_projects(syn, table))
    for extra in args.extra_project:
        projects.append({'project_id': extra, 'project_name': ''})

    # De-duplicate, preferring the first (named) occurrence.
    unique: dict[str, dict] = {}
    for project in projects:
        unique.setdefault(project['project_id'], project)
    projects = sorted(unique.values(), key=lambda p: p['project_id'])

    existing = load_state(state_path) if args.resume else {}
    if existing:
        before = len(projects)
        projects = [p for p in projects if existing.get(p['project_id'], None) is None
                    or existing[p['project_id']].status != 'ok']
        LOG.info('resuming: %d of %d projects already scanned', before - len(projects), before)
    if args.limit:
        projects = projects[:args.limit]

    LOG.info('auditing %d projects with %d workers', len(projects), args.workers)
    started = time.time()
    audits = list(existing.values())

    def run(project: dict) -> ProjectAudit:
        return audit_project(
            syn, project, canon=canon, index=index,
            view_type_mask=args.view_type_mask,
            include_project_entity=args.include_project_entity,
            async_mode=args.async_mode,
            max_retries=args.max_retries,
        )

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for done, audit in enumerate(pool.map(run, projects), 1):
            append_state(state_path, audit)
            audits.append(audit)
            if done % 25 == 0:
                LOG.info('... %d/%d (%.0fs)', done, len(projects), time.time() - started)

    LOG.info('scan finished in %.0fs', time.time() - started)

    if args.drill_down:
        findings_path = out_dir / 'entity_findings.jsonl'
        out_dir.mkdir(parents=True, exist_ok=True)
        total = 0
        with open(findings_path, 'w') as handle:
            for audit in audits:
                if audit.status != 'ok' or not audit.has_findings:
                    continue
                LOG.info('drilling down %s', audit.project_id)
                for finding in drill_down_project(
                    syn, audit, canon=canon, index=index,
                    loose_compare=args.loose_compare, limit=args.drill_down_limit,
                ):
                    handle.write(json.dumps(finding) + '\n')
                    total += 1
        LOG.info('%d affected entities written to %s', total, findings_path)

    write_reports(audits, out_dir)
    print(format_markdown(audits))
    LOG.info('reports written to %s', out_dir)
    return exit_code_for(audits, fail_on_findings=args.fail_on_findings,
                         max_unscanned=args.max_unscanned,
                         fail_on_unknown=args.fail_on_unknown,
                         allowlist=allowlist)


if __name__ == '__main__':
    sys.exit(main())
