"""Register browser-observed data through the same immutable source and acquisition flow."""

import hashlib

from insight.domain.captures import BrowserCaptureBundle, BrowserImportRequest
from insight.domain.contracts import PlatformError, Source, SourceOrigin, StagedCaptureAttachment
from insight.ports.storage import BlobStore, Transaction


class CaptureService:
    def __init__(self, tx: Transaction, blobs: BlobStore, maximum_bytes: int) -> None:
        self.tx, self.blobs, self.maximum_bytes = tx, blobs, maximum_bytes

    def import_capture(self, request: BrowserImportRequest) -> Source:
        uri = self.blobs.stage_local(request.native_path, self.maximum_bytes)
        data, _ = self.blobs.read_inbox(uri, self.maximum_bytes)
        if hashlib.sha256(data).hexdigest() != request.sha256:
            raise PlatformError("EVIDENCE_INVALID", "Browser receipt checksum differs")
        receipt = BrowserCaptureBundle.model_validate_json(data)
        attachments = []
        for file in request.attachments:
            staged = self.blobs.stage_local(file.native_path, self.maximum_bytes)
            content, _ = self.blobs.read_inbox(staged, self.maximum_bytes)
            if hashlib.sha256(content).hexdigest() != file.sha256:
                raise PlatformError("EVIDENCE_INVALID", "Browser attachment checksum differs")
            if file.media_type == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise PlatformError("INVALID_MATERIAL", "Screenshot is not a PNG")
            attachments.append(
                StagedCaptureAttachment(uri=staged, sha256=file.sha256, media_type=file.media_type)
            )
        source = Source(
            source_id=request.source_id,
            provider="browser",
            canonical_identity="browser-capture:" + request.sha256,
            resource_uri=receipt.resource_url,
            publisher=request.publisher,
            identity_status="user_provided",
            identity_basis=(
                request.provenance,
                "Browser-observed public content; observer: " + receipt.observer,
                "Observed at: " + receipt.observed_at + "; scope: " + receipt.scope,
            ),
            origin=SourceOrigin(
                channel="x"
                if receipt.scope == "public_post_sample"
                else "youtube"
                if receipt.scope == "video_caption_track"
                else "official",
                publication_url=receipt.resource_url,
            ),
            capture_uri=uri,
            capture_attachments=tuple(attachments),
        )
        with self.tx(None) as repo:
            repo.save_source(source)
        return source
