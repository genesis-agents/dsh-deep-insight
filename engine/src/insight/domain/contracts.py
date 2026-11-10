"""Version 1 contracts. JSON schemas are exported from these strict models."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Nonempty = Annotated[str, Field(min_length=1, max_length=20000, pattern=r"\S")]
ProviderName = Literal["local", "http", "conference", "youtube", "x", "feed", "browser"]
SourceChannel = Literal["official", "paper", "conference", "youtube", "x", "feed", "local"]
GoalState = Literal["met", "not_met", "unknown"]
JobState = Literal[
    "queued",
    "leased",
    "running",
    "waiting_input",
    "retry_scheduled",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
]
QualityState = Literal["draft", "evidence_incomplete", "machine_verified", "reviewed"]
MaterialRole = Literal[
    "raw_document",
    "original_slides",
    "extracted_text",
    "source_metadata",
    "post",
    "transcript",
    "derived_slide_frames",
    "reconstructed_deck",
    "raw_video",
    "raw_audio",
    "browser_capture",
]


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def version_is_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value


def public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise ValueError("Expected an absolute HTTP(S) URL")
    secret_keys = {
        "api_key",
        "apikey",
        "access_token",
        "token",
        "authorization",
        "signature",
        "x-amz-signature",
        "x-amz-credential",
    }
    if (
        parsed.username
        or parsed.password
        or any(k.lower() in secret_keys for k, _ in parse_qsl(parsed.query))
    ):
        raise ValueError(
            "Do not persist credentials or signed secret URLs; use a credential reference or explicit local import"
        )
    return value


class Scope(Contract):
    regions: tuple[Nonempty, ...]
    as_of: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    exclusions: tuple[Nonempty, ...] = ()
    since: str | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def ordered_interval(self) -> Scope:
        if self.since and date.fromisoformat(self.since) > date.fromisoformat(self.as_of):
            raise ValueError("Research start must not follow its cutoff")
        return self

    @field_validator("as_of")
    @classmethod
    def valid_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class Profile(Contract):
    profile_id: Id
    version: Annotated[int, Field(ge=1)]
    dimensions: tuple[Nonempty, ...]
    review_checks: tuple[Nonempty, ...]


class ChannelRequirement(Contract):
    channel: SourceChannel
    disposition: Literal["required", "optional", "excluded"]
    goals: tuple[Nonempty, ...] = ()
    rationale: Nonempty


class SourceOrigin(Contract):
    channel: SourceChannel
    publication_url: str | None = None
    publication_status: Literal[
        "preprint", "peer_reviewed", "technical_report", "conference_presentation", "unknown"
    ] = "unknown"

    @field_validator("publication_url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        return public_url(value) if value else value


class ResearchStandard(Contract):
    """Frozen project requirements; completeness is assessed against these explicit choices."""

    min_supporting_groups: Annotated[int, Field(ge=1, le=20)] = 2
    require_publication_dates: bool = True
    require_search_record: bool = True
    require_isolated_review: bool = True
    require_report_composition: bool = Field(default=True, exclude_if=lambda v: v is True)
    rationale: Nonempty


class ProjectSpec(Contract):
    project_id: Id
    question: Nonempty
    decision: Nonempty
    scope: Scope
    profile_ref: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+@[1-9][0-9]*$")]
    subquestions: Annotated[tuple[Nonempty, ...], Field(min_length=1)]
    quality_standard: ResearchStandard | None = Field(default=None, exclude_if=lambda v: v is None)
    collection_requirements: tuple[ChannelRequirement, ...] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def unique_channels(self) -> ProjectSpec:
        if self.collection_requirements is not None:
            channels = [r.channel for r in self.collection_requirements]
            if not channels or len(channels) != len(set(channels)):
                raise ValueError("Declare each collection channel once")
        return self


class ProjectRevision(ProjectSpec):
    revision: Annotated[int, Field(ge=1)]


class StagedCaptureAttachment(Contract):
    uri: Nonempty
    sha256: Digest
    media_type: Literal["image/png", "text/plain", "application/json"]

    @field_validator("uri")
    @classmethod
    def inbox_uri(cls, value: str) -> str:
        if not value.startswith("inbox://"):
            raise ValueError("Capture attachments must use portable inbox URIs")
        return value


class Source(Contract):
    title: Nonempty | None = Field(default=None, exclude_if=lambda v: v is None)
    independence_group: Nonempty | None = Field(default=None, exclude_if=lambda v: v is None)
    declared_material_role: (
        Literal["raw_document", "original_slides", "raw_audio", "raw_video"] | None
    ) = Field(default=None, exclude_if=lambda v: v is None)
    source_id: Id
    provider: ProviderName
    canonical_identity: Nonempty
    resource_uri: Nonempty
    publisher: Nonempty
    identity_status: Literal["user_provided", "needs_verification", "verified"]
    identity_basis: Annotated[tuple[Nonempty, ...], Field(min_length=1)]
    credential_ref: str | None = None
    origin: SourceOrigin | None = Field(default=None, exclude_if=lambda v: v is None)
    capture_uri: str | None = Field(default=None, exclude_if=lambda v: v is None)
    capture_attachments: tuple[StagedCaptureAttachment, ...] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def identity_constraints(self) -> Source:
        if self.provider == "local" and not self.resource_uri.startswith("inbox://"):
            raise ValueError("local sources must use workspace inbox logical URIs")
        if self.provider != "local" and not self.resource_uri.startswith(("https://", "http://")):
            raise ValueError("remote sources require HTTP(S) URLs")
        if self.credential_ref and not self.credential_ref.startswith("credential://"):
            raise ValueError("store only credential references")
        if self.provider != "local":
            public_url(self.resource_uri)
        if self.capture_uri and not self.capture_uri.startswith("inbox://"):
            raise ValueError("Browser captures use a portable inbox URI")
        return self


class LocalImportRequest(Contract):
    source_id: Id
    native_path: Nonempty
    publisher: Nonempty
    provenance: Nonempty
    origin: SourceOrigin | None = None
    material_role: Literal["raw_document", "original_slides", "raw_audio", "raw_video"] | None = (
        None
    )


class Window(Contract):
    start: str | None = None
    end: Nonempty


class Limits(Contract):
    media_model_calls: Annotated[int, Field(ge=0, le=100)] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    network_requests: Annotated[int, Field(ge=0, le=10000)] = 20
    source_bytes: Annotated[int, Field(ge=1, le=1_000_000_000)] = 50_000_000
    model_calls: Annotated[int, Field(ge=0, le=1000)] = 0
    context_characters: Annotated[int, Field(ge=100, le=500000)] = 60000


class MediaOptions(Contract):
    asr_model: Literal["tiny.en", "tiny", "base.en", "base"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    asr_model_sha256: Digest | None = Field(default=None, exclude_if=lambda v: v is None)
    languages: Annotated[tuple[Nonempty, ...], Field(min_length=1, max_length=8)] = (
        "en",
        "zh-Hans",
        "zh",
    )
    maximum_bytes: Annotated[int, Field(ge=10000, le=250_000_000)] = 45_000_000
    maximum_seconds: Annotated[int, Field(ge=1, le=14400)] = 7200
    frame_interval_seconds: Annotated[int, Field(ge=5, le=600)] = 30
    maximum_frames: Annotated[int, Field(ge=1, le=240)] = 120
    allow_generated_captions: bool = True


class SourcePlanItem(Contract):
    source_ref: Id
    goal: Literal[
        "document_text",
        "slides_only",
        "editable_original_pptx",
        "metadata",
        "full_talk_analysis",
        "latest_posts",
        "video_transcript",
        "video_frames",
        "public_post",
        "discover_updates",
        "observed_posts",
    ]
    required: bool = True
    accepted_material_roles: Annotated[tuple[MaterialRole, ...], Field(min_length=1)]
    requested_window: Window
    access_mode: Literal["user_file", "public_http", "authorized_api", "browser_assisted"]
    completion_rule: Nonempty
    freshness_rule: Nonempty
    pairing_page: str | None = None
    material_url: str | None = None
    page_budget: Annotated[int, Field(ge=1, le=100)] = 3
    post_scope: Literal["body_and_link_metadata"] | None = None
    exclude_replies: bool = False
    exclude_reposts: bool = False
    media: MediaOptions | None = Field(default=None, exclude_if=lambda v: v is None)
    minimum_text_characters: Annotated[int, Field(ge=80, le=100000)] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def explicit_post_scope(self) -> SourcePlanItem:
        for url in (self.pairing_page, self.material_url):
            if url:
                public_url(url)
        if self.goal == "latest_posts" and (
            self.post_scope is None
            or self.requested_window.start is None
            or self.access_mode != "authorized_api"
        ):
            raise ValueError(
                "X plans require explicit body scope, frozen start/end and authorized_api mode"
            )
        return self


class PlanSpec(Contract):
    plan_id: Id
    project_id: Id
    project_revision: Annotated[int, Field(ge=1)]
    items: Annotated[tuple[SourcePlanItem, ...], Field(min_length=1)]
    limits: Limits = Limits()

    @model_validator(mode="after")
    def unique_sources(self) -> PlanSpec:
        refs = [i.source_ref for i in self.items]
        if len(refs) != len(set(refs)):
            raise ValueError("a source may occur only once per plan")
        return self


class FrozenInput(Contract):
    project: ProjectRevision
    plan: PlanSpec
    profile: Profile
    sources: tuple[Source, ...]
    code_ref: str
    workflow_ref: Literal["evidence-research@1"] = "evidence-research@1"


class GoalResult(Contract):
    state: GoalState
    reason_code: Nonempty
    detail: Nonempty


class Artifact(Contract):
    artifact_id: Id
    sha256: Digest
    media_type: Nonempty
    size: Annotated[int, Field(ge=0)]
    role: MaterialRole
    producer_ref: Nonempty


class TextUnit(Contract):
    index: Annotated[int, Field(ge=1)]
    kind: Literal["page", "slide", "document", "post", "metadata", "transcript_segment"]
    text: str
    start_seconds: Annotated[float, Field(ge=0)] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    end_seconds: Annotated[float, Field(ge=0)] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )


class ExtractedDocument(Contract):
    processor_ref: Nonempty
    units: tuple[TextUnit, ...]
    warnings: tuple[str, ...] = ()


class Derivation(Contract):
    derivation_id: Id
    input_artifact_id: Id
    output_artifact_id: Id
    processor_ref: Nonempty
    parameters_hash: Digest


class SourceVersion(Contract):
    version_id: Id
    run_id: Id
    source_id: Id
    raw_artifact_id: Id
    extracted_artifact_id: Id | None
    acquired_at: Nonempty
    origin_uri: Nonempty
    published_at: str | None = None


class Observation(Contract):
    source_id: Id
    goal_result: GoalResult
    requested_window: Window
    observed_window: Window | None = None
    pagination_complete: bool = False
    coverage_notes: tuple[str, ...] = ()
    checkpoint: dict[str, str | int | bool | None] = Field(default_factory=dict)


class Locator(Contract):
    unit_index: Annotated[int, Field(ge=1)]
    char_start: Annotated[int, Field(ge=0)]
    char_end: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def positive_range(self) -> Locator:
        if self.char_end <= self.char_start:
            raise ValueError("empty or reversed locator")
        return self


class VisualPageLocator(Contract):
    unit_index: Annotated[int, Field(ge=1)]
    modality: Literal["visual_page"]
    observer: Nonempty
    limitations: Nonempty


class EvidenceInput(Contract):
    source_version_id: Id
    artifact_id: Id
    locator: Locator | VisualPageLocator
    quote: Nonempty


class EvidenceSpan(EvidenceInput):
    evidence_id: Id
    run_id: Id
    context: str
    normalization_ref: Literal["unicode-exact@1", "visual-observation@1"] = "unicode-exact@1"
    start_seconds: float | None = Field(default=None, exclude_if=lambda v: v is None)
    end_seconds: float | None = Field(default=None, exclude_if=lambda v: v is None)


class CoverageItem(Contract):
    subquestion: Nonempty
    evidence_ids: tuple[Id, ...]
    unresolved: str | None = None

    @model_validator(mode="after")
    def coverage_or_gap(self) -> CoverageItem:
        if not self.evidence_ids and not self.unresolved:
            raise ValueError("uncovered subquestion must disclose its gap")
        return self


class ContextRequest(Contract):
    coverage: Annotated[tuple[CoverageItem, ...], Field(min_length=1)]
    excluded_or_truncated: tuple[Nonempty, ...] = ()


class EvidenceLink(Contract):
    evidence_id: Id
    relation: Literal["supports", "contradicts", "context"]


class Claim(Contract):
    claim_id: Id
    kind: Literal["source_claim", "observation", "inference", "hypothesis"]
    statement: Nonempty
    conditions: Annotated[tuple[Nonempty, ...], Field(min_length=1)]
    evidence_links: Annotated[tuple[EvidenceLink, ...], Field(min_length=1)]
    counterevidence: tuple[Nonempty, ...] = ()
    category: Literal["technical", "provenance"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )


class Attribution(Contract):
    mode: Literal["interactive_model", "human", "model_api"]
    name: Nonempty
    model: str | None = None
    notes: Nonempty


ClaimRefs = Annotated[tuple[Id, ...], Field(min_length=1, max_length=30)]


class ReportParagraph(Contract):
    kind: Literal["paragraph"] = "paragraph"
    text: Nonempty
    claim_ids: ClaimRefs


class ReportRow(Contract):
    cells: Annotated[tuple[Nonempty, ...], Field(min_length=1, max_length=8)]
    claim_ids: ClaimRefs


class ReportTable(Contract):
    kind: Literal["table"] = "table"
    caption: Nonempty
    columns: Annotated[tuple[Nonempty, ...], Field(min_length=2, max_length=8)]
    rows: Annotated[tuple[ReportRow, ...], Field(min_length=1, max_length=30)]

    @model_validator(mode="after")
    def rectangular(self) -> ReportTable:
        if any(len(row.cells) != len(self.columns) for row in self.rows):
            raise ValueError("Every report row must match the table columns")
        return self


class DiagramNode(Contract):
    node_id: Id
    label: Nonempty
    detail: Annotated[str, Field(max_length=180)] = ""
    column: Annotated[int, Field(ge=0, le=3)]
    row: Annotated[int, Field(ge=0, le=5)]


class DiagramEdge(Contract):
    source: Id
    target: Id
    label: Annotated[str, Field(max_length=50)] = ""


class ReportDiagram(Contract):
    kind: Literal["diagram"] = "diagram"
    caption: Nonempty
    nodes: Annotated[tuple[DiagramNode, ...], Field(min_length=2, max_length=12)]
    edges: Annotated[tuple[DiagramEdge, ...], Field(min_length=1, max_length=20)]
    note: Nonempty
    claim_ids: ClaimRefs

    @model_validator(mode="after")
    def valid_graph(self) -> ReportDiagram:
        ids = {node.node_id for node in self.nodes}
        cells = {(node.column, node.row) for node in self.nodes}
        if len(ids) != len(self.nodes) or len(cells) != len(self.nodes):
            raise ValueError("Diagram nodes need unique IDs and grid cells")
        if any(
            e.source not in ids or e.target not in ids or e.source == e.target for e in self.edges
        ):
            raise ValueError("Diagram edges must connect distinct existing nodes")
        return self


class ChartPoint(Contract):
    label: Nonempty
    value: Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)]


class ReportChart(Contract):
    kind: Literal["chart"] = "chart"
    caption: Nonempty
    unit: Nonempty
    points: Annotated[tuple[ChartPoint, ...], Field(min_length=2, max_length=10)]
    reference: Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)] | None = None
    reference_label: str | None = None
    note: Nonempty
    claim_ids: ClaimRefs

    @model_validator(mode="after")
    def labeled_reference(self) -> ReportChart:
        if self.reference is not None and not self.reference_label:
            raise ValueError("A chart reference line needs an explicit label")
        return self


class ReportFigure(Contract):
    kind: Literal["figure"] = "figure"
    caption: Nonempty
    source_version_id: Id
    image_artifact_id: Id | None = Field(default=None, exclude_if=lambda v: v is None)
    unit_index: Annotated[int, Field(ge=1, le=10000)]
    explanation: Nonempty
    reading_note: Nonempty
    claim_ids: ClaimRefs


ReportBlock = Annotated[
    ReportParagraph | ReportTable | ReportDiagram | ReportChart | ReportFigure,
    Field(discriminator="kind"),
]


class ReportSection(Contract):
    section_id: Id
    question: Nonempty
    answer: Nonempty
    bridge: Nonempty
    claim_ids: ClaimRefs
    blocks: Annotated[tuple[ReportBlock, ...], Field(min_length=1, max_length=20)]


class ReportTakeaway(Contract):
    text: Nonempty
    claim_ids: ClaimRefs


class ResearchNarrative(Contract):
    headline: Nonempty
    standfirst: Nonempty
    takeaways: Annotated[tuple[ReportTakeaway, ...], Field(min_length=1, max_length=5)]
    sections: Annotated[tuple[ReportSection, ...], Field(min_length=1, max_length=12)]
    conclusion: ReportTakeaway | None = Field(default=None, exclude_if=lambda v: v is None)
    recommendations: tuple[ReportTakeaway, ...] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def unique_sections(self) -> ResearchNarrative:
        if len({s.section_id for s in self.sections}) != len(self.sections):
            raise ValueError("Report section IDs must be unique")
        if sum(isinstance(b, ReportFigure) for s in self.sections for b in s.blocks) > 12:
            raise ValueError("At most twelve original-page figures per narrative")
        return self

    def referenced_claims(self) -> set[str]:
        refs = {c for t in self.takeaways for c in t.claim_ids}
        if self.conclusion:
            refs.update(self.conclusion.claim_ids)
        for recommendation in self.recommendations or ():
            refs.update(recommendation.claim_ids)
        for section in self.sections:
            refs.update(section.claim_ids)
            for block in section.blocks:
                if isinstance(block, ReportTable):
                    refs.update(c for row in block.rows for c in row.claim_ids)
                else:
                    refs.update(block.claim_ids)
        return refs


class AnalysisSubmission(Contract):
    run_id: Id
    context_fingerprint: Digest
    producer: Attribution
    title: Nonempty
    synthesis: Nonempty
    claims: Annotated[tuple[Claim, ...], Field(min_length=1)]
    coverage: Annotated[tuple[CoverageItem, ...], Field(min_length=1)]
    limitations: tuple[Nonempty, ...]
    # An absent narrative must serialize exactly like the original v1 contract,
    # preserving stored analysis, verification and review fingerprints.
    narrative: ResearchNarrative | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def distinct_claims(self) -> AnalysisSubmission:
        ids = [c.claim_id for c in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate claim IDs")
        if self.narrative and not self.narrative.referenced_claims() <= set(ids):
            raise ValueError("Narrative references an unknown analysis claim")
        return self


class SemanticCheck(Contract):
    claim_id: Id
    verdict: Literal["supported", "contradicted", "unclear"]
    rationale: Nonempty


class VerificationSubmission(Contract):
    run_id: Id
    analysis_fingerprint: Digest
    verifier: Attribution
    checks: Annotated[tuple[SemanticCheck, ...], Field(min_length=1)]
    execution_ref: Id | None = Field(default=None, exclude_if=lambda v: v is None)


class ReviewSubmission(Contract):
    run_id: Id
    basis_fingerprint: Digest
    reviewer: Nonempty
    checked_items: Annotated[tuple[Nonempty, ...], Field(min_length=1)]
    decision: Literal["accepted", "changes_requested"]
    notes: Nonempty


class GateResult(Contract):
    gate_id: Id
    state: Literal["passed", "failed", "not_performed"]
    detail: Nonempty


class Lease(Contract):
    job_id: Id
    run_id: Id
    owner: Id
    token: Annotated[int, Field(ge=1)]


class RunView(Contract):
    run_id: Id
    project_id: Id
    execution_state: JobState
    stage: str
    quality_state: QualityState
    job_id: Id
    goal_results: tuple[Observation, ...] = ()
    gates: tuple[GateResult, ...] = ()
    delivery_ref: str | None = None
    waiting_reason: str | None = None


class ContextSnapshot(Contract):
    run_id: Id
    input_fingerprint: Digest
    evidence: tuple[EvidenceSpan, ...]
    coverage: tuple[CoverageItem, ...]
    excluded_or_truncated: tuple[Nonempty, ...]
    full_document_reading_claimed: Literal[False] = False


class DeliveryRecord(Contract):
    delivery_id: Id
    run_id: Id
    project_id: Id
    relative_path: Nonempty
    basis_fingerprint: Digest
    manifest_hash: Digest
    quality_state: QualityState
    created_at: Nonempty


class PlatformError(Exception):
    def __init__(self, code: str, detail: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds
