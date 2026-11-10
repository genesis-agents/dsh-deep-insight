"""Immutable blob store with bounded reads and atomic commits."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path
from uuid import uuid4

from insight.domain.contracts import Artifact, MaterialRole, PlatformError
from insight.domain.rules import stable_id


def native_path(path: Path) -> Path:
    """Use extended absolute paths on Windows without changing stored logical references."""
    absolute = str(path.resolve())
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def atomic_write(path: Path, data: bytes) -> None:
    path = native_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".tmp-" + uuid4().hex)
    try:
        with temporary.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def bounded_read(path: Path, maximum_bytes: int) -> bytes:
    path = native_path(path)
    if not path.is_file() or path.stat().st_size > maximum_bytes:
        raise PlatformError(
            "INVALID_MATERIAL", "Missing file or file exceeds configured size limit"
        )
    expected_size = path.stat().st_size
    with path.open("rb") as f:
        # Reading with the full configured ceiling preallocates ~50 MB even for
        # tiny documents. Bound by the actual file size and detect concurrent edits.
        data = f.read(min(expected_size + 1, maximum_bytes + 1))
    if len(data) > maximum_bytes:
        raise PlatformError("BUDGET_EXCEEDED", "Material exceeds configured size limit")
    if len(data) != expected_size:
        raise PlatformError("INVALID_MATERIAL", "Material changed while it was being read")
    return data


class FileObjectStore:
    def __init__(self, root: Path, maximum_bytes: int = 50_000_000) -> None:
        self.root, self.maximum_bytes = root.resolve(), maximum_bytes

    def object_path(self, sha: str) -> Path:
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise PlatformError("EVIDENCE_INVALID", "Invalid content digest")
        return native_path(self.root / "objects" / "sha256" / sha[:2] / sha)

    def put(self, data: bytes, media_type: str, role: MaterialRole, producer: str) -> Artifact:
        if len(data) > self.maximum_bytes:
            raise PlatformError("BUDGET_EXCEEDED", "Artifact exceeds configured size limit")
        digest = hashlib.sha256(data).hexdigest()
        target = self.object_path(digest)
        if target.exists():
            if hashlib.sha256(bounded_read(target, self.maximum_bytes)).hexdigest() != digest:
                raise PlatformError("EVIDENCE_INVALID", "Existing immutable object is corrupt")
        else:
            atomic_write(target, data)
        return Artifact(
            artifact_id=stable_id("art", digest, media_type, role, producer),
            sha256=digest,
            media_type=media_type,
            size=len(data),
            role=role,
            producer_ref=producer,
        )

    def read(self, artifact: Artifact) -> bytes:
        data = bounded_read(self.object_path(artifact.sha256), self.maximum_bytes)
        if len(data) != artifact.size or hashlib.sha256(data).hexdigest() != artifact.sha256:
            raise PlatformError("EVIDENCE_INVALID", "Artifact hash or size mismatch")
        return data

    def stage_local(self, native_path: str, maximum_bytes: int) -> str:
        path = Path(native_path).resolve()
        data = bounded_read(path, min(maximum_bytes, self.maximum_bytes))
        # Keep a logical, workspace-relative import identity, never an input-machine drive letter.
        relative = Path("inbox") / uuid4().hex / path.name
        atomic_write(self.root / relative, data)
        return "inbox://" + relative.relative_to("inbox").as_posix()

    def read_inbox(self, logical_uri: str, maximum_bytes: int) -> tuple[bytes, str]:
        if not logical_uri.startswith("inbox://"):
            raise PlatformError("INVALID_SPEC", "Expected an inbox URI")
        path = (self.root / "inbox" / logical_uri.removeprefix("inbox://")).resolve()
        if not path.is_relative_to(self.root / "inbox"):
            raise PlatformError("INVALID_SPEC", "Inbox path escapes workspace")
        return bounded_read(path, min(maximum_bytes, self.maximum_bytes)), mimetypes.guess_type(
            path.name
        )[0] or "application/octet-stream"
