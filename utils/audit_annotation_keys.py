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

    # record a completed scan's findings as the accepted baseline, no network
    python utils/audit_annotation_keys.py --state audit/state.jsonl \
        --emit-allowlist utils/annotation_key_allowlist.yaml
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import threading
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
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
from synapse_annotation_io import (  # noqa: E402
    CircuitBreaker,
    breaker_verdict,
    column_type_for,
    is_forbidden,
    read_annotations,
    with_retries,
)

LOG = logging.getLogger('audit_annotation_keys')

#: Guards the per-project read-failure list, which drill-down worker threads and
#: the scan both append to.
_READ_FAILURE_LOCK = threading.Lock()

#: What was lost, so one entity can hold more than one gap. Four different
#: operations can name the same entity - the scan's key-inventory merge
#: (``--include-project-entity``), a drill-down annotation read, a children
#: listing, and a drill-down the circuit breaker cut short - and each leaves a
#: different hole in coverage. The operation is part of a failure's identity purely
#: so recording one cannot swallow another; nothing here ever retires a failure.
READ_OP_INVENTORY = 'key_inventory'
READ_OP_ANNOTATIONS = 'annotations'
READ_OP_LISTING = 'children_listing'
READ_OP_DRILL_DOWN = 'drill_down_aborted'
#: A state-file entry from before failures recorded which operation they lost.
READ_OP_UNKNOWN = 'unknown'

#: file | table | folder | dataset. Deliberately excludes PROJECT(2): project
#: entity annotations are invisible to a view scope and need --include-project-entity.
DEFAULT_VIEW_TYPE_MASK = 0x01 | 0x04 | 0x08 | 0x80  # 141

#: Row caps for the markdown tables that grow with the data. ``summary.md`` is
#: piped verbatim into a GitHub issue body by the weekly workflow, and an issue
#: body is capped at 65,536 characters, so a per-(project, key) table would
#: eventually take the tracking step down. The CSVs in the run artifact always
#: hold every row.
#:
#: The caps are per section, not one uniform number, because the sections are not
#: alike. The list of affected projects is deliberately uncapped below: it is the
#: one actionable list in the issue and it is one short row per project, so a
#: curator must not have to download a CI artifact to learn which project to look
#: at. What actually grows is the per-key frequency tables (one row per distinct
#: key) and the conflicting-value-types table (one row per project *and* key).
MAX_KEY_FREQUENCY_ROWS = 40
MAX_MULTITYPE_ROWS = 40
MAX_LOST_READ_ROWS = 40

DEFAULT_PROJECTS_TABLE = 'syn52694652'  # Portal - MV Studies (Production)
DEFAULT_ALLOWLIST = Path(__file__).resolve().parent / 'annotation_key_allowlist.yaml'
PORTAL_FILE_VIEW = 'syn52702673'  # Portal - Files


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


#: Buckets a generated baseline covers - exactly the ones that decide the exit
#: code. ``reserved`` is reported but never gates, so an entry for it would
#: suppress nothing and only make the baseline look larger than it is.
BASELINE_BUCKETS = ('duplicates', 'orphans', 'case_variants', 'near_misses')

#: bucket -> the GitHub issue where that family of drift is tracked. Case-variant
#: drift from former slot names is #976; PascalCase duplicates, orphans and
#: probable misspellings are all key hygiene under #939.
BASELINE_ISSUES = {
    'duplicates': 939,
    'orphans': 939,
    'case_variants': 976,
    'near_misses': 939,
}

#: How far out a generated baseline is accepted for. One quarter: long enough to
#: schedule a remediation pass, short enough that neglect makes it resurface.
BASELINE_TTL_DAYS = 90


def build_baseline_entries(
    audits: Sequence[ProjectAudit],
    *,
    expires: date,
    reason: str,
) -> list[dict]:
    """Allowlist entries for every finding a completed scan recorded.

    One entry per (project, key, classification), scoped to the project synID
    rather than ``global``: the same key elsewhere is new drift and must still
    turn the job red, which is the entire point of recording a baseline.

    Every entry is marked ``generated``, which is what lets a later regeneration
    replace the baseline while leaving a curator's hand-added entries alone.
    """
    entries: list[dict] = []
    for audit in audits:
        if audit.status != 'ok':
            continue
        for bucket in BASELINE_BUCKETS:
            for key in sorted((audit.summary.get(bucket) or {})):
                entries.append({
                    'key': key,
                    'scope': audit.project_id,
                    'classification': bucket,
                    'reason': reason,
                    'issue': BASELINE_ISSUES[bucket],
                    'expires': expires.isoformat(),
                    'generated': True,
                })
    return sorted(entries, key=lambda e: (e['scope'], e['classification'], e['key']))


def entry_identity(entry: Mapping) -> tuple[str, str, str]:
    """The (key, scope, classification) triple suppression is keyed on."""
    return (str(entry.get('key') or ''),
            str(entry.get('scope') or 'global'),
            str(entry.get('classification') or 'any'))


def existing_entries(path: Path) -> list[dict]:
    """The entries an allowlist already holds, if it exists.

    Raises ``yaml.YAMLError`` rather than guessing when the file cannot be parsed,
    since the entries at risk are the ones nothing else records.
    """
    if not path.exists():
        return []
    document = yaml.safe_load(path.read_text()) or {}
    return [dict(entry) for entry in (document.get('entries') or [])
            if isinstance(entry, Mapping)]


def hand_added_entries(entries: Sequence[Mapping]) -> list[dict]:
    """The ones ``--emit-allowlist`` did not write.

    Regeneration merges rather than overwrites. The documented workflow is a
    generated baseline that shrinks as remediation lands *plus* whatever a curator
    has triaged by hand, so a regeneration that silently dropped the hand-triaged
    half would make the documented command destructive.
    """
    return [dict(entry) for entry in entries if not entry.get('generated')]


def recorded_expiries(entries: Sequence[Mapping]) -> dict[tuple[str, str, str], str]:
    """Each already-generated entry's expiry, keyed by identity.

    Carried forward by regeneration unless ``--baseline-expires`` says otherwise:
    the expiry is a deadline for remediating the drift, and the documented
    regeneration command silently resetting all 489 of them for another quarter is
    exactly how a time-boxed acceptance becomes permanent by neglect - the thing
    the expiry was added to prevent, and the opposite of what the header and
    utils/README.md tell the reader the file does.
    """
    expiries: dict[tuple[str, str, str], str] = {}
    for entry in entries:
        expires = entry.get('expires')
        if not entry.get('generated') or not expires:
            continue
        if isinstance(expires, datetime):
            expires = expires.date()
        if not isinstance(expires, date):
            try:
                expires = date.fromisoformat(str(expires))
            except ValueError:
                # An unparseable expiry suppresses nothing anyway (load_allowlist
                # drops the entry), so there is no deadline here to carry forward.
                LOG.warning('generated entry for %s has an unparseable expires: %r; it will be '
                            'redated', entry.get('key'), expires)
                continue
        expiries[entry_identity(entry)] = expires.isoformat()
    return expiries


