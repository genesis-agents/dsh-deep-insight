"""Pure canonicalization, identifiers and evidence invariants."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from insight.domain.contracts import (
    Contract,
    EvidenceInput,
    ExtractedDocument,
    PlatformError,
    TextUnit,
    VisualPageLocator,
)


def canonical(value: Contract | dict[str, Any] | list[Any]) -> bytes:
    data = value.model_dump(mode="json") if isinstance(value, Contract) else value
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def fingerprint(value: Contract | dict[str, Any] | list[Any]) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def stable_id(prefix: str, *values: str) -> str:
    return prefix + "_" + hashlib.sha256(canonical(list(values))).hexdigest()[:32]


def validate_quote(document: ExtractedDocument, evidence: EvidenceInput) -> TextUnit:
    unit = next((u for u in document.units if u.index == evidence.locator.unit_index), None)
    if unit is None or unit.kind == "metadata":
        raise PlatformError("EVIDENCE_INVALID", "Missing text unit or metadata used as content")
    if isinstance(evidence.locator, VisualPageLocator):
        if unit.kind != "page":
            raise PlatformError(
                "EVIDENCE_INVALID", "Visual observation requires an original PDF page"
            )
        return unit
    start, end = evidence.locator.char_start, evidence.locator.char_end
    if end > len(unit.text) or unit.text[start:end] != evidence.quote:
        raise PlatformError("EVIDENCE_INVALID", "Quotation must exactly match the fixed text range")
    return unit
