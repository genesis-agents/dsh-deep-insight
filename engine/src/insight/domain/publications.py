"""Research-bound imported presentations. Input paths never enter stored records."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from insight.domain.contracts import Attribution, Contract, Digest, Id, Nonempty


class PublicationFileInput(Contract):
    name: Nonempty
    native_path: Nonempty
    sha256: Digest

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if value in (".", "..") or any(c in value for c in '/\\:<>"|?*'):
            raise ValueError("A publication filename must be a single portable component")
        if value.rstrip(" .") != value or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid portable filename")
        if value.split(".")[0].upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise ValueError("Reserved device filename")
        return value


class SlideClaims(Contract):
    slide: Annotated[int, Field(ge=1)]
    claim_ids: tuple[Id, ...]
    note: Nonempty


class SourcePageCoverage(Contract):
    source_version_id: Id
    unit_index: Annotated[int, Field(ge=1)]
    slides: Annotated[tuple[int, ...], Field(min_length=1)]
    claim_ids: Annotated[tuple[Id, ...], Field(min_length=1)]


class PublicationRequest(Contract):
    registration_mode: Literal["research_bound", "unreviewed_intake"] = "research_bound"
    run_id: Id
    basis_fingerprint: Digest
    analysis_fingerprint: Digest
    title: Nonempty
    producer: Attribution
    presentation: PublicationFileInput
    supplements: tuple[PublicationFileInput, ...] = ()
    slides: Annotated[tuple[SlideClaims, ...], Field(min_length=1)]
    source_pages: tuple[SourcePageCoverage, ...] = ()
    limitations: Annotated[tuple[Nonempty, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def distinct_files(self) -> PublicationRequest:
        names = [self.presentation.name, *(f.name for f in self.supplements)]
        if len(set(n.casefold() for n in names)) != len(names):
            raise ValueError("Duplicate publication filename")
        if any(n.casefold() in ("registration.json", "index.html") for n in names):
            raise ValueError("Reserved publication filename")
        pages = [(p.source_version_id, p.unit_index) for p in self.source_pages]
        if len(pages) != len(set(pages)):
            raise ValueError("Duplicate source-page coverage")
        return self


class PublicationFile(Contract):
    name: Nonempty
    artifact_id: Id
    sha256: Digest
    size: int


class PublicationRecord(Contract):
    registration_mode: Literal["research_bound", "unreviewed_intake"]
    publication_id: Id
    project_id: Id
    run_id: Id
    basis_fingerprint: Digest
    analysis_fingerprint: Digest
    title: Nonempty
    producer: Attribution
    presentation: PublicationFile
    supplements: tuple[PublicationFile, ...]
    slides: tuple[SlideClaims, ...]
    source_pages: tuple[SourcePageCoverage, ...]
    claim_fingerprints: dict[str, str]
    limitations: tuple[Nonempty, ...]
    quality_state: Nonempty
    created_at: Nonempty
