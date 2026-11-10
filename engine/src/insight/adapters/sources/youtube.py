"""Public timed captions and separately bounded media frames; no account cookies or proxy bypass."""

from __future__ import annotations

from importlib.metadata import version
from typing import Any

import requests
from youtube_transcript_api import YouTubeTranscriptApi

from insight.adapters.sources.media import MediaFramesProvider
from insight.adapters.sources.slides import PairedSlidesProvider, video_id
from insight.domain.contracts import (
    GoalResult,
    MediaOptions,
    Observation,
    PlatformError,
    Source,
    SourcePlanItem,
)
from insight.domain.rules import canonical
from insight.ports.sources import AcquiredDocument, Acquisition, Budget


class BudgetSession(requests.Session):
    def __init__(self, budget: Budget, maximum_bytes: int) -> None:
        super().__init__()
        self.budget, self.maximum_bytes = budget, maximum_bytes
        self.caption_payloads: list[bytes] = []

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        self.budget.consume("network_requests", 1)
        kwargs["timeout"] = 25
        kwargs["stream"] = True
        response = super().send(request, **kwargs)
        if response.status_code in (401, 403, 429):
            response.close()
            raise PlatformError(
                "RATE_LIMITED" if response.status_code == 429 else "ACCESS_REQUIRED",
                "YouTube public endpoint denied or rate-limited this request; no bypass attempted",
            )
        data = bytearray()
        try:
            for chunk in response.iter_content(65536):
                if len(data) + len(chunk) > self.maximum_bytes:
                    raise PlatformError("BUDGET_EXCEEDED", "YouTube response exceeds byte limit")
                self.budget.consume("source_bytes", len(chunk))
                data.extend(chunk)
            response._content = bytes(data)
            response.__dict__["_content_consumed"] = True
            if request.url and "/api/timedtext" in request.url and response.status_code == 200:
                self.caption_payloads.append(bytes(data))
            return response
        finally:
            response.close()


def transcript_error(exc: Exception) -> PlatformError:
    name = type(exc).__name__
    if name in ("RequestBlocked", "IpBlocked", "AgeRestricted", "VideoUnplayable"):
        return PlatformError(
            "ACCESS_REQUIRED",
            f"YouTube public captions blocked ({name}); no cookies or rotating proxies were used",
        )
    if name in ("NoTranscriptFound", "TranscriptsDisabled", "VideoUnavailable", "InvalidVideoId"):
        return PlatformError(
            "TRANSCRIPT_UNAVAILABLE",
            f"No readable transcript for requested video/language ({name})",
        )
    return PlatformError(
        "NETWORK_ERROR",
        f"YouTube caption request failed ({name}); private request details were not persisted",
    )


class YouTubeProvider:
    def __init__(
        self,
        slides: PairedSlidesProvider,
        maximum_bytes: int,
        media: MediaFramesProvider | None = None,
    ) -> None:
        self.slides, self.maximum_bytes, self.media = slides, maximum_bytes, media

    def capabilities(self) -> tuple[str, ...]:
        return ("slides_only", "editable_original_pptx", "video_transcript", "video_frames")

    def probe(self, source: Source) -> dict[str, str]:
        if not video_id(source.resource_uri):
            raise PlatformError(
                "INVALID_SPEC", "Register one exact video; channel feeds use the feed provider"
            )
        return dict(
            state="requires_live_acquisition",
            captions="public_caption_tracks",
            media="optional_media_extra_and_ffmpeg",
            transcript_api=version("youtube-transcript-api"),
        )

    def discover(self, source: Source, item: SourcePlanItem, budget: Budget) -> tuple[str, ...]:
        return (
            self.slides.discover(source, item, budget)
            if item.pairing_page
            else (source.resource_uri,)
        )

    def acquire(
        self,
        source: Source,
        item: SourcePlanItem,
        budget: Budget,
        checkpoint: dict[str, str | int | bool | None],
    ) -> Acquisition:
        if item.goal in ("slides_only", "editable_original_pptx"):
            return self.slides.acquire(source, item, budget, checkpoint)
        if item.goal == "video_frames" and self.media:
            return self.media.acquire(source, item, budget, checkpoint)
        if item.goal != "video_transcript" or "transcript" not in item.accepted_material_roles:
            raise PlatformError(
                "UNSUPPORTED_CAPABILITY",
                "Choose original slides, timed transcript or sampled frames explicitly; acquisition alone cannot certify full_talk_analysis",
            )
        ident = video_id(source.resource_uri)
        if not ident:
            raise PlatformError("INVALID_SPEC", "An exact YouTube video URL is required")
        options = item.media or MediaOptions()
        metadata = AcquiredDocument(
            canonical(
                dict(
                    video_id=ident,
                    url=source.resource_uri,
                    requested_languages=list(options.languages),
                    retrieval="youtube-transcript-api",
                    processor_version=version("youtube-transcript-api"),
                )
            ),
            "application/json",
            "source_metadata",
            source.resource_uri,
        )
        try:
            with BudgetSession(budget, min(options.maximum_bytes, self.maximum_bytes)) as session:
                tracks = YouTubeTranscriptApi(http_client=session).list(ident)
                track = (
                    tracks.find_transcript(list(options.languages))
                    if options.allow_generated_captions
                    else tracks.find_manually_created_transcript(list(options.languages))
                )
                fetched = track.fetch()
                segments = fetched.to_raw_data()
                if not segments or not any(s["text"].strip() for s in segments):
                    raise PlatformError("TRANSCRIPT_UNAVAILABLE", "Empty caption track")
                if max(s["start"] + s["duration"] for s in segments) > options.maximum_seconds:
                    raise PlatformError(
                        "BUDGET_EXCEEDED", "Caption timeline exceeds configured media duration"
                    )
                payload = canonical(
                    dict(
                        schema="youtube-transcript@1",
                        video_id=ident,
                        language=fetched.language_code,
                        is_generated=fetched.is_generated,
                        segments=segments,
                        retrieval="public_caption_track; not independent ASR",
                    )
                )
                docs = [
                    metadata,
                    AcquiredDocument(
                        payload, "application/json", "transcript", source.resource_uri
                    ),
                ]
                docs.extend(
                    AcquiredDocument(raw, "application/xml", "source_metadata", source.resource_uri)
                    for raw in session.caption_payloads
                )
        except PlatformError:
            raise
        except Exception as exc:
            failure = transcript_error(exc)
            return Acquisition(
                (metadata,),
                Observation(
                    source_id=source.source_id,
                    requested_window=item.requested_window,
                    goal_result=GoalResult(
                        state="not_met", reason_code=failure.code, detail=failure.detail
                    ),
                ),
            )
        return Acquisition(
            tuple(docs),
            Observation(
                source_id=source.source_id,
                requested_window=item.requested_window,
                observed_window=None,
                pagination_complete=True,
                goal_result=GoalResult(
                    state="met",
                    reason_code="TIMED_CAPTIONS_ACQUIRED",
                    detail="Selected timed caption track archived; no complete audiovisual interpretation or historical availability claimed",
                ),
                coverage_notes=(
                    f"language={fetched.language_code}; auto_generated={fetched.is_generated}",
                    "Caption timestamps are retained; speech accuracy and full video coverage require review",
                    "Charts, slide changes and speech beyond the supplied caption track are not inferred",
                ),
            ),
        )
