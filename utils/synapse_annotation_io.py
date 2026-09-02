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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

LOG = logging.getLogger('synapse_annotation_io')

#: HTTP statuses worth trying again. A 403 is deliberately absent: an
#: authorisation failure does not become a success on the second attempt, and
#: retrying it just delays a finding.
RETRYABLE_STATUS = (429, 500, 502, 503, 504)

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


def is_forbidden(error: Exception) -> bool:
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    return status in (401, 403) or 'Forbidden' in str(error) or '403' in str(error)[:8]


_TRANSPORT_ERRORS: tuple[type[BaseException], ...] | None = None


def transport_error_types() -> tuple[type[BaseException], ...]:
    """Exception classes that mean the request never got an HTTP answer.

    ``requests.exceptions.ConnectionError`` and ``requests.exceptions.Timeout``
    derive from ``RequestException`` -> ``OSError``, *not* from the builtins of
    the same name, and they carry no ``response`` - so neither a status check nor
    an ``isinstance`` against the builtins ever matches a dropped connection or a
    read timeout, which are the most common transient failures in a multi-hour
    scan. ``requests`` is resolved on first use rather than imported at module
    scope, so this module stays importable without the Synapse client stack.
    """
    global _TRANSPORT_ERRORS
    if _TRANSPORT_ERRORS is None:
        types: list[type[BaseException]] = [TimeoutError, ConnectionError]
        try:
            from requests.exceptions import ConnectionError as RequestsConnectionError
            from requests.exceptions import Timeout as RequestsTimeout
        except ImportError:  # pragma: no cover - requests ships with synapseclient
            pass
        else:
            types += [RequestsConnectionError, RequestsTimeout]
        _TRANSPORT_ERRORS = tuple(types)
    return _TRANSPORT_ERRORS


def is_retryable(error: Exception) -> bool:
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    if status is not None:
        # A definite HTTP verdict outside the retryable set - a 404, a 400 - is
        # not going to be a different verdict on the second attempt.
        return status in RETRYABLE_STATUS
    return isinstance(error, transport_error_types())


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
