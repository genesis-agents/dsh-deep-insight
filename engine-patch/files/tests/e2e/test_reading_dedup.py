"""Repeated acquisitions share readable materials without removing their audit records."""

import json
import shutil
from pathlib import Path

from insight.domain.rules import fingerprint
from tests.e2e.test_reading_room import assert_local_links, edition_path
from tests.helpers import start_case


def test_identical_acquisitions_share_material_and_archive_legacy_view(app, tmp_path):
    start_case(app, tmp_path)
    first = app.reading.publish()
    edition = edition_path(app, first)
    record_path = next((edition / "资料库").rglob("来源记录.json"))
    record = json.loads(record_path.read_bytes())
    first_material = record_path.parent
    material_relative = first_material.relative_to(edition / "资料库")
    user_root = app.root / "01-研究项目" / "sample" / "02-原始资料"
    current = user_root / material_relative
    legacy = current.with_name(
        current.name.rsplit("--", 1)[0]
        + "--"
        + fingerprint(record["version"]["version_id"])[:16]
    )
    shutil.copytree(current, legacy)
    (legacy / "owner-note.txt").write_text(
        "Retain this edited derived copy", encoding="utf-8"
    )
    app.projects.start_run("plan_sample")
    app.worker.run_once()
    second = app.reading.publish()
    assert second["materials"] == first["materials"] == 1
    assert len(list((edition_path(app, second) / "资料库").rglob("来源记录.json"))) == 1
    assert len(list(current.glob("acquisitions/*.json"))) == 2
    assert not legacy.exists()
    archived = list(
        (app.output_root / "reading-room" / "superseded-material-views").rglob(
            "owner-note.txt"
        )
    )
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == "Retain this edited derived copy"
    assert first_material.exists()
    assert_local_links(edition_path(app, second))
    assert_local_links(app.root / "01-研究项目")
    assert app.reading.publish()["edition"] == second["edition"]


def test_changed_material_remains_a_distinct_version(app, tmp_path):
    run_id = start_case(app, tmp_path)
    first = app.reading.publish()
    Path(tmp_path / "sample.txt").write_text(
        "A different synthetic observation", encoding="utf-8"
    )
    source = app.projects.import_local(
        "source_updated",
        str(tmp_path / "sample.txt"),
        "Synthetic fixture author",
        "Updated synthetic fixture",
    )
    with app.db.transaction(None) as repo:
        original = repo.frozen_input(run_id).plan
    plan = original.model_copy(
        update={
            "plan_id": "updated-plan",
            "items": (
                original.items[0].model_copy(update={"source_ref": source.source_id}),
            ),
        }
    )
    app.projects.freeze_source_plan(plan)
    app.projects.start_run(plan.plan_id)
    app.worker.run_once()
    second = app.reading.publish()
    assert second["materials"] == first["materials"] + 1
    assert_local_links(edition_path(app, second))


def test_equal_bytes_from_different_projects_keep_their_own_sources(app, tmp_path):
    start_case(app, tmp_path, project_id="first", content="Shared synthetic bytes")
    start_case(app, tmp_path, project_id="second", content="Shared synthetic bytes")
    result = app.reading.publish()
    assert result["materials"] == 2
    assert_local_links(edition_path(app, result))