def _entry_block(entries: Sequence[Mapping]) -> str:
    body = yaml.safe_dump([dict(e) for e in entries], sort_keys=False,
                          default_flow_style=False, width=100)
    return '\n'.join(f'  {line}' if line else line
                     for line in body.rstrip('\n').split('\n'))


def format_allowlist(
    generated: Sequence[Mapping],
    hand_added: Sequence[Mapping] = (),
    *,
    header: str,
) -> str:
    """The allowlist document: header comment, generated entries, hand-added ones.

    The two groups are written as separate labelled blocks and every generated
    entry carries ``generated: true``, so both a reader and the next regeneration
    can tell which is which.
    """
    if not generated and not hand_added:
        return f"{header.rstrip()}\n\nentries: []\n"
    lines = [header.rstrip('\n'), '', 'entries:']
    if generated:
        lines.append(_entry_block(generated))
    if hand_added:
        lines += [
            '',
            '  # Hand-triaged entries: added by a curator, not by --emit-allowlist.',
            '  # Regeneration replaces everything above and preserves everything here.',
            _entry_block(hand_added),
        ]
    return '\n'.join(lines) + '\n'


def baseline_header(
    audits: Sequence[ProjectAudit],
    entries: Sequence[Mapping],
    *,
    state_path: Path | str,
    expires: date,
) -> str:
    scanned = sum(1 for a in audits if a.status == 'ok')
    counts = Counter(e['classification'] for e in entries)
    tally = ', '.join(f'{counts[b]} {b}' for b in BASELINE_BUCKETS if counts[b])
    # A state file outside the checkout is one machine's scratch directory, and
    # naming it in a committed file would send the next reader to a path that does
    # not exist for them.
    state_path = Path(state_path)
    try:
        state_path = state_path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        state_path = Path('audit/state.jsonl')
    return '\n'.join([
        '# Annotation-key findings a human has reviewed and accepted.',
        '#',
        '# Consumed by utils/audit_annotation_keys.py. Suppression affects the EXIT CODE',
        '# ONLY - the CSV and markdown reports always list every finding. The point is to',
        '# keep the weekly audit actionable: without a way to record "we looked at this',
        '# and it is fine", one accepted finding leaves the job permanently red, and a',
        '# permanently red job gets ignored.',
        '#',
        '# EVERY ENTRY MARKED `generated: true` IS GENERATED, NOT HAND-WRITTEN. Those are',
        f'# the recorded pre-remediation baseline: every finding present on {scanned} portal',
        '# projects at the time the audit tooling landed, before any Synapse writes. Recording',
        '# them is what lets the weekly job start green so that NEW drift - a project or key',
        '# not listed here - is what turns it red.',
        '#',
        f'# Baseline: {tally}.',
        '#',
        '# Regenerate from a completed scan (no Synapse credentials needed):',
        '#',
        f'#     python utils/audit_annotation_keys.py --state {state_path} \\',
        '#         --emit-allowlist utils/annotation_key_allowlist.yaml',
        '#',
        '# Regeneration MERGES: it replaces the generated block and preserves every entry',
        '# without `generated: true`, so hand-triaged acceptances survive it. Add yours',
        '# without that field (the block at the end of the file is where they collect), and',
        '# do not add it by hand to an entry you want to keep.',
        '#',
        '# This file is expected to SHRINK. Every entry is drift that still exists in',
        f'# Synapse; each remediation pass should delete the entries it fixed. The {expires.isoformat()}',
        '# expiry is not meant to be renewed - once it passes, the findings resurface and',
        '# the job goes red, which is the reminder that the remediation never happened.',
        '# Regeneration keeps each generated entry\'s expiry, so it cannot renew the',
        '# deadline by accident; only an explicit --baseline-expires moves one, and drift',
        '# found since the last regeneration is dated a quarter out from the day it appears.',
        '#',
        '# Fields per entry:',
        '#   key             (required) the annotation key as it appears on entities',
        '#   scope           a project synID, or `global` for every project. Default: global',
        '#   classification  duplicates | orphans | case_variants | reserved | near_misses',
        '#                   | unknown | any. Default: any',
        '#   reason          (required in practice) why this is acceptable',
        '#   issue           the GitHub issue where it was triaged',
        '#   expires         ISO date. After it passes the finding resurfaces, so a',
        '#                   time-boxed acceptance cannot become permanent by neglect.',
        '#                   Carried forward verbatim by regeneration.',
        '#   generated       set by --emit-allowlist. Regeneration replaces these entries',
        '#                   and preserves every entry without it. Leave it off yours.',
        '#',
        '# Keys that are legitimate by construction do NOT belong here - they are handled',
        '# in utils/annotation_key_policy.py:',
        '#   * INFRA_KEYS         schematic manifest columns (Id, Uuid, eTag, EntityId, entityId)',
        '#   * SYNAPSE_VIEW_COLUMNS  Synapse\'s own view metadata (modifiedOn, projectId, ...)',
        '#   * canonical slots that already start uppercase (Component, Filename, GIST, ...)',
        '',
    ])


# ---------------------------------------------------------------------------
# Synapse access
# ---------------------------------------------------------------------------

def login(auth_token: str | None = None, *, pool_size: int = 0):
    # Imported lazily so the classification and reporting code stays importable -
    # and therefore testable in CI - without synapseclient installed.
    import synapseclient

    syn = synapseclient.Synapse()
    syn.login(authToken=auth_token or os.environ.get('SYNAPSE_AUTH_TOKEN'), silent=True)
    syn.silent = True
    if pool_size:
        tune_connection_pool(syn, pool_size)
    return syn


def tune_connection_pool(syn, size: int) -> None:
    """Size the HTTP connection pool to the worker count.

    synapseclient defaults to 10 connections. Running more workers than that
    makes requests discard and re-establish connections
    ("Connection pool is full"), which costs more than the parallelism gains.
    """
    try:
        from requests.adapters import HTTPAdapter
    except ImportError:  # pragma: no cover - requests ships with synapseclient
        return
    session = getattr(syn, '_requests_session', None)
    if session is None:
        return
    adapter = HTTPAdapter(pool_connections=size, pool_maxsize=size, max_retries=0)
    session.mount('https://', adapter)
    session.mount('http://', adapter)


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
            # Only a missing helper falls back; every other error, including a
            # real service failure, propagates.
            if async_mode == 'client':
                raise
    return _run_scope_job_rest(syn, request)


