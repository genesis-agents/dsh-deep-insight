"""Render one page belonging to the exact saved source version, including unpublished runs."""
import json
import sys
from pathlib import Path

from insight.adapters.export.narrative import render_pdf_page
from insight.adapters.persistence.objects import atomic_write
from insight.bootstrap import Application
from insight.domain.contracts import PlatformError

app = Application(Path(sys.argv[1]))
try:
    run_id, version_id, page = sys.argv[2], sys.argv[3], int(sys.argv[4])
    document = app.queries.document(run_id, version_id)
    if not any(unit.kind == "page" and unit.index == page for unit in document.units):
        raise PlatformError("SOURCE_PAGE_INVALID", "Page does not belong to this source version")
    with app.queries.tx(None) as repo:
        version = next(item for item in repo.versions(run_id) if item.version_id == version_id)
        artifact = repo.artifact(version.raw_artifact_id)
    data = app.blobs.read(artifact)
    if not data.startswith(b"%PDF-"):
        raise PlatformError("SOURCE_PAGE_UNAVAILABLE", "This original is not a PDF document")
    target = Path(sys.argv[5])
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, render_pdf_page(data, page, target.parent))
    print(json.dumps({"rendered": True}))
except PlatformError as error:
    print(json.dumps({"error": {"code": error.code, "detail": str(error)}}))
    sys.exit(1)
finally:
    app.close()
