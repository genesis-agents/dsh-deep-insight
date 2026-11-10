from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from insight.domain.contracts import (
    ExtractedDocument,
    MaterialRole,
    Observation,
    Source,
    SourcePlanItem,
)


class Budget(Protocol):
    def consume(self, category: str, amount: int) -> None: ...


@dataclass(frozen=True)
class AcquiredDocument:
    data: bytes
    media_type: str
    role: MaterialRole
    origin_uri: str
    published_at: str | None = None


@dataclass(frozen=True)
class Acquisition:
    documents: tuple[AcquiredDocument, ...]
    observation: Observation


class SourceProvider(Protocol):
    def capabilities(self) -> tuple[str, ...]: ...
    def probe(self, source: Source) -> dict[str, str]: ...
    def discover(self, source: Source, item: SourcePlanItem, budget: Budget) -> tuple[str, ...]: ...
    def acquire(
        self,
        source: Source,
        item: SourcePlanItem,
        budget: Budget,
        checkpoint: dict[str, str | int | bool | None],
    ) -> Acquisition: ...


class TextExtractor(Protocol):
    @property
    def processor_ref(self) -> str: ...
    def extract(self, data: bytes, media_type: str, role: MaterialRole) -> ExtractedDocument: ...


class SecretStore(Protocol):
    def get(self, credential_ref: str) -> str | None: ...