def _run_scope_job_rest(syn, request: dict, *, timeout: int = 300) -> dict:
    return _run_async_job(syn, '/column/view/scope/async', request, timeout=timeout,
                          label='scope job')


def _run_async_job(
    syn,
    path: str,
    request: dict,
    *,
    timeout: int = 300,
    label: str = 'async job',
    get_path: str | None = None,
) -> dict:
    """Start a Synapse asynchronous job and poll until it settles.

    Note the two different result surfaces: most jobs are collected from
    ``/asynchronous/job/{token}``, but table queries are collected from
    ``{path}/get/{token}``. Both report progress via ``jobState``, and both
    return ``PROCESSING`` in the body rather than raising, so polling has to
    inspect the payload rather than catch an exception.
    """
    started = syn.restPOST(f'{path}/start', body=json.dumps(request))
    token = started['token']
    poll = f'{get_path}/{token}' if get_path else f'/asynchronous/job/{token}'
    deadline = time.time() + timeout
    delay = 0.5
    while True:
        status = syn.restGET(poll)
        state = status.get('jobState')
        if state == 'FAILED':
            raise RuntimeError(status.get('errorMessage', f'{label} failed'))
        if state != 'PROCESSING':
            return status
        if time.time() > deadline:
            raise TimeoutError(f'{label} {token} still processing after {timeout}s')
        time.sleep(delay)
        delay = min(delay * 1.5, 5.0)


def query_table(
    syn,
    table_id: str,
    sql: str,
    *,
    timeout: int = 300,
    max_pages: int = 100,
) -> list[dict]:
    """Rows from a Synapse table or view, as dicts keyed by column name.

    Uses the async query service rather than ``syn.tableQuery``, which is
    deprecated for removal in synapseclient 5.0, and avoids both a CSV download
    and a pandas dependency.

    Results are followed to the last page. A query whose rows span pages returns
    a ``nextPageToken``, and stopping at the first page would silently truncate
    the caller's view of the table - for ``list_portal_projects`` that means an
    audit reporting full coverage over a subset of the portal.
    """
    request = {
        'concreteType': 'org.sagebionetworks.repo.model.table.QueryBundleRequest',
        'entityId': table_id,
        'query': {'sql': sql},
        'partMask': 1,  # query results only
    }
    rows: list[dict] = []
    headers: list[str] = []
    token = None
    for _ in range(max_pages):
        if token is None:
            bundle = _run_async_job(
                syn, f'/entity/{table_id}/table/query/async', request, timeout=timeout,
                label='table query', get_path=f'/entity/{table_id}/table/query/async/get',
            )
            page = bundle.get('queryResult') or {}
        else:
            page = _run_async_job(
                syn, f'/entity/{table_id}/table/query/nextPage/async',
                {
                    'concreteType': 'org.sagebionetworks.repo.model.table.QueryNextPageToken',
                    'entityId': table_id,
                    'token': token,
                },
                timeout=timeout, label='table query page',
                get_path=f'/entity/{table_id}/table/query/nextPage/async/get',
            )
        query_results = page.get('queryResults') or {}
        headers = headers or [h['name'] for h in query_results.get('headers') or []]
        for row in query_results.get('rows') or []:
            rows.append(dict(zip(headers, row.get('values') or [])))
        token = page.get('nextPageToken')
        if not token:
            return rows
    raise RuntimeError(f'{table_id}: query pagination did not terminate after {max_pages} pages')


def list_portal_projects(syn, table_id: str) -> list[dict]:
    """Study projects from the portal studies table."""
    projects: dict[str, dict] = {}
    for row in query_table(syn, table_id,
                           f'SELECT studyId, studyName, studyStatus FROM {table_id}'):
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
    #: Reads and listings lost even after the retry budget, plus a drill-down cut
    #: short. Carried in the reports rather than only in a log line: each one is
    #: lost coverage, and ``entity_findings.jsonl`` is the only input the fix tool
    #: reads, so a dropped read silently makes a real finding unfixable.
    #:
    #: The list only ever grows. A run does not retire a gap another run recorded,
    #: not even one whose scope it happens to re-read: deciding that took an
    #: identity for "the same operation" that two rounds of fixes could not keep
    #: straight - a children listing retired an annotation-read gap, an abort was
    #: deduped away behind an entity read - and each mistake made a resumed run
    #: claim coverage it did not have. So a resumed run's coverage figure is not
    #: authoritative and says so in the report: it reports the gaps it inherited as
    #: well as its own, and a full scan is what clears a recovered one.
    read_failures: list[dict] = field(default_factory=list)

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
            'read_failures': self.read_failures,
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
            # An entry that does not name what it lost still counts; it is reported
            # under its own identity rather than being folded into a real one.
            read_failures=[{'operation': READ_OP_UNKNOWN, **failure}
                           for failure in payload.get('read_failures') or []],
        )

    def record_read_failure(
        self,
        entity_id: str,
        error: str,
        entity_type: str = '',
        *,
        operation: str,
    ) -> None:
        """Note lost coverage, at most once per entity per operation.

        One entity can be behind several operations in a run - the scan merges the
        project entity's keys into the inventory, a drill-down reads its
        annotations, the walk lists its children - and each is a distinct gap, so
        recording one must never overwrite or dedupe away another. Repeating the
        *same* operation is what is collapsed, so a recurring failure spends the
        ``--max-unscanned`` budget once rather than once per run. Reads run on a
        thread pool, hence the lock.
        """
        with _READ_FAILURE_LOCK:
            if any((failure.get('entity_id'), failure.get('operation')) == (entity_id, operation)
                   for failure in self.read_failures):
                return
            self.read_failures.append({
                'entity_id': entity_id,
                'entity_type': entity_type,
                'operation': operation,
                'error': error,
            })

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
        key_types = with_retries(
            lambda: scope_columns(
                syn, audit.project_id, view_type_mask=view_type_mask, async_mode=async_mode
            ),
            max_retries=max_retries,
            label=audit.project_id,
            logger=LOG,
        )
        if include_project_entity:
            # A view scope cannot see the project entity's own annotations. Merge
            # each key's declared type, not a placeholder: the multitype report is
            # triage input for the value-type issue, so a fabricated STRING would
            # invent a conflict against a real INTEGER or DOUBLE column. The
            # annotation type is translated into the view's ColumnType vocabulary
            # first, for the same reason.
            columns, read_error = _project_entity_column_types(
                syn, audit.project_id, max_retries=max_retries)
            if read_error:
                # Recorded against the inventory merge below, which is the gap: only
                # another scan of this project redoes it. A drill-down reading the
                # same entity does not re-derive key_types.
                audit.record_read_failure(audit.project_id, read_error, 'Project',
                                          operation=READ_OP_INVENTORY)
            for key, column in columns.items():
                key_types.setdefault(key, set()).add(column)
    except Exception as error:  # noqa: BLE001 - the failure mode is the finding
        audit.status = 'forbidden' if is_forbidden(error) else 'error'
        audit.error = f'{type(error).__name__}: {error}'[:300]
        audit.elapsed_s = time.time() - started
        LOG.warning('%s: %s (%s)', audit.project_id, audit.status, audit.error)
        return audit

    audit.key_types = {k: sorted(v) for k, v in key_types.items()}
    audit.multitype = {k: v for k, v in audit.key_types.items() if len(v) > 1}
    audit.summary = classify_key_inventory(key_types, canon=canon, index=index).as_dict()
    audit.elapsed_s = time.time() - started
    return audit


