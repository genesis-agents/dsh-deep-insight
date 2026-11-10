from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader, select_autoescape

from insight.adapters.export.narrative import (
    narrative_markdown,
    render_pdf_page,
    report_view,
)
from insight.adapters.export.reading_html import collection_table
from insight.adapters.persistence.objects import atomic_write, native_path
from insight.domain.contracts import Artifact, DeliveryRecord, PlatformError
from insight.domain.rules import canonical
from insight.ports.storage import BlobStore


class HtmlDeliveryPublisher:
    def __init__(self, output_root: Path, blobs: BlobStore) -> None:
        self.root, self.blobs = output_root.resolve(), blobs
        self.env = Environment(
            loader=FileSystemLoader(Path(__file__).parent / "templates"),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def prepare(
        self, package: dict[str, Any], artifacts: tuple[Artifact, ...]
    ) -> DeliveryRecord:
        relative = (
            Path("projects")
            / package["project_id"]
            / "deliveries"
            / package["delivery_id"]
        )
        target = native_path(self.root / relative)
        if target.exists():
            raise PlatformError("REVISION_CONFLICT", "Delivery already exists")
        temporary = native_path(self.root / ".staging" / uuid4().hex)
        temporary.mkdir(parents=True, exist_ok=False)
        files: dict[str, tuple[bytes, str]] = {}
        material_map: dict[str, str] = {}
        extensions = {
            "application/pdf": ".pdf",
            "application/json": ".json",
            "text/plain": ".txt",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        }
        for artifact in artifacts:
            name = (
                "materials/"
                + artifact.artifact_id
                + extensions.get(artifact.media_type, ".bin")
            )
            files[name] = (self.blobs.read(artifact), artifact.role)
            material_map[artifact.artifact_id] = name
        package = {**package, "materials": material_map}
        figure_map: dict[str, str] = {}
        narrative = package["analysis"].get("narrative")
        if narrative:
            versions = {v["version_id"]: v for v in package["source_versions"]}
            by_id = {a.artifact_id: a for a in artifacts}
            for section in narrative["sections"]:
                for block in section["blocks"]:
                    if block["kind"] != "figure":
                        continue
                    key = block["source_version_id"] + ":" + str(block["unit_index"])
                    if key in figure_map:
                        continue
                    artifact = by_id[
                        block.get("image_artifact_id")
                        or versions[block["source_version_id"]]["raw_artifact_id"]
                    ]
                    if block.get("image_artifact_id"):
                        suffix = (
                            ".png" if artifact.media_type == "image/png" else ".jpg"
                        )
                        name = "figures/" + artifact.artifact_id + suffix
                        files[name] = (self.blobs.read(artifact), "original_figure")
                        figure_map[key] = name
                        continue
                    name = (
                        "figures/"
                        + artifact.artifact_id
                        + "-p"
                        + str(block["unit_index"])
                        + ".png"
                    )
                    files[name] = (
                        render_pdf_page(
                            self.blobs.read(artifact), block["unit_index"], temporary
                        ),
                        "rendered_original_page",
                    )
                    figure_map[key] = name
        package = {**package, "figures": figure_map}
        external = (
            [
                "Archived HTML may reference external visual assets not included in this package"
            ]
            if any(a.media_type == "text/html" for a in artifacts)
            else []
        )
        json_files = {
            "claims.json": package["analysis"],
            "citations.json": package["context"],
            "acquisition.json": {
                "observations": package["observations"],
                "source_versions": package["source_versions"],
            },
            "quality.json": package["quality"],
            "input-snapshot.json": package["frozen_input"],
            "publications.json": package.get("publications", []),
        }
        for name, content in json_files.items():
            files[name] = (canonical(content), name.removesuffix(".json"))
        rendered = self.env.get_template("report.html").render(
            p=package,
            v=report_view(package),
            collection_html=collection_table(
                package.get("quality", {}).get("collection_coverage", {})
            ),
        )
        files["report.html"] = (rendered.encode(), "research_report")
        files["index.html"] = (rendered.encode(), "delivery_entry")
        analysis = package["analysis"]
        files["report.md"] = (narrative_markdown(package).encode(), "readable_report")
        manifest = dict(
            schema_version=1,
            delivery_id=package["delivery_id"],
            run_id=package["run_id"],
            project_id=package["project_id"],
            created_at=package["created_at"],
            basis_fingerprint=package["basis_fingerprint"],
            code_ref=package["frozen_input"]["code_ref"],
            workflow_ref=package["frozen_input"]["workflow_ref"],
            quality_state=package["quality_state"],
            producer=analysis["producer"],
            processor_refs=sorted({a.producer_ref for a in artifacts}),
            exporter_ref="html-narrative@1",
            exporter_hash=hashlib.sha256(
                Path(__file__).read_bytes()
                + Path(__file__).with_name("narrative.py").read_bytes()
            ).hexdigest(),
            template_hash=hashlib.sha256(
                b"".join(
                    (Path(__file__).parent / "templates" / name).read_bytes()
                    for name in ("report.html", "report_blocks.html", "report.css")
                )
            ).hexdigest(),
            figure_provenance=[
                dict(
                    source_version_id=block["source_version_id"],
                    unit_index=block["unit_index"],
                    path=figure_map[
                        block["source_version_id"] + ":" + str(block["unit_index"])
                    ],
                    transform="original image bytes; no visual modification"
                    if block.get("image_artifact_id")
                    else "pdftoppm-png; full original page; maximum side 1800px",
                )
                for section in (narrative or {}).get("sections", [])
                for block in section["blocks"]
                if block["kind"] == "figure"
            ],
            material_scope="Archived original bytes and fixed text derivatives; no OCR or complete visual reading is claimed",
            external_dependencies=external,
            portable=not external,
            files=[
                dict(
                    path=name,
                    role=role,
                    size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )
                for name, (data, role) in sorted(files.items())
            ],
        )
        for name, (data, _) in files.items():
            atomic_write(temporary / name, data)
        manifest_bytes = canonical(manifest)
        atomic_write(temporary / "manifest.json", manifest_bytes)
        digest = hashlib.sha256(manifest_bytes).hexdigest()
        atomic_write(
            temporary / "manifest.sha256", (digest + "  manifest.json\n").encode()
        )
        self._verify_directory(temporary)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, target)
        return DeliveryRecord(
            delivery_id=package["delivery_id"],
            run_id=package["run_id"],
            project_id=package["project_id"],
            relative_path=relative.as_posix(),
            basis_fingerprint=package["basis_fingerprint"],
            manifest_hash=digest,
            quality_state=package["quality_state"],
            created_at=package["created_at"],
        )

    def activate(
        self, record: DeliveryRecord, all_deliveries: tuple[DeliveryRecord, ...]
    ) -> None:
        verified = self.verify(record.relative_path)
        if verified["manifest_hash"] != record.manifest_hash:
            raise PlatformError(
                "EVIDENCE_INVALID", "Registered manifest does not match filesystem"
            )
        project = native_path(self.root / "projects" / record.project_id)
        previous_pointer = (
            (project / "latest.json").read_bytes()
            if (project / "latest.json").exists()
            else None
        )
        previous_index = (
            (project / "index.html").read_bytes()
            if (project / "index.html").exists()
            else None
        )
        project_deliveries = tuple(
            d for d in all_deliveries if d.project_id == record.project_id
        )
        view = self.env.get_template("project.html").render(
            project_id=record.project_id, latest=record, deliveries=project_deliveries
        )
        try:
            # All content already exists. Derived small pointers are repairable from the database.
            atomic_write(project / "index.html", view.encode())
            atomic_write(
                project / "latest.json",
                canonical(
                    {
                        "delivery_id": record.delivery_id,
                        "path": "deliveries/" + record.delivery_id,
                        "manifest_hash": record.manifest_hash,
                    }
                ),
            )
        except OSError:
            for name, old in (
                ("latest.json", previous_pointer),
                ("index.html", previous_index),
            ):
                if old is not None:
                    atomic_write(project / name, old)
                else:
                    (project / name).unlink(missing_ok=True)
            raise
        latest = {d.project_id: d for d in all_deliveries}
        homepage = self.env.get_template("workspace.html").render(
            projects=latest.values(),
            platform_exists=(self.root / "platform" / "index.html").exists(),
        )
        atomic_write(self.root / "index.html", homepage.encode())

    def _verify_directory(self, directory: Path) -> dict[str, Any]:
        directory = native_path(directory)
        payload = (directory / "manifest.json").read_bytes()
        manifest = json.loads(payload)
        digest = hashlib.sha256(payload).hexdigest()
        if (directory / "manifest.sha256").read_text().split()[0] != digest:
            raise PlatformError("EVIDENCE_INVALID", "Manifest checksum mismatch")
        seen: set[str] = set()
        for entry in manifest["files"]:
            name = entry["path"]
            path = (directory / name).resolve()
            if (
                not path.is_relative_to(directory.resolve())
                or name in seen
                or name in ("manifest.json", "manifest.sha256")
            ):
                raise PlatformError(
                    "EVIDENCE_INVALID", "Unsafe or self-referential manifest entry"
                )
            seen.add(name)
            data = path.read_bytes()
            if (
                len(data) != entry["size"]
                or hashlib.sha256(data).hexdigest() != entry["sha256"]
            ):
                raise PlatformError(
                    "EVIDENCE_INVALID", "Delivery file checksum mismatch: " + name
                )
        if (
            not {
                "index.html",
                "report.html",
                "claims.json",
                "citations.json",
                "acquisition.json",
                "quality.json",
            }
            <= seen
        ):
            raise PlatformError("EVIDENCE_INVALID", "Incomplete delivery manifest")
        return {
            "manifest_hash": digest,
            "files_verified": len(seen),
            "portable": manifest["portable"],
            "external_dependencies": manifest["external_dependencies"],
        }

    def verify(self, relative_path: str) -> dict[str, Any]:
        directory = (self.root / relative_path).resolve()
        if not directory.is_relative_to(self.root):
            raise PlatformError("INVALID_SPEC", "Delivery escapes output root")
        return self._verify_directory(directory)

    def export_exchange(
        self, run_id: str, name: Literal["context", "analysis-schema"], data: bytes
    ) -> str:
        digest = hashlib.sha256(data).hexdigest()
        relative = Path("exchange") / run_id / digest / (name + ".json")
        target = native_path(self.root / relative)
        if target.exists() and target.read_bytes() != data:
            raise PlatformError(
                "REVISION_CONFLICT",
                "Immutable exchange file exists with different bytes",
            )
        if not target.exists():
            atomic_write(target, data)
        return relative.as_posix()
