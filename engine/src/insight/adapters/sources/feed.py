"""Explicit RSS/Atom discovery snapshots, never a claim of complete account history."""

from __future__ import annotations

from urllib.parse import urljoin

from defusedxml import ElementTree as ET

from insight.adapters.sources.http import PublicHttpClient
from insight.domain.contracts import GoalResult, Observation, PlatformError, Source, SourcePlanItem
from insight.domain.rules import canonical
from insight.ports.sources import AcquiredDocument, Acquisition, Budget


class FeedProvider:
    def __init__(self, http: PublicHttpClient) -> None:
        self.http = http

    def capabilities(self) -> tuple[str, ...]:
        return ("discover_updates",)

    def probe(self, source: Source) -> dict[str, str]:
        return dict(state="requires_acquisition", scope="published_feed_snapshot_only")

    def discover(self, source: Source, item: SourcePlanItem, budget: Budget) -> tuple[str, ...]:
        data, _, final = self.http.fetch(source.resource_uri, budget)
        try:
            root = ET.fromstring(data)
        except Exception as exc:
            raise PlatformError("INVALID_MATERIAL", "Not a readable RSS/Atom feed") from exc
        links = []
        for node in root.iter():
            if node.tag.split("}")[-1] != "link":
                continue
            value = node.attrib.get("href") or node.text or ""
            value = urljoin(final, value.strip())
            if value.startswith(("https://", "http://")):
                links.append(value)
        return tuple(dict.fromkeys(links))

    def acquire(
        self,
        source: Source,
        item: SourcePlanItem,
        budget: Budget,
        checkpoint: dict[str, str | int | bool | None],
    ) -> Acquisition:
        if item.goal != "discover_updates" or "source_metadata" not in item.accepted_material_roles:
            raise PlatformError(
                "UNSUPPORTED_CAPABILITY",
                "Feed discovers entries only; fetch articles or videos as separate planned sources",
            )
        data, media, final = self.http.fetch(source.resource_uri, budget)
        try:
            root = ET.fromstring(data)
            if root.tag.split("}")[-1] not in ("rss", "feed", "RDF"):
                raise ValueError("Not a feed")
        except Exception as exc:
            raise PlatformError("INVALID_MATERIAL", "Malformed RSS/Atom feed") from exc
        entries = []
        for node in root.iter():
            if node.tag.split("}")[-1] in ("item", "entry"):
                values = {
                    c.tag.split("}")[-1]: (c.attrib.get("href") or c.text or "") for c in node
                }
                entries.append(values)
        return Acquisition(
            (
                AcquiredDocument(data, media, "source_metadata", final),
                AcquiredDocument(
                    canonical(dict(entries=entries)), "application/json", "source_metadata", final
                ),
            ),
            Observation(
                source_id=source.source_id,
                requested_window=item.requested_window,
                goal_result=GoalResult(
                    state="met",
                    reason_code="FEED_SNAPSHOT_ACQUIRED",
                    detail=f"Archived {len(entries)} feed entries; feed truncation and full historical coverage remain unknown",
                ),
                coverage_notes=(
                    "Discovery only: linked article bodies, videos and attachments have not been read",
                ),
            ),
        )