def _project_entity_column_types(
    syn,
    project_id: str,
    *,
    max_retries: int = 0,
) -> tuple[dict[str, str], str | None]:
    """The project entity's own annotation keys, as view column types.

    A key is reported in the vocabulary the rest of the inventory uses, so a
    ``LONG`` project annotation matches an ``INTEGER`` column and a multi-value
    one matches the corresponding ``*_LIST``.

    Returns the keys and, when the read was lost, the reason - which the caller
    records as a finding. Losing this read means the project's own annotations
    were not audited at all, which must not read as "nothing found there".
    """
    try:
        record = read_annotations(syn, project_id, max_retries=max_retries)
    except Exception as error:  # noqa: BLE001
        LOG.warning('%s: could not read project annotations: %s', project_id, error)
        return {}, f'{type(error).__name__}: {error}'[:300]
    return {
        key: column_type_for(declared, len(record.values.get(key) or []))
        for key, declared in record.types.items()
    }, None


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
    workers: int = 1,
    include_project_entity: bool = False,
    max_retries: int = 0,
    breaker: CircuitBreaker | None = None,
) -> tuple[list[dict], bool]:
    """Resolve a flagged project down to the individual affected entities.

    Decisions are always made from the entity's own annotations, never from a
    view row: view STRING columns are declared at maximum_size=80 so long values
    come back truncated, a view forces one type per column so the LONG-vs-STRING
    pairs are coerced, lists do not round-trip, and views are eventually
    consistent. Deciding "these are equal, drop one" from any of that could
    destroy the only surviving copy.

    Reads get ``max_retries`` attempts, and one still lost after them is appended
    to ``audit.read_failures`` rather than merely logged: the findings file is the
    fix tool's only input, so an entity dropped from it is a finding that can
    never be repaired, and the reports have to say so.

    This is the largest per-entity network loop in the tooling - 13,150 entities on
    the recorded portal scan - so it is guarded by the same circuit breaker as every
    loop in ``fix_annotation_keys``. With a retry budget and no guard, a degradation
    confined to ``/entity/{id}/annotations2`` would make each read pay the full
    jittered backoff before failing, which is over a day of grinding to reach a
    state file that is nothing but read failures. The breaker is sampled per
    request - the walk's folder listings as well as the annotation reads, so a
    degradation confined to one of the two endpoints cannot hide behind the other
    one's successes - and the abort is itself recorded as lost coverage: entities the
    pass never inspected are absent from ``entity_findings.jsonl`` just as surely as
    ones whose read failed.

    Only a request the service may have failed is sampled. A definitive answer - a
    403 on an entity behind a per-folder ACL, a 404 on one deleted since the scan -
    is recorded as lost coverage and skipped by the window: two such entities in a
    project were otherwise enough to abort the drill-down of every project after it.

    ``breaker`` is supplied by the caller so one window spans the whole run. A
    breaker built here per call gave every project a fresh window, so a systemic
    degradation cost one breaker's worth of doomed reads *per project* - about ten
    minutes each, nine hours across the 53 flagged projects on the recorded scan -
    when the point of the guard is that one systemic failure stops the run.

    Returns the findings and whether this project was cut short, so a caller
    deciding whether its pass completed does not have to infer it from a side
    effect. Inferring it is what stamped a truncated drill-down complete: the
    caller's own bookkeeping only recorded projects it skipped *before* starting
    them, so an abort inside the last - or only - flagged project left that
    bookkeeping empty and looked exactly like a clean run.
    """
    flagged = set(audit.summary.get('duplicates', {})) \
        | set(audit.summary.get('orphans', {})) \
        | set(audit.summary.get('case_variants', {})) \
        | set(audit.summary.get('reserved', {}))
    if not flagged:
        return [], False

    def inspect(target: tuple[str, str]) -> tuple[dict | None, bool | None]:
        """One entity's finding, if any, and how the breaker samples its read.

        A lost read is always recorded as lost coverage; only one the service may
        have failed is sampled. A 403 on an entity behind a per-folder ACL is a fact
        about that entity, and sampling it aborted the whole drill-down over two such
        entities - deterministically, so re-running reproduced the abort.
        """
        entity_id, entity_type = target
        try:
            record = read_annotations(syn, entity_id, max_retries=max_retries)
        except Exception as error:  # noqa: BLE001
            LOG.warning('%s: could not read annotations: %s', entity_id, error)
            audit.record_read_failure(entity_id, f'{type(error).__name__}: {error}'[:300],
                                      entity_type, operation=READ_OP_ANNOTATIONS)
            return None, breaker_verdict(error)
        annotations = dict(record.values)
        if not flagged & set(annotations):
            return None, False
        decisions = [
            d for d in decide_entity(annotations, canon=canon, index=index, loose_compare=loose_compare)
            if d.action.value != 'skip'
        ]
        if not decisions:
            return None, False
        return {
            'project_id': audit.project_id,
            'entity_id': entity_id,
            'entity_type': entity_type,
            'scanned_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'annotations': _jsonable(annotations),
            'value_types': record.types,
            'decisions': [d.as_dict() for d in decisions],
        }, False

    breaker = breaker if breaker is not None else CircuitBreaker()
    walker = _iter_project_entities(syn, audit.project_id, limit=limit, workers=workers,
                                    include_project_entity=include_project_entity,
                                    max_retries=max_retries, audit=audit, breaker=breaker)
    findings: list[dict] = []
    aborted = False

    def collect(batch: Sequence[tuple[dict | None, bool | None]]) -> bool:
        findings.extend(finding for finding, _verdict in batch if finding)
        return breaker.sample(verdict for _finding, verdict in batch)

    if workers <= 1:
        for target in walker:
            if collect([inspect(target)]):
                aborted = True
                break
    else:
        # Reads are independent, so they parallelise safely. Chunked rather than
        # materialised so the walk and the reads overlap and memory stays bounded
        # on a project with tens of thousands of entities. The breaker is judged at
        # the end of each chunk, so a degradation costs at most one chunk of extra
        # reads rather than the rest of the project.
        chunk_size = max(workers * 8, 64)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            chunk: list[tuple[str, str]] = []
            for target in walker:
                chunk.append(target)
                if len(chunk) >= chunk_size:
                    aborted = collect(list(pool.map(inspect, chunk)))
                    chunk = []
                    if aborted:
                        break
            if chunk and not aborted:
                aborted = collect(list(pool.map(inspect, chunk)))

    # The walk stops itself when a listing trips the breaker, which leaves the loop
    # above with nothing more to consume and no verdict of its own, so the abort has
    # to be read off the breaker rather than only off the read loop.
    aborted = aborted or breaker.tripped

    if aborted:
        # Recorded as its own operation, so it cannot be deduped away behind the
        # project entity's own failed read - which during an outage fails first, and
        # is the documented --include-project-entity --drill-down combination. A
        # reader has to be able to tell 64 lost reads from 64 lost reads plus
        # thousands of entities never looked at.
        detail = (f'drill-down aborted after {breaker.failures} of the last {breaker.window} '
                  'requests failed; the rest of this project was not inspected')
        LOG.error('%s: %s', audit.project_id, detail)
        audit.record_read_failure(audit.project_id, detail, 'Project',
                                  operation=READ_OP_DRILL_DOWN)
    return findings, aborted


