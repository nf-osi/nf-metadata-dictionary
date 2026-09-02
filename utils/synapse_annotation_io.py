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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

#: Synapse AnnotationsValueType -> the Python type the policy rules compare.
VALUE_DECODERS = {
    'STRING': str,
    'DOUBLE': float,
    'LONG': int,
    'TIMESTAMP_MS': int,
    'BOOLEAN': lambda v: str(v).strip().lower() in ('true', '1', 'yes'),
}


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
    Only a key the plan actually named is re-encoded.
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


def read_annotations(syn, entity_id: str) -> AnnotationRecord:
    return decode_annotations(syn.restGET(f'/entity/{entity_id}/annotations2'))


def write_annotations(syn, record: AnnotationRecord) -> dict:
    body = json.dumps({
        'id': record.entity_id,
        'etag': record.etag,
        'annotations': record.typed,
    })
    return syn.restPUT(f'/entity/{record.entity_id}/annotations2', body=body)
