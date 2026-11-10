"""Optional local ASR: explicit model setup, offline inference in a bounded child process."""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from insight.domain.contracts import MediaOptions, PlatformError


class LocalSpeechRuntime:
    def __init__(self, model_root: Path, temporary_root: Path) -> None:
        self.model_root, self.temporary_root = model_root, temporary_root

    def install_model(self, model: str) -> dict[str, str]:
        if model not in ("tiny.en", "tiny", "base.en", "base"):
            raise PlatformError("INVALID_SPEC", "Choose a supported bounded local ASR model")
        try:
            hub = importlib.import_module("huggingface_hub")
            importlib.import_module("faster_whisper")
        except ImportError as exc:
            raise PlatformError(
                "DEPENDENCY_REQUIRED",
                "Install the locked speech extra: uv sync --frozen --extra speech",
            ) from exc
        target = self.model_root / model
        target.mkdir(parents=True, exist_ok=True)
        # Public model assets only; do not reuse an implicit Hugging Face account token.
        try:
            hub.snapshot_download(
                repo_id="Systran/faster-whisper-" + model,
                local_dir=str(target),
                token=False,
                max_workers=1,
                allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.*"],
            )
        except Exception as exc:
            raise PlatformError(
                "NETWORK_ERROR", "Public ASR model setup failed; no model was marked ready"
            ) from exc
        files = {}
        for asset in sorted(target.iterdir()):
            if asset.name in (
                "model.bin",
                "config.json",
                "tokenizer.json",
            ) or asset.name.startswith("vocabulary."):
                with asset.open("rb") as handle:
                    files[asset.name] = hashlib.file_digest(handle, "sha256").hexdigest()
        if not {"model.bin", "config.json", "tokenizer.json"}.issubset(files):
            raise PlatformError("ASR_FAILED", "Downloaded model bundle is incomplete")
        digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        manifest: dict[str, Any] = dict(
            model=model,
            model_sha256=digest,
            repo="Systran/faster-whisper-" + model,
            digest_scope="model_bundle_v1",
            files=files,
        )
        (target / "insight-model.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {key: str(value) for key, value in manifest.items() if key != "files"}

    def transcribe(self, data: bytes, suffix: str, options: MediaOptions) -> dict[str, Any]:
        if not options.asr_model or not options.asr_model_sha256:
            raise PlatformError(
                "INVALID_SPEC",
                "Local ASR requires a model and its bundle SHA-256 in frozen MediaOptions",
            )
        model = self.model_root / options.asr_model
        if not (model / "insight-model.json").is_file():
            raise PlatformError(
                "DEPENDENCY_REQUIRED",
                "Set up the selected local model with media-setup-asr before acquisition; no model is downloaded during research",
            )
        if len(data) > options.maximum_bytes:
            raise PlatformError("BUDGET_EXCEEDED", "Local media exceeds the declared size ceiling")
        try:
            manifest = json.loads((model / "insight-model.json").read_bytes())
        except (ValueError, OSError) as exc:
            raise PlatformError("ASR_FAILED", "Installed ASR manifest is unreadable") from exc
        if manifest.get("model_sha256") != options.asr_model_sha256:
            raise PlatformError("HASH_MISMATCH", "Installed ASR model differs from the frozen plan")
        self.temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="asr-", dir=self.temporary_root) as folder:
            media = Path(folder) / ("input" + suffix)
            media.write_bytes(data)
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-m",
                        "insight.adapters.transforms.asr_worker",
                        str(media),
                        str(model),
                        str(options.maximum_seconds),
                        options.asr_model_sha256,
                    ],
                    capture_output=True,
                    timeout=min(3600, options.maximum_seconds * 4 + 30),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise PlatformError(
                    "BUDGET_EXCEEDED", "Local ASR exceeded its time ceiling; child process stopped"
                ) from exc
            if result.returncode or len(result.stdout) > 20_000_000:
                raise PlatformError(
                    "ASR_FAILED",
                    "Local ASR failed or exceeded output ceiling; no generated transcript published",
                )
            try:
                payload: dict[str, Any] = json.loads(result.stdout)
                if not payload.get("segments") or payload.get("retrieval") != "local_asr":
                    raise ValueError("No usable ASR segments")
                payload["audio_sha256"] = hashlib.sha256(data).hexdigest()
                return payload
            except (ValueError, TypeError) as exc:
                raise PlatformError(
                    "ASR_FAILED", "Local ASR returned no usable timed text"
                ) from exc