FINDINGS_NAME = 'entity_findings.jsonl'
PARTIAL_FINDINGS_NAME = 'entity_findings.partial.jsonl'


def findings_manifest_path(findings_path: Path) -> Path:
    """The sidecar that says whether a findings file covers a completed pass."""
    return findings_path.with_suffix('.manifest.json')


def write_findings_manifest(
    findings_path: Path,
    *,
    complete: bool,
    projects: Sequence[str],
    entities: int,
    not_inspected: Sequence[str] = (),
    partially_inspected: Sequence[str] = (),
) -> Path:
    """Record what a findings file covers, next to the file itself.

    ``fix_annotation_keys.py --findings`` consumes the findings file and nothing
    else, so the file has to be able to say for itself whether it represents a
    completed drill-down. Without that, a plan built from a pass the circuit breaker
    cut short looks exactly like a plan built from a complete one.

    ``partially_inspected`` names the projects the pass started and did not finish,
    which is a different gap from one it never reached: an abort inside the last -
    or only - flagged project leaves nothing in ``not_inspected`` at all.
    """
    manifest = {
        'findings_file': findings_path.name,
        'complete': bool(complete),
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'entities': entities,
        'projects_inspected': list(projects),
        'projects_not_inspected': list(not_inspected),
        'projects_partially_inspected': list(partially_inspected),
    }
    path = findings_manifest_path(findings_path)
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    return path


def read_findings_manifest(findings_path: Path) -> dict | None:
    """The manifest beside a findings file, or None when there is not one."""
    path = findings_manifest_path(findings_path)
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return manifest if isinstance(manifest, dict) else None


def run_drill_down(
    syn,
    audits: Sequence[ProjectAudit],
    out_dir: Path,
    *,
    canon: frozenset[str],
    index: KeyIndex,
    loose_compare: bool = False,
    limit: int | None = None,
    workers: int = 1,
    include_project_entity: bool = False,
    max_retries: int = 0,
) -> list[ProjectAudit]:
    """Drill every flagged project down to its affected entities.

    Rows are written to a partial path first and only moved onto
    ``entity_findings.jsonl`` when the pass ran to completion. The breaker spans the
    run, so an abort skips every remaining flagged project; writing straight to the
    real path would then replace a previous *complete* findings file with a subset,
    and that file is the only input ``fix_annotation_keys.py --findings`` reads - a
    curator who re-ran the drill-down during a transient degradation would repair
    part of the work believing it was all of it. An abort now leaves the last good
    file untouched and its own output at ``entity_findings.partial.jsonl``, and
    either way a manifest beside the file names the projects it covers.

    Completion is the positive signal every project reports, not the absence of
    skipped ones: the pre-project guard only names projects the pass never started,
    so an abort *inside* the last - or only - flagged project left that list empty
    and promoted a truncated file with ``complete: true`` stamped on it.

    Returns the projects whose state lines the caller has to rewrite: the ones this
    pass inspected, plus the ones it never reached, each carrying the abort as lost
    coverage.
    """
    findings_path = out_dir / FINDINGS_NAME
    partial_path = out_dir / PARTIAL_FINDINGS_NAME
    # One breaker for the whole drill-down, not one per project: a systemic
    # degradation has to stop the run, and a per-project window merely made it
    # cost one breaker's worth of doomed reads per project instead.
    breaker = CircuitBreaker()
    flagged = [a for a in audits if a.status == 'ok' and a.has_findings]
    drilled: list[ProjectAudit] = []
    inspected: list[str] = []
    not_inspected: list[str] = []
    partially_inspected: list[str] = []
    completed = True
    total = 0

    with open(partial_path, 'w') as handle:
        for position, audit in enumerate(flagged):
            if breaker.tripped:
                skipped = flagged[position:]
                detail = ('drill-down stopped before this project: '
                          f'{breaker.failures} of the last {breaker.window} requests failed')
                LOG.error('drill-down stopped after %d of %d projects; %d not inspected',
                          position, len(flagged), len(skipped))
                for pending in skipped:
                    pending.record_read_failure(pending.project_id, detail, 'Project',
                                                operation=READ_OP_DRILL_DOWN)
                    drilled.append(pending)
                    not_inspected.append(pending.project_id)
                completed = False
                break
            LOG.info('drilling down %s', audit.project_id)
            drilled.append(audit)
            inspected.append(audit.project_id)
            findings, aborted = drill_down_project(
                syn, audit, canon=canon, index=index,
                loose_compare=loose_compare, limit=limit, workers=workers,
                include_project_entity=include_project_entity,
                max_retries=max_retries, breaker=breaker,
            )
            for finding in findings:
                handle.write(json.dumps(finding) + '\n')
                total += 1
            if aborted:
                completed = False
                partially_inspected.append(audit.project_id)

    if not completed:
        manifest = write_findings_manifest(partial_path, complete=False, projects=inspected,
                                           entities=total, not_inspected=not_inspected,
                                           partially_inspected=partially_inspected)
        kept = (f'{findings_path} was left as it was' if findings_path.exists()
                else f'no {findings_path} was written')
        LOG.error('the drill-down did not complete, so %s; the %d entities this pass did '
                  'resolve are in %s, described by %s - re-run the drill-down before feeding '
                  'anything to fix_annotation_keys.py', kept, total, partial_path, manifest)
        return drilled

    os.replace(partial_path, findings_path)
    stale = findings_manifest_path(partial_path)
    if stale.exists():
        stale.unlink()
    write_findings_manifest(findings_path, complete=True, projects=inspected, entities=total)
    LOG.info('%d affected entities across %d projects written to %s',
             total, len(inspected), findings_path)
    return drilled


CHILD_TYPES = ('file', 'folder', 'table', 'dataset')


def _list_children(syn, parent_id: str) -> list[dict]:
    """One page-through of an entity's children via the stable REST endpoint.

    ``syn.getChildren`` is deprecated for removal in synapseclient 5.0;
    ``POST /entity/children`` is the underlying service and is not going away.
    """
    children: list[dict] = []
    token = None
    while True:
        body: dict[str, Any] = {
            'parentId': parent_id,
            'includeTypes': list(CHILD_TYPES),
            'sortBy': 'NAME',
            'sortDirection': 'ASC',
        }
        if token:
            body['nextPageToken'] = token
        page = syn.restPOST('/entity/children', body=json.dumps(body))
        children.extend(page.get('page') or [])
        token = page.get('nextPageToken')
        if not token:
            return children


def _safe_list_children(
    syn,
    parent_id: str,
    *,
    max_retries: int = 0,
    audit: ProjectAudit | None = None,
) -> tuple[list[dict], bool | None]:
    """Children of one entity, and how the circuit breaker samples the listing.

    An unreadable folder yields nothing rather than aborting a walk over thousands
    of siblings, but the caller is told, because a swallowed listing is a coverage
    gap and one lost during a systemic degradation has to reach the circuit breaker.
    A listing the service answered definitively - a 403 on a folder with its own ACL -
    is recorded as a gap but not sampled, so the guard fires on an outage rather than
    on a permission the curator was never going to have.

    A listing gets the same retry budget as an annotation read, and one still lost
    after them is recorded on the audit as lost coverage - under its own operation,
    since an unlisted folder and an unread entity are different gaps. Swallowing it
    into an empty page was the one lost-read path that was not treated as a finding:
    a single 503 on a project's root made the walk yield nothing, so the project
    contributed no rows to ``entity_findings.jsonl`` - the fix tool's only input -
    while the report still said "Entity reads lost after retries: 0" for a project
    it listed as affected, and the run exited 0.
    """
    try:
        return with_retries(lambda: _list_children(syn, parent_id),
                            max_retries=max_retries, label=parent_id, logger=LOG), False
    except Exception as error:  # noqa: BLE001
        LOG.warning('%s: could not list children: %s', parent_id, error)
        if audit is not None:
            audit.record_read_failure(
                parent_id,
                f'could not list children: {type(error).__name__}: {error}'[:300],
                operation=READ_OP_LISTING)
        return [], breaker_verdict(error)


def _iter_project_entities(
    syn,
    project_id: str,
    *,
    limit: int | None = None,
    workers: int = 1,
    include_project_entity: bool = False,
    max_retries: int = 0,
    audit: ProjectAudit | None = None,
    breaker: CircuitBreaker | None = None,
):
    """Walk files, folders, tables and datasets under a project.

    Breadth-first, listing every folder at a given depth in parallel. The walk,
    not the annotation reads, is what dominates a large project: syn23664726 has
    over 1,300 folders, and listing them one at a time took longer than reading
    every annotation in the project. Levels are expanded lazily, so a caller
    that stops early does not pay for the rest of the tree.

    ``include_project_entity`` yields the project itself first. Without it a
    project whose only stray keys sit on the project entity is reported in the
    summary but contributes no row to ``entity_findings.jsonl``, which is the
    only input ``fix_annotation_keys.py --findings`` reads - the finding would be
    visible and unfixable. It stays opt-in, matching the audit flag that folds
    those keys into the inventory in the first place.

    An ``audit`` makes a lost listing part of the caller's coverage accounting;
    without one an unreadable folder is only logged, which is fine for a caller
    that is not reporting coverage at all.

    A ``breaker`` samples each listing, so the walk is guarded like every other
    per-entity network loop and stops the moment the trailing failure rate says the
    service is systemically unwell. Without it a degradation confined to
    ``POST /entity/children`` was invisible: the healthy annotation reads filled the
    window with successes while every listing paid the full jittered backoff, which
    is hours of grinding on the 1,300-folder project above. One window holds both
    kinds of request deliberately - the ratio it measures is "requests to Synapse
    that failed", not a per-endpoint rate, which is the right question for a guard
    whose job is to notice that the service as a whole has stopped answering. A
    listing the service refused outright is not one of those: it is recorded as a gap
    and left out of the window.
    """
    seen = 0
    frontier = [project_id]
    visited: set[str] = {project_id}

    if include_project_entity:
        yield project_id, 'Project'
        seen += 1
        if limit is not None and seen >= limit:
            return

    def children_of(parent: str) -> tuple[list[dict], bool | None]:
        return _safe_list_children(syn, parent, max_retries=max_retries, audit=audit)

    # A level is listed in chunks rather than all at once so the breaker is judged
    # often enough to matter: one level of the 1,300-folder project is 1,300 doomed
    # listings during an outage, which is hours. Chunked exactly like the
    # drill-down's reads - workers stay busy, and a degradation costs at most one
    # chunk of extra listings.
    chunk_size = max(workers * 8, 64) if workers > 1 else 1

    while frontier:
        next_frontier: list[str] = []
        tripped = False
        for start in range(0, len(frontier), chunk_size):
            batch = frontier[start:start + chunk_size]
            if workers > 1 and len(batch) > 1:
                with ThreadPoolExecutor(max_workers=min(workers, len(batch))) as pool:
                    listings = list(pool.map(children_of, batch))
            else:
                listings = [children_of(parent) for parent in batch]

            tripped = breaker is not None and \
                breaker.sample(verdict for _children, verdict in listings)
            # Children already fetched are yielded even when this chunk tripped the
            # breaker: they were read, so dropping them would lose coverage silently.
            for children, _verdict in listings:
                for child in children:
                    entity_type = child['type'].rsplit('.', 1)[-1]
                    if entity_type == 'Folder' and child['id'] not in visited:
                        visited.add(child['id'])
                        next_frontier.append(child['id'])
                    yield child['id'], entity_type
                    seen += 1
                    if limit is not None and seen >= limit:
                        return
            if tripped:
                return
        frontier = next_frontier


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


def carry_forward(
    existing: Mapping[str, ProjectAudit],
    rescanning: Iterable[str],
) -> list[ProjectAudit]:
    """State-file entries this run is not redoing, and so must carry forward.

    A resumed run rescans the projects that previously came back forbidden or
    failed. Carrying their stale audit forward as well would count them twice:
    the same project reported as both scanned and forbidden, ``projects_total``
    inflated, and a duplicate row in the CSV - so a resume that successfully
    retried three 403s would still exit 2 on them.

    Each carried-forward audit comes through exactly as recorded, entity read
    failures included. A resumed run does not retire another run's coverage gaps at
    all - see :attr:`ProjectAudit.read_failures` - so it reports the gaps it
    inherited alongside its own and says in the report that its coverage figure is
    not authoritative. That under-claims coverage, which is the honest direction;
    only a full scan clears a gap a later run recovered.
    """
    pending = set(rescanning)
    return [audit for audit in existing.values() if audit.project_id not in pending]


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
              'read_failures', 'elapsed_s', 'error']
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
                'read_failures': len(audit.read_failures),
                'elapsed_s': round(audit.elapsed_s, 2),
                'error': audit.error or '',
            })


def build_summary(audits: Sequence[ProjectAudit], *, carried_forward: int = 0) -> dict:
    """Run-level counts.

    ``carried_forward`` is how many project audits came out of the state file
    instead of being read by this run. Any of it makes the coverage figures
    non-authoritative: they include reads this run did not perform, and a gap an
    earlier run recorded is still reported because nothing here re-verified it.
    """
    scanned = [a for a in audits if a.status == 'ok']
    forbidden = [a for a in audits if a.status == 'forbidden']
    failed = [a for a in audits if a.status == 'error']
    return {
        'projects_total': len(audits),
        'projects_scanned': len(scanned),
        'projects_carried_forward': carried_forward,
        'coverage_authoritative': not carried_forward,
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
        'entity_read_failures': sum(len(a.read_failures) for a in audits),
        'entity_reads_lost': [
            dict(failure, project_id=a.project_id)
            for a in audits for failure in a.read_failures
        ],
    }


def _truncation_note(total: int, shown: int) -> list[str]:
    """A line naming what a capped table left out, and where the rest lives."""
    if total <= shown:
        return []
    return ['', f'_{total - shown} more rows omitted; every row is in the '
                '`annotation-key-audit` artifact (the CSVs and `state.jsonl`)._']


def format_markdown(audits: Sequence[ProjectAudit], *, carried_forward: int = 0) -> str:
    stats = build_summary(audits, carried_forward=carried_forward)
    lines = ['# Annotation key audit', '']

    # Coverage first, deliberately: "0 findings" is meaningless without knowing
    # how many projects were actually readable.
    lines += [
        '## Coverage', '',
        f"- Projects in scope: **{stats['projects_total']}**",
        f"- Scanned: **{stats['projects_scanned']}**",
        f"- Not readable (403): **{stats['projects_forbidden']}**",
        f"- Failed: **{stats['projects_failed']}**",
        f"- Entity reads lost after retries: **{stats['entity_read_failures']}**",
        f"- Carried forward from an earlier run: **{stats['projects_carried_forward']}**",
        '',
    ]
    if not stats['coverage_authoritative']:
        lines += [
            (f"> **This coverage figure is not authoritative.** "
             f"{stats['projects_carried_forward']} of {stats['projects_total']} project audits "
             'came from the state file rather than from reads this run performed, and a lost '
             'read another run recorded is still reported here because nothing in this run '
             're-verified it. Re-run a full scan (without `--resume`) for an authoritative '
             'figure.'), '',
        ]
    if stats['projects_forbidden'] or stats['projects_failed']:
        lines += ['> Findings below cover only the scanned projects.', '']
    if stats['entity_read_failures']:
        lines += [
            ('> Some entity reads were lost, so the entity-level findings are incomplete and '
             'the affected entities are absent from `entity_findings.jsonl`. Re-run the '
             'drill-down for the projects listed below. The operation column says what was '
             'lost: an unread entity, a folder whose children were never enumerated, a key '
             'inventory that was never merged, or a drill-down that stopped early.'), '',
            '| Project | Entity | Lost | Error |', '|---|---|---|---|',
        ]
        lost = stats['entity_reads_lost']
        lines += [
            f"| {item['project_id']} | {item['entity_id']} "
            f"| {item.get('operation') or READ_OP_UNKNOWN} "
            f"| {str(item.get('error') or '')[:120]} |"
            for item in lost[:MAX_LOST_READ_ROWS]
        ]
        lines += _truncation_note(len(lost), MAX_LOST_READ_ROWS)
        lines.append('')

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
    # Uncapped on purpose: this is the list a curator acts on.
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
        lines += [f'| `{key}` | {count} |' for key, count in frequency[:MAX_KEY_FREQUENCY_ROWS]]
        lines += _truncation_note(len(frequency), MAX_KEY_FREQUENCY_ROWS)
        lines.append('')

    multitype = [a for a in audits if a.multitype]
    if multitype:
        lines += [
            '### Conflicting value types', '',
            ('Same key stored with different column types across entities. Separate root '
             'cause from key casing; tracked separately.'), '',
            '| Project | Key | Types |', '|---|---|---|',
        ]
        rows = [
            f"| {audit.project_id} | `{key}` | {', '.join(types)} |"
            for audit in sorted(multitype, key=lambda a: a.project_id)
            for key, types in sorted(audit.multitype.items())
        ]
        lines += rows[:MAX_MULTITYPE_ROWS]
        lines += _truncation_note(len(rows), MAX_MULTITYPE_ROWS)
        lines.append('')

    return '\n'.join(lines)


