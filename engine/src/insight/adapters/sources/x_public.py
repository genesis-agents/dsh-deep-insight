"""Public single-post samples via X's published embed endpoint; no account window claim."""

import json
import re
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup, Tag

from insight.adapters.sources.http import PublicHttpClient
from insight.adapters.sources.x_posts import XPostsProvider
from insight.domain.contracts import GoalResult, Observation, PlatformError, Source, SourcePlanItem
from insight.domain.rules import canonical
from insight.ports.sources import AcquiredDocument, Acquisition, Budget


class XProvider:
    def __init__(self, api: XPostsProvider, http: PublicHttpClient) -> None:
        self.api, self.http = api, http

    def capabilities(self) -> tuple[str, ...]:
        return ("latest_posts:authorized_api", "public_post:single_sample")

    def probe(self, source: Source) -> dict[str, str]:
        if "/status/" in source.resource_uri:
            return dict(state="requires_acquisition", scope="one_public_embedded_post_only")
        return self.api.probe(source)

    def discover(self, source: Source, item: SourcePlanItem, budget: Budget) -> tuple[str, ...]:
        return (source.resource_uri,)

    def acquire(
        self,
        source: Source,
        item: SourcePlanItem,
        budget: Budget,
        checkpoint: dict[str, str | int | bool | None],
    ) -> Acquisition:
        if item.goal == "latest_posts":
            return self.api.acquire(source, item, budget, checkpoint)
        if item.goal != "public_post" or "post" not in item.accepted_material_roles:
            raise PlatformError(
                "UNSUPPORTED_CAPABILITY",
                "X requires an authorized account window or an explicit public single-post sample",
            )
        uri = urlparse(source.resource_uri)
        match = re.fullmatch(r"/([A-Za-z0-9_]{1,15})/status/([0-9]{1,20})/?", uri.path)
        if (
            uri.hostname not in ("x.com", "www.x.com", "twitter.com", "www.twitter.com")
            or not match
        ):
            raise PlatformError("INVALID_SPEC", "Specify one canonical X status URL")
        data, _, _ = self.http.fetch(
            "https://publish.twitter.com/oembed?"
            + urlencode(
                dict(url=source.resource_uri, omit_script="true", dnt="true", hide_thread="true")
            ),
            budget,
        )
        try:
            record = json.loads(data)
            block = BeautifulSoup(record["html"], "html.parser").find("blockquote")
            if not isinstance(block, Tag):
                raise ValueError("No embedded post")
            paragraph = block.select_one("p") if block else None
            text = paragraph.get_text(" ", strip=True) if paragraph else ""
            links = [a.get("href", "") for a in block.select("a")] if block else []
            author = urlparse(record["author_url"]).path.strip("/")
            if (
                not text
                or author.casefold() != match[1].casefold()
                or not any(f"/status/{match[2]}" in str(link) for link in links)
            ):
                raise ValueError("Embed identity mismatch or no body")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise PlatformError(
                "INVALID_PROVIDER_RESPONSE",
                "Public embed did not supply the requested post identity and body",
            ) from exc
        post = dict(
            id=match[2],
            text=text,
            author_handle=author,
            retrieval="public_oembed_sample",
            scope="one_visible_embed; full_long_post_or_thread_not_asserted",
        )
        return Acquisition(
            (
                AcquiredDocument(data, "application/json", "source_metadata", source.resource_uri),
                AcquiredDocument(canonical(post), "application/json", "post", source.resource_uri),
            ),
            Observation(
                source_id=source.source_id,
                requested_window=item.requested_window,
                goal_result=GoalResult(
                    state="met",
                    reason_code="PUBLIC_POST_SAMPLE_ACQUIRED",
                    detail="One publicly embedded post body acquired; no latest-account, complete-thread or full-long-post claim",
                ),
                coverage_notes=(
                    "Public sample only: does not advance an API window watermark",
                    "Expanded text, attachments and external articles require separate acquisition",
                ),
            ),
        )
