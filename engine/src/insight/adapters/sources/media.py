"""Optional bounded public-video download and sampled frames with decoded timestamps."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from insight.domain.contracts import (
    GoalResult,
    MediaOptions,
    Observation,
    PlatformError,
    Source,
    SourcePlanItem,
)
from insight.domain.rules import canonical
from insight.ports.sources import AcquiredDocument, Acquisition, Budget


class QuietLogger:
    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass


class MediaFramesProvider:
    def __init__(self, temporary_root: Path, maximum_bytes: int) -> None:
        self.temporary_root, self.maximum_bytes = temporary_root, maximum_bytes

    def acquire(
        self,
        source: Source,
        item: SourcePlanItem,
        budget: Budget,
        checkpoint: dict[str, str | int | bool | None],
    ) -> Acquisition:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:
            raise PlatformError(
                "DEPENDENCY_REQUIRED",
                "Install the locked media extra: uv sync --frozen --extra media",
            ) from exc
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise PlatformError(
                "DEPENDENCY_REQUIRED", "ffmpeg is required for decoded frame extraction"
            )
        options = item.media or MediaOptions()
        maximum = min(options.maximum_bytes, self.maximum_bytes)
        deadline = time.monotonic() + 240

        def check_time() -> None:
            if time.monotonic() > deadline:
                raise PlatformError("BUDGET_EXCEEDED", "Media operation time budget exhausted")

        class BoundedDL(YoutubeDL):
            def urlopen(self, request: Any) -> Any:
                check_time()
                budget.consume("network_requests", 1)
                response = super().urlopen(request)
                read = response.read

                def counted_read(amount: int | None = None) -> bytes:
                    check_time()
                    data: bytes = read(amount)
                    budget.consume("source_bytes", len(data))
                    return data

                response.__dict__["read"] = counted_read
                return response

        def progress(status: dict[str, Any]) -> None:
            check_time()
            if int(status.get("downloaded_bytes", 0)) > maximum:
                raise PlatformError("BUDGET_EXCEEDED", "Downloaded media exceeded byte ceiling")

        self.temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="video-", dir=self.temporary_root) as tmp:
            folder = Path(tmp)
            params: Any = dict(
                outtmpl=str(folder / "video.%(ext)s"),
                quiet=True,
                no_warnings=True,
                noplaylist=True,
                cachedir=False,
                retries=0,
                fragment_retries=0,
                extractor_retries=0,
                socket_timeout=20,
                logger=QuietLogger(),
                progress_hooks=[progress],
                format="worst[height<=480][ext=mp4]/worst[height<=480]",
                max_filesize=maximum,
                concurrent_fragment_downloads=1,
                restrictfilenames=True,
            )
            try:
                with BoundedDL(params) as downloader:
                    info = downloader.extract_info(source.resource_uri, download=False)
                    if not isinstance(info, dict) or info.get("is_live"):
                        raise PlatformError(
                            "INVALID_MATERIAL", "One completed public video is required"
                        )
                    duration = info.get("duration")
                    if (
                        not isinstance(duration, (int, float))
                        or not 0 < duration <= options.maximum_seconds
                    ):
                        raise PlatformError(
                            "BUDGET_EXCEEDED",
                            "Video duration missing or outside the declared media ceiling",
                        )
                    downloader.process_info(info)
            except PlatformError:
                raise
            except Exception as exc:
                blocked = any(
                    x in str(exc).lower()
                    for x in ("sign in", "not a bot", "403", "429", "private video", "unavailable")
                )
                raise PlatformError(
                    "ACCESS_REQUIRED" if blocked else "NETWORK_ERROR",
                    "Public video download failed; no account cookies, authentication bypass or rotating proxies used",
                ) from exc
            videos = [
                p for p in folder.glob("video.*") if p.suffix not in (".part", ".ytdl", ".json")
            ]
            if len(videos) != 1 or not 0 < videos[0].stat().st_size <= maximum:
                raise PlatformError(
                    "BUDGET_EXCEEDED",
                    "No complete media file inside the byte ceiling; partial files not published",
                )
            video = videos[0]
            command = [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-i",
                str(video),
                "-an",
                "-vf",
                f"select=isnan(prev_selected_t)+gte(t-prev_selected_t\\,{options.frame_interval_seconds}),scale=w='min(1280,iw)':h=-2,showinfo",
                "-fps_mode",
                "vfr",
                "-frames:v",
                str(options.maximum_frames),
                str(folder / "frame-%04d.png"),
            ]
            try:
                result = subprocess.run(command, capture_output=True, timeout=120, check=False)
            except subprocess.TimeoutExpired as exc:
                raise PlatformError("BUDGET_EXCEEDED", "Frame extraction timed out") from exc
            if result.returncode:
                raise PlatformError("INVALID_MATERIAL", "ffmpeg could not decode this video")
            timestamps = [float(x) for x in re.findall(rb"pts_time:([0-9.]+)", result.stderr)]
            frames = sorted(folder.glob("frame-*.png"))
            if not frames or len(frames) != len(timestamps):
                raise PlatformError(
                    "INVALID_MATERIAL", "Decoded frame timestamps do not match frame files"
                )
            video_data = video.read_bytes()
            docs = [
                AcquiredDocument(
                    video_data,
                    "video/mp4" if video.suffix == ".mp4" else "video/webm",
                    "raw_video",
                    source.resource_uri,
                )
            ]
            records = []
            for frame, timestamp in zip(frames, timestamps, strict=True):
                data = frame.read_bytes()
                docs.append(
                    AcquiredDocument(
                        data,
                        "image/png",
                        "derived_slide_frames",
                        source.resource_uri + f"#t={timestamp:.3f}",
                    )
                )
                records.append(
                    dict(
                        seconds=timestamp, sha256=hashlib.sha256(data).hexdigest(), frame=frame.name
                    )
                )
            manifest = dict(
                schema="video-frame-sampling@1",
                video_sha256=hashlib.sha256(video_data).hexdigest(),
                duration_seconds=duration,
                sample_interval_seconds=options.frame_interval_seconds,
                frames=records,
                completeness="sampled_candidates_only; no complete_slide_recovery_claim",
                command=command[4:],
            )
            # Do not retain the machine's temporary paths in portable records.
            manifest.pop("command")
            docs.append(
                AcquiredDocument(
                    canonical(manifest), "application/json", "source_metadata", source.resource_uri
                )
            )
            return Acquisition(
                tuple(docs),
                Observation(
                    source_id=source.source_id,
                    requested_window=item.requested_window,
                    goal_result=GoalResult(
                        state="met",
                        reason_code="SAMPLED_FRAMES_ACQUIRED",
                        detail=f"Archived {len(frames)} decoded samples and source video; not a complete PPT recovery",
                    ),
                    coverage_notes=(
                        "Frame positions are decoded pts_time, not invented page times",
                        "Short slides, transitions, animation stages and occlusions can be missed; visual review still required",
                    ),
                ),
            )
