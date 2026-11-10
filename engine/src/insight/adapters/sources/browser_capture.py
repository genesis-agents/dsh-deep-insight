"""Read only explicitly imported browser receipts; never borrow session cookies."""

import hashlib
from datetime import datetime
from typing import Any

from insight.domain.captures import BrowserCaptureBundle
from insight.domain.contracts import GoalResult, Observation, PlatformError, Source, SourcePlanItem
from insight.domain.rules import canonical
from insight.ports.sources import AcquiredDocument, Acquisition, Budget
from insight.ports.storage import BlobStore


class BrowserCaptureProvider:
    def __init__(self, blobs: BlobStore, maximum_bytes: int) -> None:
        self.blobs, self.maximum_bytes = blobs, maximum_bytes

    def capabilities(self) -> tuple[str, ...]:
        return ("observed_posts", "video_transcript", "document_text")

    def probe(self, source: Source) -> dict[str, str]:
        return dict(
            state="imported_receipt_available" if source.capture_uri else "capture_required",
            completeness="browser_visible_sample_only; no_API_watermark",
        )

    def discover(self, source: Source, item: SourcePlanItem, budget: Budget) -> tuple[str, ...]:
        return (source.resource_uri,)

    def acquire(
        self,
        source: Source,
        item: SourcePlanItem,
        budget: Budget,
        checkpoint: dict[str, str | int | bool | None],
    ) -> Acquisition:
        if not source.capture_uri:
            raise PlatformError(
                "INPUT_REQUIRED", "Import a browser observation receipt before acquiring it"
            )
        data, _ = self.blobs.read_inbox(source.capture_uri, self.maximum_bytes)
        digest = hashlib.sha256(data).hexdigest()
        if source.canonical_identity != "browser-capture:" + digest:
            raise PlatformError("EVIDENCE_INVALID", "Staged browser receipt changed")
        receipt = BrowserCaptureBundle.model_validate_json(data)
        if receipt.resource_url != source.resource_uri:
            raise PlatformError("EVIDENCE_INVALID", "Browser receipt refers to another page")
        documents = [
            AcquiredDocument(data, "application/json", "source_metadata", receipt.resource_url)
        ]
        complete = True
        if (
            item.goal == "document_text"
            and receipt.scope == "public_article"
            and receipt.article
            and "raw_document" in item.accepted_material_roles
        ):
            article = receipt.article
            documents.append(
                AcquiredDocument(
                    article.text.encode(),
                    "text/plain",
                    "raw_document",
                    receipt.resource_url,
                    article.published_at,
                )
            )
            complete = (
                article.expanded
                and not article.truncated
                and len(article.text) >= (item.minimum_text_characters or 400)
            )
            detail = "Visible browser article text archived; not a downloaded HTML/PDF original or whole-site coverage"
        elif (
            item.goal == "observed_posts"
            and receipt.scope == "public_post_sample"
            and "post" in item.accepted_material_roles
        ):
            for post in receipt.posts:
                created = datetime.fromisoformat(post.published_at.replace("Z", "+00:00"))
                end = datetime.fromisoformat(item.requested_window.end.replace("Z", "+00:00"))
                start = (
                    datetime.fromisoformat(item.requested_window.start.replace("Z", "+00:00"))
                    if item.requested_window.start
                    else None
                )
                if (
                    end.tzinfo is None
                    or (start and start.tzinfo is None)
                    or created >= end
                    or (start and created < start)
                ):
                    raise PlatformError(
                        "WINDOW_MISMATCH", "Observed post is outside the declared sample window"
                    )
                documents.append(
                    AcquiredDocument(
                        canonical(post), "application/json", "post", post.url, post.published_at
                    )
                )
                complete = complete and post.expanded and not post.truncated
            detail = "Observed browser post samples; account history, API windows, attachments and unread threads are not claimed"
        elif (
            item.goal == "video_transcript"
            and receipt.scope == "video_caption_track"
            and "transcript" in item.accepted_material_roles
        ):
            payload: dict[str, Any] = dict(
                schema="youtube-transcript@1",
                language=receipt.language,
                is_generated=receipt.generated_captions,
                segments=[
                    s.model_dump(mode="json", exclude={"schema_version"}) for s in receipt.segments
                ],
                retrieval="visible_browser_caption_export",
            )
            documents.append(
                AcquiredDocument(
                    canonical(payload), "application/json", "transcript", receipt.resource_url
                )
            )
            detail = "Browser-observed timed captions; full audiovisual review and speech accuracy remain separate"
        else:
            raise PlatformError(
                "UNSUPPORTED_CAPABILITY",
                "Browser receipts supply observed_posts or timed captions; never latest_posts API completeness",
            )
        for attachment in source.capture_attachments or ():
            content, _ = self.blobs.read_inbox(attachment.uri, self.maximum_bytes)
            if hashlib.sha256(content).hexdigest() != attachment.sha256:
                raise PlatformError("EVIDENCE_INVALID", "Staged browser capture attachment changed")
            documents.append(
                AcquiredDocument(
                    content, attachment.media_type, "browser_capture", receipt.resource_url
                )
            )
        budget.consume("source_bytes", sum(len(d.data) for d in documents))
        return Acquisition(
            tuple(documents),
            Observation(
                source_id=source.source_id,
                requested_window=item.requested_window,
                observed_window=None,
                pagination_complete=False,
                goal_result=GoalResult(
                    state="met" if complete else "not_met",
                    reason_code="BROWSER_SAMPLE_ACQUIRED"
                    if complete
                    else "TRUNCATED_BROWSER_SAMPLE",
                    detail=detail,
                ),
                coverage_notes=receipt.limitations
                + (
                    "Observed at: " + receipt.observed_at,
                    "Does not advance or certify an API account-window watermark",
                ),
            ),
        )
