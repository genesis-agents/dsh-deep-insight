"""Conference/YouTube slide acquisition with explicit page and video pairing."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, parse_qsl, urldefrag, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from insight.adapters.sources.http import PublicHttpClient
from insight.domain.contracts import GoalResult, Observation, PlatformError, Source, SourcePlanItem
from insight.ports.sources import AcquiredDocument, Acquisition, Budget


def video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    candidate = None
    if host in ("youtu.be", "www.youtu.be"):
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in (
        "youtube.com",
        "www.youtube.com",
        "www.youtube-nocookie.com",
        "youtube-nocookie.com",
    ):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/", "/live/")):
            candidate = parsed.path.split("/")[2]
    return candidate if candidate and re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None


def resource_link(url: str) -> str:
    """Ignore only known marketing/share parameters, never a resource identifier."""
    parsed = urlparse(urldefrag(url)[0])
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() != "fbclid"
        and not key.lower().startswith("utm_")
        and not (parsed.hostname == "drive.google.com" and key.lower() == "usp")
    ]
    return parsed._replace(query=urlencode(query)).geturl()


def same_session(page: bytes, base: str, selected: str, expected: str) -> bool:
    soup = BeautifulSoup(page, "html.parser")
    for anchor in soup.find_all("a", href=True):
        if resource_link(urljoin(base, str(anchor["href"]))) != selected:
            continue
        for block in anchor.parents:
            if block.name not in ("p", "li", "tr", "div", "section", "article", "body", "html"):
                continue
            ids = {
                video_id(urljoin(base, str(node.get(attr, ""))))
                for tag, attr in (("a", "href"), ("iframe", "src"))
                for node in block.find_all(tag)
            } - {None}
            if ids == {expected}:
                return True
    return False


class PairedSlidesProvider:
    def __init__(self, client: PublicHttpClient, require_video_pair: bool = False) -> None:
        self.http, self.require_video_pair = client, require_video_pair

    def capabilities(self) -> tuple[str, ...]:
        return ("slides_only", "editable_original_pptx")

    def probe(self, source: Source) -> dict[str, str]:
        return {
            "state": "pairing_plan_required",
            "detail": "Specify the exact session page and requested slide material",
        }

    def _page(
        self, source: Source, item: SourcePlanItem, budget: Budget
    ) -> tuple[bytes, str, dict[str, str]]:
        page_url = item.pairing_page or (None if self.require_video_pair else source.resource_uri)
        if not page_url:
            raise PlatformError(
                "INVALID_SPEC", "YouTube slides require an explicit official pairing page"
            )
        data, media, final = self.http.fetch(page_url, budget)
        if media != "text/html":
            raise PlatformError(
                "PAIRING_INVALID", "Pairing reference must be an actual session page"
            )
        soup = BeautifulSoup(data, "html.parser")
        title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
        if any(s in title for s in ("access denied", "just a moment", "sign in", "log in")):
            raise PlatformError("ACCESS_REQUIRED", "Pairing page is not accessible")
        links = {}
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href")
            if isinstance(href, str):
                links[resource_link(urljoin(final, href))] = anchor.get_text(" ", strip=True)
        if self.require_video_pair:
            expected = video_id(source.resource_uri)
            if not expected:
                raise PlatformError(
                    "INVALID_SPEC", "Specify a single YouTube video, not a channel or search result"
                )
            embeds = [str(frame.get("src", "")) for frame in soup.find_all("iframe")]
            embedded_ids = {video_id(urljoin(final, href)) for href in (*links, *embeds)}
            if expected not in embedded_ids:
                raise PlatformError(
                    "PAIRING_INVALID", "Session page does not link/embed the requested video ID"
                )
        return data, final, links

    def discover(self, source: Source, item: SourcePlanItem, budget: Budget) -> tuple[str, ...]:
        _, _, links = self._page(source, item, budget)
        return tuple(
            url
            for url, label in links.items()
            if re.search(r"slide|投影片|演示稿", url + " " + label, re.I)
        )

    def acquire(
        self,
        source: Source,
        item: SourcePlanItem,
        budget: Budget,
        checkpoint: dict[str, str | int | bool | None],
    ) -> Acquisition:
        if (
            item.goal not in ("slides_only", "editable_original_pptx")
            or "original_slides" not in item.accepted_material_roles
        ):
            raise PlatformError(
                "UNSUPPORTED_CAPABILITY",
                "This adapter acquires paired original slides only; speech and video frames are not enabled",
            )
        page, page_url, links = self._page(source, item, budget)
        selected = (
            resource_link(urljoin(page_url, item.material_url)) if item.material_url else None
        )
        if selected and selected not in links:
            raise PlatformError(
                "PAIRING_INVALID", "Requested material is not linked by this exact session page"
            )
        if not selected:
            candidates = [
                url
                for url, label in links.items()
                if re.search(r"slide|投影片|演示稿", url + " " + label, re.I)
                and (
                    urlparse(url).path.lower().endswith((".pdf", ".pptx"))
                    or (
                        urlparse(url).hostname == "drive.google.com"
                        and "/file/d/" in urlparse(url).path
                    )
                )
            ]
            if len(candidates) != 1:
                raise PlatformError(
                    "PAIRING_AMBIGUOUS",
                    "Specify one linked original slide file; no title-based guessing",
                )
            selected = candidates[0]
        expected = video_id(source.resource_uri) if self.require_video_pair else None
        paired = bool(expected and same_session(page, page_url, selected, expected))
        if expected and not paired:
            raise PlatformError(
                "PAIRING_INVALID", "Material and requested video are not in the same session entry"
            )
        label = links[selected]
        explicit_slides = bool(
            re.search(r"slide|投影片|演示稿|幻灯片", selected + " " + label, re.I)
        )
        catalog_slides = paired and bool(
            re.search(
                r"(?:talks?|presentations?).{0,80}(?:slide decks?|slides)|(?:幻灯片|投影片).{0,40}(?:演讲|视频)",
                BeautifulSoup(page, "html.parser").get_text(" ", strip=True),
                re.I,
            )
        )
        paper_only = bool(re.search(r"\bpaper\b|论文", label, re.I)) and not bool(
            re.search(r"slide|投影片|演示稿|幻灯片", label, re.I)
        )
        data, media, final = self.http.fetch(selected, budget)
        drive = re.fullmatch(r"/file/d/([A-Za-z0-9_-]+)/view/?", urlparse(selected).path)
        if urlparse(selected).hostname == "drive.google.com" and drive:
            data, media, final = self.http.fetch(
                "https://drive.google.com/uc?export=download&id=" + drive[1], budget
            )
            if media == "text/html":
                raise PlatformError(
                    "ACCESS_REQUIRED",
                    "Public Drive download returned an access/confirmation page; explicit authorized import required",
                )
        if media == "application/pdf" and (paper_only or not (explicit_slides or catalog_slides)):
            raise PlatformError(
                "PAIRING_INVALID",
                "Linked PDF is not identified as slides; a paper cannot substitute",
            )
        if (
            item.goal == "editable_original_pptx"
            and media != "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ):
            raise PlatformError(
                "GOAL_NOT_MET", "Editable original PPTX was requested; a PDF cannot substitute"
            )
        if media not in (
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ):
            raise PlatformError("INVALID_MATERIAL", "Original slides must be an actual PDF or PPTX")
        identity_ok = (
            source.identity_status == "verified"
            and item.freshness_rule == "snapshot_at_acquisition"
        )
        goal = GoalResult(
            state="met" if identity_ok else "unknown",
            reason_code="PAIRED_ORIGINAL_ACQUIRED"
            if identity_ok
            else "FRESHNESS_OR_IDENTITY_NOT_VERIFIED",
            detail="Original slide document paired through the exact session page; no speech reading is claimed",
        )
        return Acquisition(
            (
                AcquiredDocument(page, "text/html", "source_metadata", page_url),
                AcquiredDocument(data, media, "original_slides", final),
            ),
            Observation(
                source_id=source.source_id,
                goal_result=goal,
                requested_window=item.requested_window,
                observed_window=item.requested_window,
                pagination_complete=True,
                coverage_notes=(
                    "Paired page archived as metadata; cannot substitute for research content",
                    "Speech not acquired; editable original PPTX only when actual media type is PPTX",
                    "Catalog scope and same-session video/document association verified"
                    if catalog_slides
                    else "Slide identity follows the explicit linked material label",
                ),
            ),
        )
