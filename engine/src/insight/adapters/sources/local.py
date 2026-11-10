from __future__ import annotations

from pathlib import PurePosixPath

from insight.adapters.transforms.speech import LocalSpeechRuntime
from insight.adapters.transforms.text import sniff_type
from insight.domain.contracts import GoalResult, Observation, PlatformError, Source, SourcePlanItem
from insight.domain.rules import canonical
from insight.ports.sources import AcquiredDocument, Acquisition, Budget
from insight.ports.storage import BlobStore


class LocalFileProvider:
    def __init__(
        self, blobs: BlobStore, maximum_bytes: int, speech: LocalSpeechRuntime | None = None
    ) -> None:
        self.blobs, self.maximum_bytes = blobs, maximum_bytes
        self.speech = speech

    def capabilities(self) -> tuple[str, ...]:
        return (
            "document_text",
            "slides_only",
            "editable_original_pptx",
            "video_transcript:local_ASR",
        )

    def probe(self, source: Source) -> dict[str, str]:
        data, media = self.blobs.read_inbox(source.resource_uri, self.maximum_bytes)
        return {"state": "accessible", "media_type": media, "size": str(len(data))}

    def discover(self, source: Source, item: SourcePlanItem, budget: Budget) -> tuple[str, ...]:
        return (source.resource_uri,)

    def acquire(
        self,
        source: Source,
        item: SourcePlanItem,
        budget: Budget,
        checkpoint: dict[str, str | int | bool | None],
    ) -> Acquisition:
        data, media = self.blobs.read_inbox(source.resource_uri, self.maximum_bytes)
        budget.consume("source_bytes", len(data))
        media = sniff_type(data, media)
        role = source.declared_material_role or "raw_document"
        if (
            item.goal == "video_transcript"
            and role in ("raw_audio", "raw_video")
            and "transcript" in item.accepted_material_roles
        ):
            if not self.speech or not item.media:
                raise PlatformError(
                    "DEPENDENCY_REQUIRED",
                    "Local media transcription needs explicit MediaOptions and configured ASR runtime",
                )
            try:
                budget.consume("media_model_calls", 1)
                transcript = self.speech.transcribe(
                    data, PurePosixPath(source.resource_uri).suffix, item.media
                )
            except PlatformError as exc:
                return Acquisition(
                    (AcquiredDocument(data, media, role, source.resource_uri),),
                    Observation(
                        source_id=source.source_id,
                        requested_window=item.requested_window,
                        goal_result=GoalResult(
                            state="not_met", reason_code=exc.code, detail=exc.detail
                        ),
                        coverage_notes=(
                            "Original media retained; no generated transcript was published",
                        ),
                    ),
                )
            return Acquisition(
                (
                    AcquiredDocument(data, media, role, source.resource_uri),
                    AcquiredDocument(
                        canonical(transcript), "application/json", "transcript", source.resource_uri
                    ),
                ),
                Observation(
                    source_id=source.source_id,
                    requested_window=item.requested_window,
                    goal_result=GoalResult(
                        state="met",
                        reason_code="LOCAL_ASR_ACQUIRED",
                        detail="Locally generated timed transcription; not author captions, verified numbers or a complete audiovisual analysis",
                    ),
                    coverage_notes=(
                        "Local int8 CPU model; model hash and engine version are retained",
                        "ASR names, numbers, punctuation and timestamps require review against the archived source",
                    ),
                ),
            )
        supported = item.goal == "document_text" and "raw_document" in item.accepted_material_roles
        if role == "original_slides" and item.goal in ("slides_only", "editable_original_pptx"):
            if media not in (
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ):
                raise PlatformError(
                    "INVALID_MATERIAL", "Declared original slides must actually be PDF/PPTX"
                )
            supported = "original_slides" in item.accepted_material_roles and (
                item.goal == "slides_only" or "presentationml" in media
            )
        result = GoalResult(
            state="met" if supported else "not_met",
            reason_code="FILE_READ" if supported else "UNSUPPORTED_GOAL",
            detail="User-provided file acquired; publisher authenticity is not inferred"
            if supported
            else "Local adapter supports document_text/raw_document only",
        )
        return Acquisition(
            documents=(AcquiredDocument(data, media, role, source.resource_uri),)
            if supported
            else (),
            observation=Observation(
                source_id=source.source_id,
                goal_result=result,
                requested_window=item.requested_window,
                observed_window=item.requested_window if supported else None,
                pagination_complete=supported,
                coverage_notes=("File import does not authenticate the original author's claims",),
            ),
        )
