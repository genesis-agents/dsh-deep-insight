"""Composition root. OS paths and adapter wiring are kept out of the research core."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from pydantic import Field, field_validator

from insight import __version__
from insight.adapters.export.publisher import HtmlDeliveryPublisher
from insight.adapters.export.reading import ReadingRoomPublisher
from insight.adapters.persistence.database import Database
from insight.adapters.persistence.objects import FileObjectStore, atomic_write, native_path
from insight.adapters.persistence.profiles import BundledProfiles
from insight.adapters.persistence.secrets import OperatingSystemSecrets
from insight.adapters.sources.browser_capture import BrowserCaptureProvider
from insight.adapters.sources.feed import FeedProvider
from insight.adapters.sources.http import HttpDocumentProvider, PublicHttpClient
from insight.adapters.sources.local import LocalFileProvider
from insight.adapters.sources.media import MediaFramesProvider
from insight.adapters.sources.slides import PairedSlidesProvider
from insight.adapters.sources.x_posts import XPostsProvider
from insight.adapters.sources.x_public import XProvider
from insight.adapters.sources.youtube import YouTubeProvider
from insight.adapters.transforms.presentation import PptxInspector
from insight.adapters.transforms.speech import LocalSpeechRuntime
from insight.adapters.transforms.text import DocumentExtractor
from insight.application.captures import CaptureService
from insight.application.collectors import CollectorService
from insight.application.delivery import DeliveryService
from insight.application.projects import ProjectService
from insight.application.publications import PublicationService
from insight.application.queries import QueryService
from insight.application.reading import ReadingService
from insight.application.research import ResearchService
from insight.application.workflow import AcquisitionWorker
from insight.domain import contracts
from insight.domain.captures import BrowserCaptureBundle, BrowserImportRequest
from insight.domain.contracts import Contract, PlatformError
from insight.domain.publications import PublicationRequest
from insight.ports.sources import SourceProvider


class WorkspaceSettings(Contract):
    data_directory: str = "."
    output_directory: str = "outputs"
    maximum_file_bytes: int = Field(default=50_000_000, ge=1, le=1_000_000_000)
    lease_seconds: int = Field(default=120, ge=15, le=3600)

    @field_validator("data_directory", "output_directory")
    @classmethod
    def portable_directory(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if (
            not normalized.strip()
            or PurePosixPath(normalized).is_absolute()
            or PureWindowsPath(value).drive
            or ".." in PurePosixPath(normalized).parts
        ):
            raise ValueError(
                "Workspace directories must be relative paths without parent traversal"
            )
        return normalized


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def code_reference() -> str:
    repository = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        ).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "package:" + __version__


def repository_boundary() -> Path:
    """Respect the containing checkout when this platform lives in a monorepo."""
    source = Path(__file__).resolve().parents[2]
    return next((p for p in (source, *source.parents) if (p / ".git").exists()), source)


def initialize_workspace(root: Path) -> dict[str, str]:
    root = root.resolve()
    if root.is_relative_to(repository_boundary()):
        raise PlatformError("INVALID_SPEC", "Runtime workspace must be outside the code repository")
    native_path(root).mkdir(parents=True, exist_ok=True)
    settings = native_path(root / "workspace.toml")
    if not settings.exists():
        atomic_write(
            settings,
            (
                'schema_version = 1\ndata_directory = "90-平台运行"\n'
                'output_directory = "90-平台运行/outputs"\nmaximum_file_bytes = 50000000\nlease_seconds = 120\n'
            ).encode(),
        )
    configured = WorkspaceSettings.model_validate_json(
        json.dumps(tomllib.loads(settings.read_text(encoding="utf-8")))
    )
    data_root = (root / configured.data_directory).resolve()
    if not data_root.is_relative_to(root):
        raise PlatformError("INVALID_SPEC", "Data directory must remain inside the workspace")
    database = Database(data_root / "state" / "insight.db", utc_now)
    migrations = Path(__file__).resolve().parents[2] / "migrations"
    if not migrations.is_dir():
        migrations = Path(__file__).parent / "resources" / "migrations"
    database.migrate(migrations)
    database.close()
    return {"workspace": str(root), "settings": str(settings), "schema_revision": "0002"}


class Application:
    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], str] = utc_now,
        providers: dict[str, SourceProvider] | None = None,
    ) -> None:
        self.root = root.resolve()
        setting_path = native_path(self.root / "workspace.toml")
        if not setting_path.is_file():
            raise PlatformError("WORKSPACE_NOT_INITIALIZED", "Run init for this workspace first")
        self.settings = WorkspaceSettings.model_validate_json(
            json.dumps(tomllib.loads(setting_path.read_text(encoding="utf-8")))
        )
        self.output_root = (self.root / self.settings.output_directory).resolve()
        self.data_root = (self.root / self.settings.data_directory).resolve()
        if not self.data_root.is_relative_to(self.root):
            raise PlatformError("INVALID_SPEC", "Data directory must remain inside the workspace")
        source_root = repository_boundary()
        if self.output_root.is_relative_to(source_root) or self.root.is_relative_to(source_root):
            raise PlatformError(
                "INVALID_SPEC", "Runtime workspace and outputs must be outside the code repository"
            )
        if not self.output_root.is_relative_to(self.root):
            raise PlatformError("INVALID_SPEC", "Outputs must remain inside the portable workspace")
        self.db = Database(self.data_root / "state" / "insight.db", clock)
        self.blobs = FileObjectStore(self.data_root, self.settings.maximum_file_bytes)
        self.http = PublicHttpClient(self.settings.maximum_file_bytes)
        self.x_posts = XPostsProvider(OperatingSystemSecrets())
        self.speech = LocalSpeechRuntime(
            self.data_root / "models/asr", self.data_root / "temporary/asr"
        )
        installed: dict[str, SourceProvider] = {
            "local": LocalFileProvider(self.blobs, self.settings.maximum_file_bytes, self.speech),
            "http": HttpDocumentProvider(self.http),
            "conference": PairedSlidesProvider(self.http),
            "youtube": YouTubeProvider(
                PairedSlidesProvider(self.http, require_video_pair=True),
                self.settings.maximum_file_bytes,
                MediaFramesProvider(
                    self.data_root / "temporary/media", self.settings.maximum_file_bytes
                ),
            ),
            "x": XProvider(self.x_posts, self.http),
            "feed": FeedProvider(self.http),
            "browser": BrowserCaptureProvider(self.blobs, self.settings.maximum_file_bytes),
        }
        if providers:
            installed.update(providers)
        self.providers = installed
        self.captures = CaptureService(
            self.db.transaction, self.blobs, self.settings.maximum_file_bytes
        )
        self.collectors = CollectorService(
            self.db.transaction, installed, BundledProfiles(), code_reference(), clock, self.speech
        )
        self.publisher = HtmlDeliveryPublisher(self.output_root, self.blobs)
        self.projects = ProjectService(
            self.db.transaction,
            BundledProfiles(),
            self.blobs,
            clock,
            code_reference(),
            self.settings.maximum_file_bytes,
        )
        self.research = ResearchService(self.db.transaction, self.blobs, self.publisher, clock)
        self.publications = PublicationService(
            self.db.transaction,
            self.blobs,
            self.research,
            PptxInspector(),
            clock,
            self.settings.maximum_file_bytes,
        )
        self.queries = QueryService(self.db.transaction, self.blobs)
        self.reading = ReadingService(
            self.db.transaction, ReadingRoomPublisher(self.output_root, self.blobs, self.root)
        )
        self.worker = AcquisitionWorker(
            self.db.transaction,
            self.db,
            self.blobs,
            installed,
            DocumentExtractor(),
            clock,
            self.settings.lease_seconds,
        )
        self.delivery = DeliveryService(
            self.db.transaction, self.research, self.publisher, self.blobs, clock
        )

    def doctor(self) -> dict[str, Any]:
        with self.db.transaction(None) as repo:
            run_count = len(repo.list_runs())
        return dict(
            platform_version=__version__,
            sqlite_version=sqlite3.sqlite_version,
            schema_revision=self.db.schema_revision(),
            workspace=str(self.root),
            data_root=str(self.data_root),
            outputs=str(self.output_root),
            run_count=run_count,
            dependencies={
                n: version(n)
                for n in ("pydantic", "sqlalchemy", "alembic", "httpx", "jinja2", "pypdf")
            },
            capabilities={
                "local_documents": "implemented",
                "http_documents": "implemented",
                "conference_pairing": "implemented_pending_live_validation",
                "youtube": "paired_original_slides; public_timed_captions; sampled_frames_with_optional_media_extra_and_ffmpeg; full_talk_analysis_requires_research_review",
                "x": "authorized_API_window_and_public_single_post_samples; live_success_is_source_specific",
                "feeds": "RSS_Atom_discovery_snapshot; not_complete_account_history",
                "collection_requirements": "independent_project_channels_required_for_new_revisions",
                "browser_assisted": "explicit_observation_receipt_import; visible_public_post_samples_and_timed_captions; no_cookie_or_API_window_reuse",
                "local_asr": "optional_speech_extra_and_explicit_local_model; budgeted_offline_CPU_transcription_of_acquired_media",
                "ocr": "not_enabled",
                "analysis": "interactive_file_exchange",
                "narrative_report": "structured_sections_tables_diagrams_charts",
                "original_pdf_figures": "available"
                if shutil.which("pdftoppm")
                else "pdftoppm_not_configured",
                "monitoring": "not_enabled",
            },
        )

    def export_schemas(self) -> str:
        target = self.output_root / "platform" / "schemas" / "v1"
        for name in (
            "ProjectSpec",
            "Source",
            "LocalImportRequest",
            "PlanSpec",
            "EvidenceInput",
            "ContextRequest",
            "AnalysisSubmission",
            "VerificationSubmission",
            "ReviewSubmission",
            "ContextSnapshot",
        ):
            model = getattr(contracts, name)
            atomic_write(
                target / (name + ".json"),
                json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2).encode(),
            )
        atomic_write(
            target / "PublicationRequest.json",
            json.dumps(
                PublicationRequest.model_json_schema(), ensure_ascii=False, indent=2
            ).encode(),
        )
        for model in (BrowserImportRequest, BrowserCaptureBundle):
            atomic_write(
                target / (model.__name__ + ".json"),
                json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2).encode(),
            )
        return str(target)

    def close(self) -> None:
        self.http.close()
        self.x_posts.close()
        self.db.close()

    def set_credential(self, reference: str, value: str) -> None:
        OperatingSystemSecrets().set(reference, value)

    def credential_present(self, reference: str) -> bool:
        return bool(OperatingSystemSecrets().get(reference))
