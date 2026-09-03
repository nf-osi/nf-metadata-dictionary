#!/usr/bin/env python3
"""
Read and write Synapse entity annotations through the stable REST surface.

Takes an already-authenticated ``synapseclient.Synapse`` as an argument and
imports nothing from it, so this module is importable without synapseclient.

Uses ``/entity/{id}/annotations2`` rather than ``syn.get_annotations`` /
``syn.set_annotations`` / ``synapseclient.Annotations``, which are deprecated for
removal in synapseclient 5.0. The REST payload also carries each key's declared
value type, which the annotation-key tooling needs: the whole point of the
``type_coercion`` verdict is that ``IndividualID`` is stored as a LONG while
``individualID`` is a STRING.
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

LOG = logging.getLogger('synapse_annotation_io')

#: HTTP statuses worth trying again. A 403 is deliberately absent: an
#: authorisation failure does not become a success on the second attempt, and
#: retrying it just delays a finding.
RETRYABLE_STATUS = (429, 500, 502, 503, 504)

#: Statuses that answer a question about one entity, and would answer it the same
#: way however many times it is asked: a 403 on a file behind its own ACL, a 404 or
#: a 410 on one deleted between the audit and the fix. These are data - see
#: :func:`breaker_verdict`.
#:
#: Enumerated rather than "any status that is not retryable", which swept in the two
#: failures a run cannot survive. A 401 is not a fact about an entity but about the
#: credential, and a 400 says this tool is building a request the service will keep
#: rejecting; both recur on every subsequent call, so a run-wide failure of either
#: kind has to reach the circuit breaker. Because every request then fails, the
#: guard trips as soon as its floor is met - within ten requests of a token being
#: revoked mid-scan - rather than grinding through thousands of entities.
DEFINITIVE_STATUS = (403, 404, 410)

#: Synapse AnnotationsValueType -> the Python type the policy rules compare.
VALUE_DECODERS = {
    'STRING': str,
    'DOUBLE': float,
    'LONG': int,
    'TIMESTAMP_MS': int,
    'BOOLEAN': lambda v: str(v).strip().lower() in ('true', '1', 'yes'),
}

#: AnnotationsValueType -> the entity-view ColumnType the same annotation
#: surfaces as. The two are different vocabularies: a view reports ``LONG`` as
#: ``INTEGER`` and ``TIMESTAMP_MS`` as ``DATE``, and never uses either name, so
#: comparing an annotation type against a column type directly invents
#: conflicts that do not exist.
COLUMN_TYPE_FOR_VALUE_TYPE = {
    'STRING': 'STRING',
    'DOUBLE': 'DOUBLE',
    'BOOLEAN': 'BOOLEAN',
    'LONG': 'INTEGER',
    'TIMESTAMP_MS': 'DATE',
}

#: A multi-value annotation surfaces as the matching list column. ColumnType has
#: no ``DOUBLE_LIST``, so a multi-value DOUBLE lands in ``STRING_LIST``.
LIST_COLUMN_TYPE_FOR_VALUE_TYPE = {
    'STRING': 'STRING_LIST',
    'DOUBLE': 'STRING_LIST',
    'BOOLEAN': 'BOOLEAN_LIST',
    'LONG': 'INTEGER_LIST',
    'TIMESTAMP_MS': 'DATE_LIST',
}


def column_type_for(declared: str, value_count: int) -> str:
    """The entity-view ColumnType an annotation of this type and arity becomes."""
    if value_count > 1:
        return LIST_COLUMN_TYPE_FOR_VALUE_TYPE.get(declared, 'STRING_LIST')
    return COLUMN_TYPE_FOR_VALUE_TYPE.get(declared, 'STRING')


@dataclass(frozen=True)
class AnnotationRecord:
    entity_id: str
    etag: str
    #: key -> decoded Python values, the shape the policy rules operate on
    values: dict[str, list]
    #: key -> declared Synapse value type, preserved verbatim on write
    types: dict[str, str]
    #: key -> the value strings exactly as Synapse served them, so an untouched
    #: key can be re-emitted without going through the decoder at all
    raw: dict[str, list] = field(default_factory=dict)

    @property
    def typed(self) -> dict:
        """The /annotations2 wire form of this record."""
        return encode_annotations(self.values, self.types, self.raw)


def _decode_values(raw_values, declared: str) -> list:
    decoder = VALUE_DECODERS.get(declared, str)
    decoded = []
    for raw in raw_values or []:
        try:
            decoded.append(decoder(raw))
        except (TypeError, ValueError):
            # Keep the raw string rather than dropping a value we cannot parse;
            # a mis-typed annotation is data to report, not to lose.
            decoded.append(raw)
    return decoded


def decode_annotations(payload: dict) -> AnnotationRecord:
    values: dict[str, list] = {}
    types: dict[str, str] = {}
    raw: dict[str, list] = {}
    for key, entry in (payload.get('annotations') or {}).items():
        declared = entry.get('type', 'STRING')
        raw[key] = list(entry.get('value') or [])
        values[key] = _decode_values(raw[key], declared)
        types[key] = declared
    return AnnotationRecord(payload['id'], payload['etag'], values, types, raw)


def encode_annotations(
    values: dict[str, list],
    types: dict[str, str],
    raw: dict[str, list] | None = None,
) -> dict:
    """Wire form, preserving each key's original declared type.

    Types are never re-inferred: a key this run did not touch must round-trip
    byte for byte, or the verification pass cannot prove nothing else changed.

    Decoding is lossy in the textual direction - a DOUBLE stored as ``"1.50"``
    decodes to ``1.5`` and re-encodes to ``"1.5"``, ``"1e6"`` becomes
    ``"1000000.0"`` - and ``verify_run`` compares decoded values, so it could
    never catch that. ``raw`` closes the gap: when a key's value still decodes to
    exactly what is being written, the original strings go back out untouched.
    Callers supply ``raw`` under the key each value is being written to, so a
    renamed key carries its original representation to its new name and only a
    genuinely changed value is re-encoded.
    """
    raw = raw or {}
    encoded = {}
    for key, value in values.items():
        items = value if isinstance(value, list) else [value]
        declared = types.get(key) or _infer_value_type(items)
        original = raw.get(key)
        if original is not None and _decode_values(original, declared) == list(items):
            encoded[key] = {'type': declared, 'value': list(original)}
            continue
        encoded[key] = {
            'type': declared,
            'value': [_encode_scalar(item, declared) for item in items],
        }
    return encoded


def _infer_value_type(items: Sequence[Any]) -> str:
    if not items:
        return 'STRING'
    first = items[0]
    if isinstance(first, bool):
        return 'BOOLEAN'
    if isinstance(first, int):
        return 'LONG'
    if isinstance(first, float):
        return 'DOUBLE'
    return 'STRING'


def _encode_scalar(value: Any, declared: str) -> str:
    if declared == 'BOOLEAN':
        return 'true' if bool(value) else 'false'
    return str(value)


def status_of(error: Exception) -> int | None:
    """The HTTP status behind an exception, when it carries a response at all."""
    return getattr(getattr(error, 'response', None), 'status_code', None)


def _reads_as_forbidden(error: Exception) -> bool:
    """Whether an exception with no response still reads as an authorisation refusal."""
    return 'Forbidden' in str(error) or '403' in str(error)[:8]


def is_forbidden(error: Exception) -> bool:
    """An authorisation refusal, which no number of retries turns into a yes."""
    status = status_of(error)
    if status is not None:
        return status in (401, 403)
    return _reads_as_forbidden(error)


_TRANSPORT_ERRORS: tuple[type[BaseException], ...] | None = None


def transport_error_types() -> tuple[type[BaseException], ...]:
    """Exception classes that mean the request never got an HTTP answer.

    ``requests.exceptions.ConnectionError`` and ``requests.exceptions.Timeout``
    derive from ``RequestException`` -> ``OSError``, *not* from the builtins of
    the same name, and they carry no ``response`` - so neither a status check nor
    an ``isinstance`` against the builtins ever matches a dropped connection or a
    read timeout, which are the most common transient failures in a multi-hour
    scan. ``ChunkedEncodingError`` (a connection dropped mid-response) and
    ``RetryError`` (urllib3's own budget exhausted) sit in the same gap.
    ``requests`` is resolved on first use rather than imported at module scope, so
    this module stays importable without the Synapse client stack.

    Deliberately not ``RequestException`` itself: that would sweep in
    ``MissingSchema`` and ``InvalidURL``, which are programming errors and would
    be retried three times for nothing.
    """
    global _TRANSPORT_ERRORS
    if _TRANSPORT_ERRORS is None:
        types: list[type[BaseException]] = [TimeoutError, ConnectionError]
        try:
            from requests.exceptions import ChunkedEncodingError, RetryError
            from requests.exceptions import ConnectionError as RequestsConnectionError
            from requests.exceptions import Timeout as RequestsTimeout
        except ImportError:  # pragma: no cover - requests ships with synapseclient
            pass
        else:
            types += [RequestsConnectionError, RequestsTimeout,
                      ChunkedEncodingError, RetryError]
        _TRANSPORT_ERRORS = tuple(types)
    return _TRANSPORT_ERRORS


def is_retryable(error: Exception) -> bool:
    status = status_of(error)
    if status is not None:
        # A definite HTTP verdict outside the retryable set - a 404, a 400 - is
        # not going to be a different verdict on the second attempt.
        return status in RETRYABLE_STATUS
    return isinstance(error, transport_error_types())


def is_definitive(error: Exception) -> bool:
    """Whether the service answered about one entity, and would answer the same again.

    True only for :data:`DEFINITIVE_STATUS`: a 403 on a file behind a per-folder ACL,
    and a 404 or 410 on an entity deleted between the audit and the fix, are facts
    about those entities rather than signs that Synapse is unwell. Everything else -
    a 429 or 5xx, a 401 on a credential that has stopped working, a 400 on a request
    this tool will keep building the same way, a dropped connection, an exception this
    module cannot classify at all - is treated as a possible run-wide problem, so an
    unrecognised systemic failure still stops a run rather than being waved through as
    data about one entity.
    """
    status = status_of(error)
    if status is not None:
        return status in DEFINITIVE_STATUS
    # No response to read - a client that did not attach one, or a stub. A 403 is
    # still recognisable from the message; nothing else is, so nothing else is
    # excused from the guard.
    return _reads_as_forbidden(error)


def breaker_verdict(error: Exception | None) -> bool | None:
    """How one request's outcome is sampled into a :class:`CircuitBreaker`.

    ``False`` for a request that succeeded, ``True`` for one lost to a possible
    service problem, and ``None`` - not sampled at all - for a per-entity verdict the
    service answered definitively.

    Sampling a definitive verdict made the guard fire on the data rather than on an
    outage. With ``ERROR_FLOOR`` at 10 and the threshold at 10%, two 403s inside one
    window abort a whole pass, and the abort is deterministic: re-running produces
    the identical abort, so the only way forward is to prune the input by hand. A run
    that meets a handful of entities the caller cannot see, or that were deleted
    since the audit, records them as the coverage gaps they already are and carries
    on. Neither is retried either, so neither costs the wall clock the guard exists
    to protect.

    Only :data:`DEFINITIVE_STATUS` earns that exemption, and deliberately not "any
    status that is not retryable": a 401 says the credential is finished and a 400
    says the request shape is wrong, and both of those fail every remaining call, so
    excusing them let an expired token grind through a whole plan with the guard
    sampling nothing at all.
    """
    if error is None:
        return False
    return None if is_definitive(error) else True


def with_retries(call, *, max_retries: int, label: str, logger: logging.Logger | None = None):
    """Retry transient REST failures with jittered backoff. Never retries a 403.

    Lives here rather than in one script so the audit and the fix tool share a
    single policy: a rate limit must not be survivable on one code path and fatal
    on another.
    """
    logger = logger or LOG
    delay = 2.0
    for attempt in range(max_retries + 1):
        try:
            return call()
        except Exception as error:  # noqa: BLE001
            if is_forbidden(error) or not is_retryable(error) or attempt == max_retries:
                raise
            sleep_for = delay + random.uniform(0, delay / 2)
            logger.info('%s: retry %d/%d after %.1fs (%s)', label, attempt + 1, max_retries,
                        sleep_for, type(error).__name__)
            time.sleep(sleep_for)
            delay = min(delay * 2, 30.0)
    raise AssertionError('unreachable')


#: Abort once more than this fraction of the most recent requests have failed. The
#: rate is measured over a trailing window rather than the whole run, so a healthy
#: prefix cannot dilute the signal: a run that degrades at entity 2,000 stops
#: there rather than waiting for the cumulative rate to catch up.
ERROR_RATE_THRESHOLD = 0.10
#: How many of the most recent requests the rate is measured over.
ERROR_SAMPLE = 50
#: Fewest results the rate is judged on, so a run shorter than the full window is
#: guarded too. Below this a single failure would be enough to clear the
#: threshold on its own, which would abort a three-entity run spuriously.
ERROR_FLOOR = 10


class CircuitBreaker:
    """Trailing-window failure rate, tripped by a systemic problem.

    A service degradation should stop a per-entity loop where the trouble starts,
    whether that is at entity 10 or at entity 2,000. Hence the trailing window,
    judged as soon as ``floor`` results
    are in rather than once it is full: the whole-run rate would take hundreds more
    failures to clear the threshold after a long healthy prefix, and waiting for a
    full window would leave every run shorter than it unguarded - which is exactly
    the scale a curator drives by hand.

    Lives beside ``with_retries`` for the same reason: retries make an unguarded
    loop worse rather than better, since each entity of a doomed run pays the full
    jittered backoff before failing, which turns seconds into days. Every
    per-entity network loop in the audit and the fix tool is guarded by this one
    implementation so a guard cannot be added to one loop and forgotten on its
    sibling.

    The window holds one sample per *request*, never one per iteration: work that
    issued no network call says nothing about the health of the service. Nor does a
    request the service answered definitively - see :func:`breaker_verdict` - so a
    403 or a 404 is recorded as lost coverage without touching the window.

    A trip is a latch: once the rate has been over the threshold the breaker stays
    tripped for the rest of the run. The rate itself is a live trailing figure, so
    it recovers as soon as enough successes push the failures back out of the
    window - 50 successes then 6 failures trips it, and 45 further successes leave
    5 in 50, which is not *over* 10%. Callers ask ``tripped`` after the fact to
    learn whether the pass they just ran was cut short, so a recovering rate meant
    an abort could be forgotten by the time it was read: the walk stopped, the
    caller saw ``tripped`` False, and a truncated drill-down was stamped complete.
    """

    def __init__(self, *, sample: int = ERROR_SAMPLE, floor: int = ERROR_FLOOR,
                 threshold: float = ERROR_RATE_THRESHOLD):
        self.threshold = threshold
        self.floor = min(sample, floor)
        self.recent: deque[bool] = deque(maxlen=sample)
        self._tripped = False

    def record(self, failed: bool) -> None:
        self.recent.append(bool(failed))
        if self.window >= self.floor and self.failures / self.window > self.threshold:
            self._tripped = True

    def sample(self, verdicts: Iterable[bool | None]) -> bool:
        """Record verdicts in order, stopping at the one that trips the breaker.

        ``None`` means the item issued no request and is not sampled at all, which
        is what keeps work that asked the service for nothing from diluting the
        window. Returns True once the trailing rate is over the threshold, so a
        batched caller - the audit's threaded drill-down reads a chunk at a time -
        can stop at the end of the batch that tripped it.
        """
        for verdict in verdicts:
            if verdict is None:
                continue
            self.record(verdict)
            if self.tripped:
                return True
        return False

    @property
    def failures(self) -> int:
        return sum(self.recent)

    @property
    def window(self) -> int:
        return len(self.recent)

    @property
    def tripped(self) -> bool:
        """Whether the failure rate has been over the threshold at any point."""
        return self._tripped


def run_guarded(
    items: Sequence,
    step,
    *,
    failed,
    label: str,
    logger: logging.Logger | None = None,
) -> tuple[list, bool]:
    """Apply ``step`` to each item, stopping the moment the breaker trips.

    Every sequential per-entity loop that issues network calls runs through here,
    so a systemic failure stops the run where it starts rather than grinding
    through thousands of entities in any one of them.

    ``failed`` returns True or False for an item that issued a request the service
    may have failed, and None for one the window must not see at all - an item that
    made no network call, or one the service answered definitively. Only requests
    are sampled, because the breaker is measuring the service rather than the loop:
    an item that asked the service for nothing can neither trip it nor dilute it,
    and one it answered with a 403 or a 404 is data rather than a degradation. See
    :func:`breaker_verdict`, which every call site classifies through. Sampling every
    iteration is what let unchanged entities hide an outage - at nine of them per
    planned entity the window sits at 5 failures in 50, exactly the 10% threshold
    and so never above it, while every read the loop actually issued was failing.

    Returns the results collected and whether the run was cut short.
    """
    logger = logger or LOG
    breaker = CircuitBreaker()
    results: list = []
    for position, item in enumerate(items, 1):
        result = step(position, item)
        results.append(result)
        if breaker.sample([failed(result)]):
            logger.error('%s: aborting at entity %d: %d of the last %d requests failed',
                         label, position, breaker.failures, breaker.window)
            return results, True
    return results, False


def read_annotations(syn, entity_id: str, *, max_retries: int = 0) -> AnnotationRecord:
    """Read one entity's annotations, optionally riding out a transient failure.

    ``max_retries`` defaults to 0 because not every caller wants to wait; a
    caller whose failure mode is worse than the delay - anything that would
    otherwise turn one rate-limited read into an aborted run - should pass it.
    """
    def read():
        return decode_annotations(syn.restGET(f'/entity/{entity_id}/annotations2'))

    if not max_retries:
        return read()
    return with_retries(read, max_retries=max_retries, label=entity_id)


def write_annotations(syn, record: AnnotationRecord) -> dict:
    body = json.dumps({
        'id': record.entity_id,
        'etag': record.etag,
        'annotations': record.typed,
    })
    return syn.restPUT(f'/entity/{record.entity_id}/annotations2', body=body)
