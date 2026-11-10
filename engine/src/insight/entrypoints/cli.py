from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from insight.bootstrap import Application, initialize_workspace
from insight.domain.captures import BrowserImportRequest
from insight.domain.contracts import (
    AnalysisSubmission,
    ContextRequest,
    Contract,
    EvidenceInput,
    LocalImportRequest,
    PlanSpec,
    PlatformError,
    ProjectSpec,
    ReviewSubmission,
    Source,
    VerificationSubmission,
)
from insight.domain.publications import PublicationRequest


def load[T: Contract](path: str, model: type[T]) -> T:
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise PlatformError("INVALID_SPEC", "Explicit schema_version: 1 is required")
    return model.model_validate_json(raw)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="insight", description="Evidence-based personal research workspace"
    )
    p.add_argument("--workspace", required=True, type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    for name in (
        "init",
        "doctor",
        "schemas",
        "reconcile",
        "reading-room",
        "collectors",
    ):
        sub.add_parser(name)
    project = sub.add_parser("project")
    project.add_argument("--file", required=True)
    project.add_argument("--expected-revision", type=int, default=0)
    for name in (
        "source-register",
        "source-import",
        "plan",
        "analysis",
        "verification",
        "review",
        "publication-register",
    ):
        sub.add_parser(name).add_argument("--file", required=True)
    local = sub.add_parser("source-local")
    for flag in ("id", "file", "publisher", "provenance"):
        local.add_argument("--" + flag, required=True)
    run = sub.add_parser("run")
    run.add_argument("--plan", required=True)
    run.add_argument("--key")
    worker = sub.add_parser("worker")
    worker.add_argument("--max-jobs", type=int, default=1)
    status = sub.add_parser("status")
    status.add_argument("--run")
    document = sub.add_parser("document")
    document.add_argument("--run", required=True)
    document.add_argument("--version", required=True)
    image = sub.add_parser("source-image")
    image.add_argument("--run", required=True)
    image.add_argument("--version", required=True)
    image.add_argument("--index", type=int)
    for name in ("evidence", "context"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--run", required=True)
        cmd.add_argument("--file", required=True)
    for name in ("quality", "deliver", "resume", "cancel"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--run", required=True)
        if name == "deliver":
            cmd.add_argument("--draft", action="store_true")
    record = sub.add_parser("record-execution")
    record.add_argument("--run", required=True)
    record.add_argument("--kind", required=True)
    record.add_argument("--file", required=True)
    sub.add_parser("verify-delivery").add_argument("--path", required=True)
    sub.add_parser("verify-publication").add_argument("--id", required=True)
    sub.add_parser("collector-preflight").add_argument("--plan", required=True)
    sub.add_parser("capture-import").add_argument("--file", required=True)
    sub.add_parser("media-setup-asr").add_argument(
        "--model", choices=("tiny.en", "tiny", "base.en", "base"), required=True
    )
    probe = sub.add_parser("collector-probe")
    probe.add_argument("--run", required=True)
    probe.add_argument("--source", required=True)
    for name in ("credential-set", "credential-check"):
        sub.add_parser(name).add_argument("--ref", required=True)
    return p


def dispatch(app: Application, a: argparse.Namespace) -> Any:
    match a.command:
        case "source-image":
            from insight.application.source_images import source_images

            return source_images(app, a.run, a.version, a.index)
        case "record-execution":
            payload = json.loads(Path(a.file).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise PlatformError(
                    "INVALID_SPEC", "Execution payload must be an object"
                )
            app.research.record_execution(a.run, a.kind, payload)
            return {"recorded": True}
        case "media-setup-asr":
            return app.collectors.setup_asr(a.model)
        case "capture-import":
            return app.captures.import_capture(load(a.file, BrowserImportRequest))
        case "collectors":
            return app.collectors.catalog()
        case "collector-preflight":
            return app.collectors.preflight(a.plan)
        case "collector-probe":
            return app.collectors.probe(a.run, a.source)
        case "credential-check":
            return dict(
                configured=app.credential_present(a.ref), live_access="not_checked"
            )
        case "credential-set":
            if not sys.stdin.isatty():
                raise PlatformError(
                    "INVALID_SPEC",
                    "Run credential-set in your local interactive terminal; never put secrets in JSON, chat or command arguments",
                )
            app.set_credential(
                a.ref, getpass.getpass("API token (hidden, saved to OS keyring): ")
            )
            return dict(saved=True)
        case "publication-register":
            return app.publications.register(load(a.file, PublicationRequest))
        case "verify-publication":
            return app.publications.verify(a.id)
        case "doctor":
            return app.doctor()
        case "reading-room":
            return app.reading.publish()
        case "schemas":
            return {"schema_directory": app.export_schemas()}
        case "project":
            return app.projects.define_project(
                load(a.file, ProjectSpec), a.expected_revision
            )
        case "source-local":
            return app.projects.import_local(a.id, a.file, a.publisher, a.provenance)
        case "source-register":
            return app.projects.register_source(load(a.file, Source))
        case "source-import":
            local_request = load(a.file, LocalImportRequest)
            return app.projects.import_local(
                local_request.source_id,
                local_request.native_path,
                local_request.publisher,
                local_request.provenance,
                local_request.origin,
                local_request.material_role,
            )
        case "plan":
            return app.projects.freeze_source_plan(load(a.file, PlanSpec))
        case "run":
            return app.projects.start_run(a.plan, a.key)
        case "worker":
            if not 1 <= a.max_jobs <= 100:
                raise PlatformError(
                    "INVALID_SPEC", "Worker job bound must be between 1 and 100"
                )
            processed = []
            for _ in range(a.max_jobs):
                run_id = app.worker.run_once()
                if run_id is None:
                    break
                processed.append(run_id)
            return {"processed_runs": processed}
        case "status":
            return app.queries.inspect_run(a.run) if a.run else app.queries.list_runs()
        case "document":
            return app.queries.document(a.run, a.version)
        case "evidence":
            return app.research.add_evidence(a.run, load(a.file, EvidenceInput))
        case "context":
            request = load(a.file, ContextRequest)
            return app.research.prepare_context(
                a.run, request.coverage, request.excluded_or_truncated
            )
        case "analysis":
            return app.research.submit_analysis(load(a.file, AnalysisSubmission))
        case "verification":
            app.research.submit_verification(load(a.file, VerificationSubmission))
            return {"recorded": True}
        case "quality":
            return app.research.evaluate(a.run)
        case "review":
            app.research.record_review(load(a.file, ReviewSubmission))
            return {"recorded": True}
        case "deliver":
            return app.delivery.assemble_delivery(a.run, allow_draft=a.draft)
        case "verify-delivery":
            return app.publisher.verify(a.path)
        case "resume":
            app.projects.resume_run(a.run)
            return {"queued": True}
        case "cancel":
            app.projects.cancel_run(a.run)
            return {"cancel_requested": True}
        case "reconcile":
            return {"project_entries_rebuilt": app.delivery.reconcile_outputs()}
        case _:
            raise PlatformError("INVALID_SPEC", "Unknown operation")


def json_default(value: Any) -> Any:
    if isinstance(value, Contract):
        return value.model_dump(mode="json")
    raise TypeError(type(value).__name__)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    a = parser().parse_args()
    app = None
    try:
        if a.command == "init":
            result = initialize_workspace(a.workspace)
        else:
            app = Application(a.workspace)
            result = dispatch(app, a)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default))
        return 0
    except (ValidationError, PlatformError, OSError, ValueError, KeyError) as exc:
        code = exc.code if isinstance(exc, PlatformError) else "INVALID_SPEC"
        detail = exc.detail if isinstance(exc, PlatformError) else str(exc)
        print(
            json.dumps({"error": {"code": code, "detail": detail}}, ensure_ascii=False)
        )
        return 2
    finally:
        if app:
            app.close()


if __name__ == "__main__":
    raise SystemExit(main())
