from __future__ import annotations

from urllib.parse import urlparse

import httpx

from insight.adapters.transforms.publication import publication_date
from insight.adapters.transforms.text import sniff_type
from insight.domain.contracts import GoalResult, Observation, PlatformError, Source, SourcePlanItem
from insight.ports.sources import AcquiredDocument, Acquisition, Budget


class PublicHttpClient:
    def __init__(self, maximum_bytes: int, transport: httpx.BaseTransport | None = None) -> None:
        self.maximum_bytes = maximum_bytes
        self.client = httpx.Client(
            timeout=httpx.Timeout(25, connect=10),
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "PersonalInsightPlatform/0.1 (bounded document research)"},
        )

    def fetch(self, url: str, budget: Budget) -> tuple[bytes, str, str]:
        for attempt in range(2):
            try:
                return self._fetch_once(url, budget)
            except PlatformError as exc:
                if exc.code != "TRANSIENT_NETWORK_ERROR" or attempt:
                    if exc.code == "TRANSIENT_NETWORK_ERROR":
                        raise PlatformError("NETWORK_ERROR", exc.detail) from exc
                    raise
        raise AssertionError("Bounded retry loop exhausted")

    def _fetch_once(self, url: str, budget: Budget) -> tuple[bytes, str, str]:
        for _ in range(6):
            parsed = urlparse(url)
            if parsed.scheme not in ("https", "http") or parsed.username or parsed.password:
                raise PlatformError(
                    "INVALID_SPEC", "Expected public HTTP(S) URL without embedded credentials"
                )
            budget.consume("network_requests", 1)
            try:
                with self.client.stream("GET", url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise PlatformError("INVALID_MATERIAL", "Redirect without destination")
                        url = str(response.url.join(location))
                        continue
                    if response.status_code in (401, 403):
                        raise PlatformError(
                            "ACCESS_REQUIRED",
                            "Source denied access; authentication was not bypassed",
                        )
                    if response.status_code == 429:
                        retry = response.headers.get("retry-after", "60")
                        raise PlatformError(
                            "RATE_LIMITED",
                            "Source rate limit; retry window requires a later attempt",
                            min(int(retry), 86400) if retry.isdigit() else 60,
                        )
                    if response.status_code in (500, 502, 503, 504):
                        retry = response.headers.get("retry-after")
                        if retry:
                            raise PlatformError(
                                "RATE_LIMITED",
                                "Server supplied a retry window; request deferred",
                                min(int(retry), 86400) if retry.isdigit() else 60,
                            )
                        raise PlatformError(
                            "TRANSIENT_NETWORK_ERROR",
                            f"Source returned HTTP {response.status_code}",
                        )
                    if response.status_code >= 400:
                        raise PlatformError(
                            "NETWORK_ERROR", f"Source returned HTTP {response.status_code}"
                        )
                    content = bytearray()
                    for part in response.iter_bytes():
                        if len(content) + len(part) > self.maximum_bytes:
                            raise PlatformError("BUDGET_EXCEEDED", "Download size limit exceeded")
                        budget.consume("source_bytes", len(part))
                        content.extend(part)
                    data = bytes(content)
                    if not data:
                        raise PlatformError("INVALID_MATERIAL", "Empty response body")
                    media = sniff_type(
                        data, response.headers.get("content-type", "application/octet-stream")
                    )
                    return data, media, str(response.url)
            except httpx.HTTPError as exc:
                raise PlatformError(
                    "TRANSIENT_NETWORK_ERROR", f"Network operation failed ({type(exc).__name__})"
                ) from exc
        raise PlatformError("NETWORK_ERROR", "Redirect limit exceeded")

    def close(self) -> None:
        self.client.close()


class HttpDocumentProvider:
    def __init__(self, client: PublicHttpClient) -> None:
        self.http = client

    def capabilities(self) -> tuple[str, ...]:
        return ("document_text",)

    def probe(self, source: Source) -> dict[str, str]:
        # Discovery/probe does not pretend that reading the URL produced research evidence.
        return {
            "state": "requires_acquisition",
            "detail": "Actual body checked during a budgeted acquisition",
        }

    def discover(self, source: Source, item: SourcePlanItem, budget: Budget) -> tuple[str, ...]:
        return (source.resource_uri,)

    def acquire(
        self,
        source: Source,
        item: SourcePlanItem,
        budget: Budget,
        checkpoint: dict[str, str | int | bool | None],
    ) -> Acquisition:
        if item.goal != "document_text" or "raw_document" not in item.accepted_material_roles:
            raise PlatformError(
                "UNSUPPORTED_CAPABILITY", "HTTP adapter only supports document_text/raw_document"
            )
        data, media, final_url = self.http.fetch(source.resource_uri, budget)
        fresh = item.freshness_rule == "snapshot_at_acquisition"
        goal = GoalResult(
            state="met" if source.identity_status == "verified" and fresh else "unknown",
            reason_code="FRESHNESS_NOT_VERIFIED"
            if not fresh
            else "BODY_ACQUIRED"
            if source.identity_status == "verified"
            else "IDENTITY_NOT_VERIFIED",
            detail="Content acquired; source identity depends on the recorded identity basis",
        )
        return Acquisition(
            (
                AcquiredDocument(
                    data,
                    media,
                    "raw_document",
                    final_url,
                    publication_date(data) if media == "text/html" else None,
                ),
            ),
            Observation(
                source_id=source.source_id,
                goal_result=goal,
                requested_window=item.requested_window,
                observed_window=None,
                pagination_complete=True,
                coverage_notes=(
                    "Current snapshot only; historical publication availability is not verified",
                    "Single specified document only; no whole-site or historical coverage claimed",
                ),
            ),
        )
