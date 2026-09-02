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
from dataclasses import dataclass
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

    @property
    def typed(self) -> dict:
        """The /annotations2 wire form of this record."""
        return encode_annotations(self.values, self.types)


def decode_annotations(payload: dict) -> AnnotationRecord:
    values: dict[str, list] = {}
    types: dict[str, str] = {}
    for key, entry in (payload.get('annotations') or {}).items():
        declared = entry.get('type', 'STRING')
        decoder = VALUE_DECODERS.get(declared, str)
        decoded = []
        for raw in entry.get('value') or []:
            try:
                decoded.append(decoder(raw))
            except (TypeError, ValueError):
                # Keep the raw string rather than dropping a value we cannot
                # parse; a mis-typed annotation is data to report, not to lose.
                decoded.append(raw)
        values[key] = decoded
        types[key] = declared
    return AnnotationRecord(payload['id'], payload['etag'], values, types)


def encode_annotations(values: dict[str, list], types: dict[str, str]) -> dict:
    """Wire form, preserving each key's original declared type.

    Types are never re-inferred: a key this run did not touch must round-trip
    byte for byte, or the verification pass cannot prove nothing else changed.
    """
    encoded = {}
    for key, value in values.items():
        items = value if isinstance(value, list) else [value]
        declared = types.get(key) or _infer_value_type(items)
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