def write_reports(
    audits: Sequence[ProjectAudit],
    out_dir: Path,
    *,
    carried_forward: int = 0,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_key_rows_csv(audits, out_dir / 'annotation_key_audit.csv')
    write_project_rows_csv(audits, out_dir / 'annotation_key_audit_projects.csv')
    (out_dir / 'summary.json').write_text(
        json.dumps(build_summary(audits, carried_forward=carried_forward), indent=2) + '\n')
    (out_dir / 'summary.md').write_text(
        format_markdown(audits, carried_forward=carried_forward) + '\n')


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

    A resumed run cannot clear a lost read: gaps are never retired, only recorded,
    so an inherited one keeps spending the ``--max-unscanned`` budget. Exit 0 from a
    ``--resume`` therefore means "nothing new went wrong", and only a full scan -
    or, for an accepted gap, ``--max-unscanned`` - turns a run that inherited a
    transient failure green again.
    """
    allowlist = allowlist or Allowlist()
    stats = build_summary(audits)
    # An entity read lost after the retry budget is the same kind of problem as an
    # unreadable project - coverage this run cannot vouch for - so it spends the
    # same budget rather than passing silently.
    unscanned = (stats['projects_forbidden'] + stats['projects_failed']
                 + stats['entity_read_failures'])

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

def emit_allowlist(
    audits: Sequence[ProjectAudit],
    path: Path,
    *,
    state_path: Path,
    expires: str | None = None,
) -> int:
    """Write a completed scan's findings out as an allowlist baseline.

    Merges: the generated baseline is replaced wholesale, and every entry a
    curator added by hand is carried over untouched. Where a hand-added entry
    covers the same (key, scope, classification) as a generated one, the
    hand-added one stands - its reason and expiry are the human's decision.

    An already-generated entry also keeps its recorded expiry. Only an explicit
    ``--baseline-expires`` moves a deadline, so the documented regeneration command
    cannot quietly renew the whole baseline for another quarter. Drift found since
    the last regeneration gets the default expiry, which is how a fresh finding
    still lands with one.
    """
    if expires:
        try:
            expiry = date.fromisoformat(expires)
        except ValueError:
            LOG.error('--baseline-expires must be an ISO date (YYYY-MM-DD); got %r', expires)
            return 1
    else:
        expiry = datetime.now(timezone.utc).date() + timedelta(days=BASELINE_TTL_DAYS)

    try:
        already = existing_entries(path)
    except yaml.YAMLError as error:
        LOG.error('%s exists but could not be parsed (%s); refusing to overwrite it, because '
                  'any hand-triaged entries it holds would be lost', path, error)
        return 1

    preserved = hand_added_entries(already)
    carried = {} if expires else recorded_expiries(already)
    scanned = sum(1 for a in audits if a.status == 'ok')
    reason = (f'Pre-remediation baseline from the {scanned}-project portal scan; '
              'drift still present in Synapse.')
    hand_triaged = {entry_identity(e) for e in preserved}
    entries = [
        {**entry, 'expires': carried.get(entry_identity(entry), entry['expires'])}
        for entry in build_baseline_entries(audits, expires=expiry, reason=reason)
        if entry_identity(entry) not in hand_triaged
    ]
    # The header names the deadline the reader has to act on, which once expiries
    # are carried forward is the earliest one still in the file.
    deadline = min((date.fromisoformat(e['expires']) for e in entries), default=expiry)
    header = baseline_header(audits, entries, state_path=state_path, expires=deadline)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_allowlist(entries, preserved, header=header))
    counts = Counter(e['classification'] for e in entries)
    renewed = sum(1 for e in entries if entry_identity(e) not in carried)
    LOG.info('wrote %d baseline entries to %s (%s); %d kept their recorded expiry, %d dated %s; '
             'earliest deadline %s; %d hand-triaged entries preserved',
             len(entries), path,
             ', '.join(f'{counts[b]} {b}' for b in BASELINE_BUCKETS if counts[b]),
             len(entries) - renewed, renewed, expiry.isoformat(), deadline.isoformat(),
             len(preserved))
    return 0


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
                        help='tolerate this many unreadable projects, plus entity reads lost '
                             'during --drill-down, before exiting 2')
    parser.add_argument('--out-dir', default='audit', help='directory for state and reports')
    parser.add_argument('--state', default=None, help='state file (default <out-dir>/state.jsonl)')
    parser.add_argument('--resume', action='store_true', help='skip projects already scanned')
    parser.add_argument('--report-only', action='store_true',
                        help='regenerate reports from the state file without any network calls')
    parser.add_argument('--emit-allowlist', default=None, metavar='PATH',
                        help='write the state file\'s findings out as an allowlist baseline and '
                             'exit; reads the state file only, so no Synapse credentials needed')
    parser.add_argument('--baseline-expires', default=None, metavar='YYYY-MM-DD',
                        help=f'expiry for --emit-allowlist entries (default: {BASELINE_TTL_DAYS} '
                             'days from today)')
    parser.add_argument('--drill-down', action='store_true',
                        help='resolve affected projects to individual entities (read-only)')
    parser.add_argument('--drill-down-limit', type=int, default=None,
                        help='stop after walking N entities per project')
    parser.add_argument('--drill-down-workers', type=int, default=8,
                        help='parallel entity reads during drill-down (read-only)')
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

    if args.report_only or args.emit_allowlist:
        audits = list(load_state(state_path).values())
        if not audits:
            LOG.error('no state found at %s; nothing to report', state_path)
            return 1
        if args.emit_allowlist:
            return emit_allowlist(audits, Path(args.emit_allowlist), state_path=state_path,
                                  expires=args.baseline_expires)
        # Every audit here was read by an earlier run, so the coverage figures say so.
        write_reports(audits, out_dir, carried_forward=len(audits))
        print(format_markdown(audits, carried_forward=len(audits)))
        return exit_code_for(audits, fail_on_findings=args.fail_on_findings,
                             max_unscanned=args.max_unscanned,
                             fail_on_unknown=args.fail_on_unknown,
                             allowlist=allowlist)

    syn = login(pool_size=max(args.workers, args.drill_down_workers, 10))

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
    audits = carry_forward(existing, (p['project_id'] for p in projects))
    carried_forward = len(audits)

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
        out_dir.mkdir(parents=True, exist_ok=True)
        drilled = run_drill_down(
            syn, audits, out_dir, canon=canon, index=index,
            loose_compare=args.loose_compare, limit=args.drill_down_limit,
            workers=args.drill_down_workers,
            include_project_entity=args.include_project_entity,
            max_retries=args.max_retries,
        )
        # Each project's state line was written before its drill-down, so re-append
        # every project the drill-down touched now that its entity reads have
        # settled. load_state keys by project and the later line wins, so
        # --report-only over this state file reads back the same coverage this run
        # reported, gaps included.
        for audit in drilled:
            append_state(state_path, audit)
        lost = sum(len(a.read_failures) for a in audits)
        if lost:
            LOG.error('%d recorded coverage gaps - this run\'s, plus any carried forward from '
                      'the state file - so the findings file is incomplete; the reports and '
                      'its manifest list them', lost)

    write_reports(audits, out_dir, carried_forward=carried_forward)
    print(format_markdown(audits, carried_forward=carried_forward))
    LOG.info('reports written to %s', out_dir)
    return exit_code_for(audits, fail_on_findings=args.fail_on_findings,
                         max_unscanned=args.max_unscanned,
                         fail_on_unknown=args.fail_on_unknown,
                         allowlist=allowlist)


if __name__ == '__main__':
    sys.exit(main())
