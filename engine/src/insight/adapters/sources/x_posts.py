"""One API page per acquisition: the worker commits every page before requesting the next."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from insight.domain.contracts import GoalResult, Observation, PlatformError, Source, SourcePlanItem
from insight.domain.rules import canonical, fingerprint
from insight.ports.sources import AcquiredDocument, Acquisition, Budget, SecretStore

API_SCHEMA_REF = "x-users-posts@2026-10-26"


class XPostsProvider:
    def __init__(self, secrets: SecretStore, transport: httpx.BaseTransport | None = None) -> None:
        self.secrets = secrets
        self.client = httpx.Client(
            base_url="https://api.x.com", timeout=25, follow_redirects=False, transport=transport
        )

    def capabilities(self) -> tuple[str, ...]:
        return ("latest_posts:body_and_link_metadata",)

    def _token(self, source: Source) -> str:
        value = self.secrets.get(source.credential_ref) if source.credential_ref else None
        if not value:
            raise PlatformError(
                "ACCESS_REQUIRED",
                "X API credential is not configured; no browser session is borrowed",
            )
        return value

    def probe(self, source: Source) -> dict[str, str]:
        self._token(source)
        return {
            "state": "credential_present_not_live_verified",
            "interface_version": API_SCHEMA_REF,
        }

    def discover(self, source: Source, item: SourcePlanItem, budget: Budget) -> tuple[str, ...]:
        return (source.resource_uri,)

    def _json(
        self, path: str, token: str, budget: Budget, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        budget.consume("network_requests", 1)
        try:
            with self.client.stream(
                "GET", path, params=params, headers={"Authorization": "Bearer " + token}
            ) as response:
                body = bytearray()
                status = response.status_code
                for part in response.iter_bytes():
                    if len(body) + len(part) > 5_000_000:
                        raise PlatformError("BUDGET_EXCEEDED", "X response exceeds page size limit")
                    budget.consume("source_bytes", len(part))
                    body.extend(part)
        except httpx.HTTPError as exc:
            raise PlatformError(
                "NETWORK_ERROR", "X API request failed; request headers were not persisted"
            ) from exc
        if status in (401, 402, 403):
            raise PlatformError(
                "ACCESS_REQUIRED", "X API access or account entitlement is insufficient"
            )
        if status == 429:
            retry = response.headers.get("retry-after", "60")
            raise PlatformError(
                "RATE_LIMITED",
                "X API rate limit; frozen window and committed checkpoint retained",
                min(int(retry), 86400) if retry.isdigit() else 60,
            )
        if status == 400 and params and params.get("pagination_token"):
            raise PlatformError(
                "CURSOR_INVALID",
                "Pagination token was rejected; same frozen window must be rescanned",
            )
        if status != 200:
            raise PlatformError("NETWORK_ERROR", f"X API returned HTTP {status}")
        try:
            result = json.loads(body)
        except ValueError as exc:
            raise PlatformError("INVALID_PROVIDER_RESPONSE", "X API returned invalid JSON") from exc
        if not isinstance(result, dict) or result.get("errors"):
            raise PlatformError(
                "INVALID_PROVIDER_RESPONSE", "X API returned an error or partial error envelope"
            )
        return result

    def acquire(
        self,
        source: Source,
        item: SourcePlanItem,
        budget: Budget,
        checkpoint: dict[str, str | int | bool | None],
    ) -> Acquisition:
        if (
            item.goal != "latest_posts"
            or item.post_scope != "body_and_link_metadata"
            or "post" not in item.accepted_material_roles
        ):
            raise PlatformError(
                "UNSUPPORTED_CAPABILITY",
                "X adapter supports explicit API-visible post bodies and link metadata only",
            )
        token = self._token(source)
        identity = re.fullmatch(r"x:user:([0-9]{1,19})", source.canonical_identity)
        resolved_lookup = None
        if not identity and re.fullmatch(r"x:handle:[A-Za-z0-9_]{1,15}", source.canonical_identity):
            handle = source.canonical_identity.removeprefix("x:handle:")
            if urlparse(source.resource_uri).path.strip("/").casefold() != handle.casefold():
                raise PlatformError("IDENTITY_MISMATCH", "X URL and handle disagree")
            stable = checkpoint.get("verified_user_id")
            if not stable:
                resolved_lookup = self._json("/2/users/by/username/" + handle, token, budget)
                user = resolved_lookup.get("data", {})
                if (
                    not re.fullmatch(r"[0-9]{1,19}", str(user.get("id", "")))
                    or str(user.get("username", "")).casefold() != handle.casefold()
                ):
                    raise PlatformError(
                        "IDENTITY_MISMATCH", "X username did not resolve to a stable matching ID"
                    )
                stable = user["id"]
            identity = re.fullmatch(r"x:user:([0-9]{1,19})", "x:user:" + str(stable))
        if not identity:
            raise PlatformError(
                "IDENTITY_NOT_VERIFIED", "Register a stable numeric X user ID, not a display name"
            )
        user_id = identity[1]
        try:
            start = datetime.fromisoformat(
                (item.requested_window.start or "").replace("Z", "+00:00")
            )
            end = datetime.fromisoformat(item.requested_window.end.replace("Z", "+00:00"))
            if start.tzinfo is None or end.tzinfo is None or start >= end:
                raise ValueError("invalid time interval")
        except ValueError as exc:
            raise PlatformError(
                "INVALID_SPEC", "X window requires explicit timezone-aware start < end"
            ) from exc
        query = {
            "user_id": user_id,
            "start": item.requested_window.start,
            "end": item.requested_window.end,
            "exclude_replies": item.exclude_replies,
            "exclude_reposts": item.exclude_reposts,
            "scope": item.post_scope,
        }
        query_hash = fingerprint(query)
        if checkpoint.get("query_hash") not in (None, query_hash):
            raise PlatformError(
                "REVISION_CONFLICT", "Cannot reuse cursor for a different frozen X query"
            )
        pages = int(checkpoint.get("pages_committed") or 0)
        cp = dict(checkpoint)
        if pages >= item.page_budget:
            return Acquisition(
                (),
                Observation(
                    source_id=source.source_id,
                    requested_window=item.requested_window,
                    goal_result=GoalResult(
                        state="not_met",
                        reason_code="PAGE_BUDGET_EXCEEDED",
                        detail="Frozen per-run page budget exhausted; completed watermark was not advanced",
                    ),
                    checkpoint=cp,
                ),
            )
        documents = []
        if resolved_lookup:
            documents.append(
                AcquiredDocument(
                    canonical(resolved_lookup),
                    "application/json",
                    "source_metadata",
                    source.resource_uri,
                )
            )
        username = str(checkpoint.get("verified_username") or "")
        if not username:
            lookup = self._json("/2/users/" + user_id, token, budget)
            user = lookup.get("data", {})
            expected_handle = urlparse(source.resource_uri).path.strip("/").split("/")[0]
            if (
                user.get("id") != user_id
                or not isinstance(user.get("username"), str)
                or user["username"].lower() != expected_handle.lower()
            ):
                raise PlatformError(
                    "IDENTITY_MISMATCH",
                    "Stable user ID and expected handle do not match; source identity needs review",
                )
            username = user["username"]
            documents.append(
                AcquiredDocument(
                    canonical(lookup),
                    "application/json",
                    "source_metadata",
                    "https://api.x.com/2/users/" + user_id,
                )
            )
        params = {
            "start_time": str(item.requested_window.start),
            "end_time": item.requested_window.end,
            "max_results": "100",
            "post.fields": "id,text,author_id,created_at,conversation_id,note_post,entities,attachments,edit_controls",
        }
        excludes = []
        if item.exclude_replies:
            excludes.append("replies")
        if item.exclude_reposts:
            excludes.append("retweets")
        if excludes:
            params["exclude"] = ",".join(excludes)
        if checkpoint.get("next_token"):
            params["pagination_token"] = str(checkpoint["next_token"])
        try:
            page = self._json("/2/users/" + user_id + "/tweets", token, budget, params)
        except PlatformError as exc:
            if exc.code == "CURSOR_INVALID" and int(checkpoint.get("rescan_count") or 0) < 1:
                cp.update(
                    query_hash=query_hash,
                    next_token=None,
                    verified_username=username,
                    rescan_count=1,
                )
                return Acquisition(
                    tuple(documents),
                    Observation(
                        source_id=source.source_id,
                        requested_window=item.requested_window,
                        goal_result=GoalResult(
                            state="not_met",
                            reason_code="CURSOR_RESET_PENDING",
                            detail="Rescan same frozen window and deduplicate committed posts",
                        ),
                        checkpoint=cp,
                    ),
                )
            raise
        posts = page.get("data", [])
        if not isinstance(posts, list):
            raise PlatformError("INVALID_PROVIDER_RESPONSE", "Expected post array")
        max_id = int(str(checkpoint.get("max_id") or "0"))
        for post in posts:
            if (
                not isinstance(post, dict)
                or not re.fullmatch(r"[0-9]{1,19}", str(post.get("id", "")))
                or post.get("author_id") != user_id
                or not isinstance(post.get("text"), str)
            ):
                raise PlatformError(
                    "INVALID_PROVIDER_RESPONSE", "Post identity or body is incomplete"
                )
            try:
                created = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise PlatformError(
                    "INVALID_PROVIDER_RESPONSE", "Post timestamp missing or invalid"
                ) from exc
            if created.tzinfo is None or not start <= created < end:
                raise PlatformError(
                    "INVALID_PROVIDER_RESPONSE", "Provider returned posts outside the frozen window"
                )
            max_id = max(max_id, int(post["id"]))
            documents.append(
                AcquiredDocument(
                    canonical(post),
                    "application/json",
                    "post",
                    f"https://x.com/{username}/status/{post['id']}",
                    post["created_at"],
                )
            )
        meta = page.get("meta", {})
        if (
            not isinstance(meta, dict)
            or "result_count" not in meta
            or meta["result_count"] != len(posts)
        ):
            raise PlatformError("INVALID_PROVIDER_RESPONSE", "Pagination metadata is incomplete")
        next_token = meta.get("next_token")
        if next_token is not None and not isinstance(next_token, str):
            raise PlatformError("INVALID_PROVIDER_RESPONSE", "Invalid pagination token")
        complete = not next_token
        cp.update(
            query_hash=query_hash,
            verified_user_id=user_id,
            pages_committed=pages + 1,
            next_token=next_token,
            verified_username=username,
            max_id=str(max_id),
        )
        if complete:
            cp["completed_window_end"] = item.requested_window.end
        documents.append(
            AcquiredDocument(
                canonical(page),
                "application/json",
                "source_metadata",
                "https://api.x.com/2/users/" + user_id + "/tweets",
            )
        )
        return Acquisition(
            tuple(documents),
            Observation(
                source_id=source.source_id,
                requested_window=item.requested_window,
                observed_window=item.requested_window if complete else None,
                pagination_complete=complete,
                checkpoint=cp,
                goal_result=GoalResult(
                    state="met" if complete else "not_met",
                    reason_code="API_WINDOW_COMPLETE" if complete else "PAGINATION_PENDING",
                    detail="Declared API-visible body window complete"
                    if complete
                    else "Page committed; more pages remain in the same frozen window",
                ),
                coverage_notes=(
                    "Body and link metadata only; media bytes, full articles and thread parents are not acquired",
                    "Deleted, protected, unavailable and provider-history-limited posts cannot be claimed as fully covered",
                    API_SCHEMA_REF,
                ),
            ),
        )

    def close(self) -> None:
        self.client.close()
