"""Portable receipts for content actually observed through a browser session."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator

from insight.domain.contracts import Contract, Digest, Id, Nonempty, public_url


class ObservedPost(Contract):
    url: Nonempty
    author_handle: Annotated[str, Field(pattern=r"^[A-Za-z0-9_]{1,15}$")]
    text: Annotated[str, Field(min_length=1, max_length=100000, pattern=r"\S")]
    published_at: Nonempty
    expanded: bool
    truncated: bool
    linked_urls: tuple[str, ...] = ()

    @model_validator(mode="after")
    def identity_and_time(self) -> ObservedPost:
        import re

        uri = urlparse(public_url(self.url))
        match = re.fullmatch(r"/([A-Za-z0-9_]{1,15})/status/([0-9]{1,20})/?", uri.path)
        if (
            uri.hostname not in ("x.com", "www.x.com", "twitter.com", "www.twitter.com")
            or not match
            or match[1].casefold() != self.author_handle.casefold()
        ):
            raise ValueError("Observed post URL must match its author and permanent status ID")
        if datetime.fromisoformat(self.published_at.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Post timestamp needs an explicit timezone")
        for link in self.linked_urls:
            public_url(link)
        return self


class CaptionSegment(Contract):
    start: Annotated[float, Field(ge=0)]
    duration: Annotated[float, Field(gt=0)]
    text: Nonempty


class ObservedArticle(Contract):
    title: Nonempty
    text: Annotated[str, Field(min_length=1, max_length=500000, pattern=r"\S")]
    expanded: bool
    truncated: bool
    published_at: str | None = None


class BrowserCaptureBundle(Contract):
    resource_url: Nonempty
    observed_at: Nonempty
    observer: Nonempty
    capture_method: Literal["visible_browser_ui"]
    scope: Literal["public_post_sample", "video_caption_track", "public_article"]
    public_content_only: Literal[True]
    posts: tuple[ObservedPost, ...] = ()
    segments: tuple[CaptionSegment, ...] = ()
    article: ObservedArticle | None = None
    language: Nonempty | None = None
    generated_captions: bool | None = None
    limitations: Annotated[tuple[Nonempty, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def bounded_scope(self) -> BrowserCaptureBundle:
        uri = urlparse(public_url(self.resource_url))
        if datetime.fromisoformat(self.observed_at.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Observation time needs an explicit timezone")
        if self.scope == "public_post_sample":
            if (
                not self.posts
                or self.segments
                or uri.hostname not in ("x.com", "www.x.com", "twitter.com", "www.twitter.com")
            ):
                raise ValueError("X capture must contain observed public posts only")
            expected_author = uri.path.strip("/").split("/")[0]
            if any(p.author_handle.casefold() != expected_author.casefold() for p in self.posts):
                raise ValueError("Capture cannot mix posts from unrelated account timelines")
            if len({p.url for p in self.posts}) != len(self.posts):
                raise ValueError("Duplicate observed post")
        elif self.scope == "public_article":
            if self.article is None or self.posts or self.segments:
                raise ValueError("Article capture must contain one visible article only")
        elif (
            not self.segments
            or self.posts
            or self.language is None
            or uri.hostname not in ("youtube.com", "www.youtube.com")
            or uri.path != "/watch"
        ):
            raise ValueError("Caption capture requires one watch page, timed segments and language")
        if any(a.start > b.start for a, b in zip(self.segments, self.segments[1:], strict=False)):
            raise ValueError("Caption segments must follow the observed timeline")
        return self


class CaptureAttachmentInput(Contract):
    native_path: Nonempty
    sha256: Digest
    media_type: Literal["image/png", "text/plain", "application/json"]
    kind: Literal["browser_screenshot", "transcript_export"]


class BrowserImportRequest(Contract):
    source_id: Id
    native_path: Nonempty
    sha256: Digest
    publisher: Nonempty
    provenance: Nonempty
    attachments: tuple[CaptureAttachmentInput, ...] = ()
