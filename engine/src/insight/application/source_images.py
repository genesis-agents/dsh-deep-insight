"""Archive original HTML images selected from a fixed source version, with budgeted requests."""

from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from insight.domain.contracts import PlatformError

if TYPE_CHECKING:
    from insight.bootstrap import Application


class ImageParser(HTMLParser):
    """List image references in document order; do not infer their scientific meaning."""

    def __init__(self, origin: str) -> None:
        super().__init__()
        self.origin = origin
        self.images: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        values = dict(attrs)
        source = values.get("data-src") or values.get("src")
        if not source or source.startswith("data:"):
            return
        url = urljoin(self.origin, source)
        if urlparse(url).scheme not in ("http", "https"):
            return
        if any(row["image_url"] == url for row in self.images):
            return
        self.images.append(
            {
                "unit_index": len(self.images) + 1,
                "image_url": url,
                "caption": values.get("alt") or values.get("title") or "",
            }
        )


def source_images(
    app: Application, run_id: str, version_id: str, index: int | None
) -> dict[str, Any]:
    """List archived HTML image references, or capture one exact reference as an immutable artifact."""
    with app.db.transaction(None) as repo:
        version = next(
            (v for v in repo.versions(run_id) if v.version_id == version_id), None
        )
        if version is None:
            raise PlatformError(
                "INVALID_SPEC", "Source version does not belong to this run"
            )
        artifact = repo.artifact(version.raw_artifact_id)
        if artifact.media_type != "text/html":
            raise PlatformError(
                "UNSUPPORTED_CAPABILITY",
                "HTML image capture requires an archived HTML source; PDF figures use page numbers",
            )
        parser = ImageParser(version.origin_uri)
        parser.feed(app.blobs.read(artifact).decode("utf-8", errors="replace"))
        if index is None:
            return {"source_version_id": version_id, "images": parser.images}
        if index < 1 or index > len(parser.images):
            raise PlatformError(
                "INVALID_SPEC", "Image index is outside this fixed source"
            )
        selected = parser.images[index - 1]
        for event in repo.events(run_id):
            row = event["payload"]
            if (
                event["kind"] == "source_image_archived"
                and row.get("source_version_id") == version_id
                and row.get("unit_index") == index
            ):
                return row
        limits = repo.frozen_input(run_id).plan.limits
    url = selected["image_url"]
    parsed = urlparse(url)
    if parsed.username or parsed.password or not parsed.hostname:
        raise PlatformError("INVALID_SPEC", "Image URL must be a public HTTP address")
    addresses = socket.getaddrinfo(
        parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    )
    if not addresses or any(
        not ipaddress.ip_address(address[4][0]).is_global for address in addresses
    ):
        raise PlatformError("ACCESS_REQUIRED", "Image address is not public")
    with app.db.transaction(None) as repo:
        repo.budget_consume(run_id, "network_requests", 1, limits.network_requests)
    with app.http.client.stream("GET", url) as response:
        if response.status_code != 200:
            raise PlatformError(
                "NETWORK_ERROR",
                f"Original image returned HTTP {response.status_code}; redirects are not followed",
            )
        data = bytearray()
        for chunk in response.iter_bytes():
            if len(data) + len(chunk) > app.settings.maximum_file_bytes:
                raise PlatformError(
                    "BUDGET_EXCEEDED", "Original image exceeds the file limit"
                )
            with app.db.transaction(None) as repo:
                repo.budget_consume(
                    run_id, "source_bytes", len(chunk), limits.source_bytes
                )
            data.extend(chunk)
    raw = bytes(data)
    media, suffix = (
        ("image/png", ".png")
        if raw.startswith(b"\x89PNG\r\n\x1a\n")
        else ("image/jpeg", ".jpg")
        if raw.startswith(b"\xff\xd8\xff")
        else (None, None)
    )
    if media is None:
        raise PlatformError(
            "UNSUPPORTED_CAPABILITY",
            "Original image must be PNG or JPEG; active content is not accepted",
        )
    saved = app.blobs.put(raw, media, "raw_document", "source-image@1")
    path = Path(".source-figures") / (saved.artifact_id + str(suffix))
    target = app.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.resolve().is_relative_to(app.root):
        raise PlatformError(
            "ACCESS_REQUIRED", "Image archive must remain inside the research workspace"
        )
    target.write_bytes(raw)
    acquired_at = app.research.clock()
    result = {
        **selected,
        "source_version_id": version_id,
        "image_artifact_id": saved.artifact_id,
        "source_url": version.origin_uri,
        "path": path.as_posix(),
        "acquired_at": acquired_at,
    }
    with app.db.transaction(None) as repo:
        repo.save_artifact(saved)
        repo.event(run_id, "source_image_archived", result, acquired_at)
    return result
