"""Read one UI snapshot in one engine process; never mutate research records."""
import json
import sys
from pathlib import Path
from insight.bootstrap import Application
from insight.entrypoints.cli import json_default
from insight.domain.rules import fingerprint
from insight.domain.assessment import assess_research
from snapshot_projection import reader_events

app = Application(Path(sys.argv[1]))
try:
    runs = app.queries.list_runs()
    details = []
    for run in runs[-10:]:
        detail = app.queries.inspect_run(run.run_id)
        # Read through the engine repository port; the UI never parses SQLite.
        with app.queries.tx(None) as repo:
            analysis = repo.analysis(run.run_id)
            verification = repo.verification(run.run_id)
            detail["observations"] = [item.model_dump(mode="json") for item in repo.observations(run.run_id)]
            detail["analysis"] = analysis.model_dump(mode="json") if analysis else None
            current_verification = bool(
                analysis and verification
                and verification.analysis_fingerprint == fingerprint(analysis)
            )
            detail["verification"] = verification.model_dump(mode="json") if current_verification else None
            detail["verification_status"] = "current" if current_verification else "stale" if verification else "missing"
            detail["analysis_fingerprint"] = fingerprint(analysis) if analysis else None
            detail["assessment"] = [g.model_dump(mode="json") for g in assess_research(
                repo.frozen_input(run.run_id), repo.versions(run.run_id), repo.context(run.run_id),
                analysis, verification, repo.events(run.run_id))]
        detail["events"] = reader_events(detail["events"])
        details.append(detail)
    print(json.dumps({
        "runs": runs,
        "details": details,
        "storage": app.doctor(),
    }, ensure_ascii=False, default=json_default))
finally:
    app.close()
