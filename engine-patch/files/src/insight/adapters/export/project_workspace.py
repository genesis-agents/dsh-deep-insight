"""Present the same registered records as project-first folders in Explorer."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

from bs4 import BeautifulSoup
from insight.adapters.export.reading_html import (
    collection_table,
    esc,
    page,
    paragraph,
    relative_link,
    table,
)
from insight.adapters.persistence.objects import atomic_write, native_path
from insight.domain.contracts import PlatformError
from insight.domain.rules import canonical


class ProjectWorkspaceWriter:
    def __init__(self, workspace: Path, outputs: Path) -> None:
        self.workspace, self.outputs = workspace.resolve(), outputs.resolve()

    def _presentation_path(
        self, value: str, project: str, folder: Path, relative_base: Path | None = None
    ) -> Path:
        from pathlib import PureWindowsPath

        if not Path(value).is_absolute() and not PureWindowsPath(value).drive:
            candidate = ((relative_base or folder) / value).resolve()
            if not candidate.is_relative_to(folder):
                raise PlatformError("EVIDENCE_INVALID", "Presentation path escapes project")
            return candidate
        candidate = Path(value).resolve()
        if candidate.is_relative_to(folder):
            return candidate
        # Legacy sidecars contain absolute paths. Map only this workspace's known
        # former project output root; never accept arbitrary external file paths.
        legacy = (self.workspace / "outputs" / "projects" / project / "presentations").resolve()
        if candidate.is_relative_to(legacy):
            return folder / candidate.relative_to(legacy)
        raise PlatformError("EVIDENCE_INVALID", "Presentation path escapes project")

    def publish(
        self,
        files: dict[str, bytes],
        cards: dict[str, dict[str, Any]],
        runs: list[dict[str, Any]],
        edition_base: str,
        project_ids: tuple[str, ...],
        publications: list[dict[str, Any]],
        publication_files: dict[str, dict[str, bytes]],
    ) -> str:
        material_roots = {
            str(PurePosixPath(c["path"]).parent): f"01-研究项目/{c['project']}/02-原始资料/"
            + str(PurePosixPath(c["path"]).parent.relative_to("资料库"))
            for c in cards.values()
        }
        obsolete_material_views: set[Path] = set()
        for card in cards.values():
            material_parent = self.workspace / f"01-研究项目/{card['project']}/02-原始资料"
            for old in card.get("legacy_folders", []):
                candidate = material_parent / PurePosixPath(old).relative_to("资料库")
                if not candidate.resolve().is_relative_to(material_parent.resolve()):
                    raise PlatformError("INVALID_SPEC", "Historical material view escapes project")
                canonical_folder = (
                    self.workspace / material_roots[str(PurePosixPath(card["path"]).parent)]
                )
                if (
                    candidate.resolve() != canonical_folder.resolve()
                    and native_path(candidate).is_dir()
                ):
                    obsolete_material_views.add(candidate)
        run_labels: dict[str, str] = {}
        project_rounds: dict[str, int] = {}
        for run in runs:
            project = run["view"]["project_id"]
            project_rounds[project] = project_rounds.get(project, 0) + 1
            date = run["events"][0]["at"][:10] if run["events"] else "日期未记录"
            run_labels[run["view"]["run_id"]] = f"{date}-第{project_rounds[project]:02d}轮研究"
        paths: dict[str, str] = {}
        for name in files:
            if name == "index.html":
                paths[name] = "02-共享资料索引/index.html"
            elif name == "阅读说明.md":
                paths[name] = "00-工作区说明.md"
            elif name.startswith("资料库/"):
                parent = next(root for root in material_roots if name.startswith(root + "/"))
                paths[name] = (
                    material_roots[parent] + "/" + str(PurePosixPath(name).relative_to(parent))
                )
            else:
                parts = PurePosixPath(name).parts
                project = parts[1]
                root = f"01-研究项目/{project}"
                if len(parts) == 3 and parts[-1] == "index.html":
                    paths[name] = root + "/00-项目概览.html"
                elif len(parts) == 3:
                    paths[name] = root + "/01-研究任务/01-已登记任务.html"
                else:
                    run_id, filename = parts[3], parts[4]
                    stage = filename[:2]
                    category = {
                        "01": "01-研究任务",
                        "02": "01-研究任务",
                        "03": "06-更新记录",
                        "04": "03-证据与摘录",
                        "05": "04-分析与核验",
                        "06": "04-分析与核验",
                        "07": "04-分析与核验",
                        "08": "05-成果交付",
                    }.get(stage, "04-分析与核验")
                    paths[name] = f"{root}/{category}/{run_labels[run_id]}/" + (
                        "00-本轮过程.html" if filename == "index.html" else filename
                    )
        extra: dict[str, bytes] = {}
        external_links: dict[str, str] = {}
        supplementary: dict[str, list[str]] = {}
        publication_modes: dict[str, str] = {}
        all_deliveries = [d for r in runs for d in r["deliveries"]]
        latest_reports = {
            p: max(
                (d for d in all_deliveries if d["project_id"] == p),
                key=lambda d: (d["created_at"], d["delivery_id"]),
            )["delivery_id"]
            for p in project_ids
            if any(d["project_id"] == p for d in all_deliveries)
        }
        obsolete_report_views: list[tuple[Path, dict[str, Any]]] = []
        for run in runs:
            project = run["view"]["project_id"]
            for delivery in run["deliveries"]:
                source = (self.outputs / delivery["relative_path"]).resolve()
                manifest_bytes = (source / "manifest.json").read_bytes()
                if hashlib.sha256(manifest_bytes).hexdigest() != delivery["manifest_hash"]:
                    raise PlatformError("EVIDENCE_INVALID", "Registered report manifest differs")
                manifest = json.loads(manifest_bytes)
                old_target = f"01-研究项目/{project}/05-成果交付/报告-{delivery['created_at'][:10]}--{delivery['delivery_id'][-8:]}"
                target = old_target
                if delivery["delivery_id"] != latest_reports[project]:
                    target = (
                        f"01-研究项目/{project}/05-成果交付/历史版本/"
                        + PurePosixPath(old_target).name
                    )
                    old_view = self.workspace / old_target
                    if old_view.is_dir():
                        obsolete_report_views.append((old_view, manifest))
                for entry in manifest["files"]:
                    original = (source / entry["path"]).resolve()
                    if not original.is_relative_to(source):
                        raise PlatformError("EVIDENCE_INVALID", "Unsafe report material path")
                    data = native_path(original).read_bytes()
                    if (
                        len(data) != entry["size"]
                        or hashlib.sha256(data).hexdigest() != entry["sha256"]
                    ):
                        raise PlatformError("EVIDENCE_INVALID", "Registered report file differs")
                    extra[target + "/" + entry["path"]] = data
                    external_links[str(original)] = target + "/" + entry["path"]
                extra[target + "/manifest.json"] = manifest_bytes
                extra[target + "/manifest.sha256"] = (source / "manifest.sha256").read_bytes()
        for record in publications:
            project = record["project_id"]
            suffix = record["publication_id"][-8:]
            category = (
                "待核验/"
                if record["registration_mode"] == "unreviewed_intake"
                else ""
                if record["current_basis"]
                else "历史版本/"
            )
            safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in record["title"])[
                :48
            ].rstrip(" .")
            target = f"01-研究项目/{project}/05-成果交付/{category}PPT-{safe_title}--{suffix}"
            # Names and relative file locations originate in the strict registration contract.
            for name, data in publication_files[record["publication_id"]].items():
                extra[target + "/" + name] = data
            stored = {k: v for k, v in record.items() if k != "current_basis"}
            extra[target + "/registration.json"] = canonical(stored)
            body = paragraph(
                "已登记并绑定研究判断；待人工审阅。"
                if record["registration_mode"] == "research_bound"
                else "仅登记文件保全；尚未逐条绑定和核验其中新增分析，不可用作已核验研究。",
                "notice",
            )
            body += paragraph("研究依据：" + record["basis_fingerprint"])
            body += (
                "<p>"
                + relative_link(
                    target + "/index.html",
                    target + "/" + record["presentation"]["name"],
                    "打开可编辑PPT",
                )
                + "</p>"
            )
            body += "<h2>逐页判断与研究库对应</h2>"
            for slide in record["slides"]:
                body += "<h3>PPT 第 " + esc(slide["slide"]) + " 页</h3>"
                body += paragraph(
                    "判断：" + ("、".join(slide["claim_ids"]) or "编排页")
                ) + paragraph(slide["note"])
            body += "<h2>原件页码对应</h2>"
            for source in record["source_pages"]:
                body += paragraph(
                    "原件第 "
                    + str(source["unit_index"])
                    + " 页 → PPT "
                    + "、".join(map(str, source["slides"]))
                    + " 页；判断 "
                    + "、".join(source["claim_ids"])
                )
            body += "<h2>核验边界</h2>" + "".join(paragraph(x) for x in record["limitations"])
            body += (
                "<h2>附属材料</h2><ul>"
                + "".join(
                    "<li>"
                    + relative_link(target + "/index.html", target + "/" + f["name"], f["name"])
                    + "</li>"
                    for f in record["supplements"]
                )
                + "</ul>"
            )
            extra[target + "/index.html"] = page(record["title"], body)
            supplementary.setdefault(project, []).append(
                target + "/" + record["presentation"]["name"]
            )
            publication_modes[target + "/" + record["presentation"]["name"]] = record[
                "registration_mode"
            ]
        output = dict(extra)
        for old, data in files.items():
            new = paths[old]
            generated_html = (
                old == "index.html"
                or old.startswith("研究项目/")
                or PurePosixPath(old).name == "index.html"
            )
            if not generated_html:
                output[new] = data
                continue
            soup = BeautifulSoup(data, "html.parser")
            for anchor in soup.find_all("a", href=True):
                if anchor.get_text() in run_labels:
                    anchor.string = run_labels[anchor.get_text()]
                uri = urlparse(str(anchor["href"]))
                if uri.scheme or not uri.path:
                    continue
                old_target = posixpath.normpath(
                    posixpath.join(str(PurePosixPath(old).parent), unquote(uri.path))
                )
                mapped_target = paths.get(old_target)
                if mapped_target is None:
                    absolute = (
                        self.outputs / edition_base / PurePosixPath(old).parent / unquote(uri.path)
                    ).resolve()
                    mapped_target = external_links.get(str(absolute))
                if mapped_target:
                    relative = os.path.relpath(
                        mapped_target, str(PurePosixPath(new).parent)
                    ).replace("\\", "/")
                    anchor["href"] = quote(relative, safe="/") + (
                        "#" + uri.fragment if uri.fragment else ""
                    )
            output[new] = str(soup).encode()
        project_links = []
        for project in sorted(project_ids):
            root = f"01-研究项目/{project}"
            overview = root + "/00-项目概览.html"
            project_links.append(
                '<article class="card"><h2>'
                + relative_link("00-开始阅读.html", overview, project)
                + "</h2>"
                + paragraph("任务 → 原始资料 → 证据摘录 → 分析核验 → 成果交付 → 更新记录")
                + "</article>"
            )
            project_runs = [r for r in runs if r["view"]["project_id"] == project]
            additions = (
                collection_table(project_runs[-1].get("collection_coverage", {}))
                if project_runs
                else ""
            )
            source_overview = root + "/02-原始资料/00-信源总览.html"
            rows = []
            for research in reversed(project_runs):
                observations = {o["source_id"]: o for o in research["observations"]}
                for source in research["input"]["sources"]:
                    origin = source.get("origin") or {}
                    o = observations.get(source["source_id"], {})
                    materials = [
                        c
                        for c in cards.values()
                        if c["project"] == project and c["source_id"] == source["source_id"]
                    ]
                    links = "".join(
                        "<p>"
                        + relative_link(
                            source_overview,
                            material_roots[str(PurePosixPath(c["path"]).parent)] + "/index.html",
                            c["role"],
                        )
                        + "</p>"
                        for c in materials
                    )
                    rows.append(
                        [
                            esc(source["publisher"]) + paragraph(source["source_id"]),
                            esc(
                                {
                                    "official": "官网",
                                    "paper": "论文",
                                    "conference": "会议原稿",
                                    "youtube": "YouTube",
                                    "x": "X",
                                    "feed": "订阅发现",
                                    "local": "本地资料",
                                }.get(str(origin.get("channel", "")), "历史未分类")
                            ),
                            esc(source["provider"]),
                            esc(origin.get("publication_url") or source["resource_uri"]),
                            esc(o.get("goal_result", {}).get("reason_code", "尚未执行"))
                            + paragraph(o.get("goal_result", {}).get("detail", "")),
                            "".join(paragraph(b) for b in source["identity_basis"]),
                            links or "未取得材料",
                        ]
                    )
            output[source_overview] = page(
                "信源总览：出处、取得方式与实际覆盖",
                paragraph(
                    "官网、会议、论文等表示原始出处；http、本地导入、连接器和API表示取得方式。采集失败与尚未执行的来源也保留。"
                )
                + table(
                    [
                        "来源",
                        "原始出处类别",
                        "平台取得方式",
                        "原始地址或导入位置",
                        "实际取得结果",
                        "出处与导入依据",
                        "查看归档材料",
                    ],
                    rows,
                ),
            )
            additions += (
                "<p>"
                + relative_link(
                    overview,
                    source_overview,
                    "查看信源总览：出处、方式、失败原因与原件",
                )
                + "</p><h2>直接打开成果</h2>"
            )
            historical = ""
            for run in reversed(runs):
                if run["view"]["project_id"] != project:
                    continue
                for d in reversed(run["deliveries"]):
                    target = external_links[
                        str((self.outputs / d["relative_path"] / "index.html").resolve())
                    ]
                    report_link = (
                        "<p>"
                        + relative_link(
                            overview,
                            target,
                            "研究报告 · "
                            + d["created_at"][:19].replace("T", " ")
                            + (" · 当前研究依据" if d["current_basis"] else " · 历史研究依据"),
                        )
                        + "</p>"
                    )
                    if d["delivery_id"] == latest_reports[project]:
                        additions += report_link
                    else:
                        historical += report_link
            for ppt in supplementary.get(project, []):
                additions += (
                    "<p>"
                    + relative_link(overview, ppt, "可编辑PPT · " + PurePosixPath(ppt).name)
                    + "</p>"
                )
                additions += paragraph(
                    "PPT已绑定研究判断；页码和原件依据见成品登记页，待人工审阅。"
                    if publication_modes[ppt] == "research_bound"
                    else "此稿仅登记保全，新增分析尚未逐条绑定核验。",
                    "notice",
                )
                analysis_page = str(PurePosixPath(ppt).parent / "index.html")
                if analysis_page in extra:
                    additions += (
                        "<p>"
                        + relative_link(overview, analysis_page, "查看成品登记与逐页依据")
                        + "</p>"
                    )
            if historical:
                additions += "<details><summary>历史报告版本</summary>" + historical + "</details>"
            html_text = output[overview].decode().replace("</main>", additions + "</main>")
            output[overview] = html_text.encode()
            # Category landing files make the directory usable without starting in a browser.
            for category in (
                "01-研究任务",
                "02-原始资料",
                "03-证据与摘录",
                "04-分析与核验",
                "05-成果交付",
                "06-更新记录",
            ):
                landing = root + "/" + category + "/index.html"
                children = sorted(
                    p
                    for p in output
                    if p.startswith(root + "/" + category + "/")
                    and (p.endswith(".html") or p.endswith(".pptx"))
                )
                if category == "05-成果交付":
                    children = [
                        p for p in children if p.endswith("index.html") or p.endswith(".pptx")
                    ]
                    current = [p for p in children if "/历史版本/" not in p]
                    history = [p for p in children if "/历史版本/" in p]
                    items = (
                        "<ul>"
                        + "".join(
                            "<li>"
                            + relative_link(
                                landing,
                                p,
                                str(PurePosixPath(p).relative_to(root + "/" + category)),
                            )
                            + "</li>"
                            for p in current
                            if "/materials/" not in p
                        )
                        + "</ul>"
                    )
                    if history:
                        items += (
                            "<details><summary>历史报告</summary><ul>"
                            + "".join(
                                "<li>"
                                + relative_link(
                                    landing,
                                    p,
                                    str(PurePosixPath(p).relative_to(root + "/" + category)),
                                )
                                + "</li>"
                                for p in history
                                if "/materials/" not in p
                            )
                            + "</ul></details>"
                        )
                    output[landing] = page(
                        category,
                        items,
                        relative_link(landing, overview, "返回项目概览"),
                    )
                    continue
                items = (
                    "<ul>"
                    + "".join(
                        "<li>"
                        + relative_link(
                            landing,
                            p,
                            str(PurePosixPath(p).relative_to(root + "/" + category)),
                        )
                        + "</li>"
                        for p in children
                        if "/materials/" not in p
                    )
                    + "</ul>"
                )
                output[landing] = page(
                    category, items, relative_link(landing, overview, "返回项目概览")
                )
        output["00-工作区说明.md"] = (
            "# 个人洞察工作区\n\n先进入 01-研究项目，再选专题。每个专题按任务、原始资料、证据、分析、成果、更新记录组织。\n\n"
            "00-开始阅读.html 是浏览器入口。02-共享资料索引 是跨项目导航，不能自动成为任何项目的研究依据。\n\n"
            "90-平台运行 存放数据库、不可变对象、请求、工程验证和历史阅读快照。日常阅读不需要进入。\n\n"
            "用户目录是可重建的阅读副本，请通过平台提交研究修改。原始资料、旧报告和历史快照不因刷新被删除。\n\n"
            "刷新命令：uv run --frozen insight --workspace <本工作区> reading-room。当前没有后台实时同步。\n"
        ).encode()
        output["00-开始阅读.html"] = page(
            "我的研究项目",
            paragraph("从项目进入，查看任务、资料、分析过程和最终成果。")
            + '<div class="grid">'
            + "".join(project_links)
            + "</div><p>"
            + relative_link(
                "00-开始阅读.html",
                "02-共享资料索引/index.html",
                "跨项目资料索引（辅助入口）",
            )
            + "</p>",
        )
        immutable = set(extra) | {
            paths[old]
            for old in files
            if old.startswith("资料库/") and PurePosixPath(old).name != "index.html"
        }
        for name in immutable:
            path = native_path(self.workspace / name)
            if path.exists() and path.read_bytes() != output[name]:
                raise PlatformError(
                    "REVISION_CONFLICT",
                    "A user material or delivery copy was edited; preserve it before refreshing",
                )
        for old_view, manifest in obsolete_report_views:
            if not old_view.resolve().is_relative_to(self.workspace / "01-研究项目"):
                raise PlatformError("INVALID_SPEC", "Obsolete report view escapes user projects")
            for entry in manifest["files"]:
                candidate_path = (old_view / entry["path"]).resolve()
                if not candidate_path.is_relative_to(old_view.resolve()):
                    raise PlatformError("INVALID_SPEC", "Historical user report escapes its folder")
                content = native_path(candidate_path).read_bytes()
                if (
                    len(content) != entry["size"]
                    or hashlib.sha256(content).hexdigest() != entry["sha256"]
                ):
                    raise PlatformError(
                        "REVISION_CONFLICT",
                        "Historical user report was edited; preserve it before refreshing",
                    )
        # Prepare and validate all bytes before updating the stable human entrance last.
        for name, data in output.items():
            if name == "00-开始阅读.html":
                continue
            path = native_path(self.workspace / name)
            if not path.exists() or path.read_bytes() != data:
                atomic_write(path, data)
        for old_view, _ in obsolete_report_views:
            archive_path = (
                self.outputs
                / "reading-room"
                / "superseded-user-views"
                / uuid4().hex
                / old_view.name
            )
            if not archive_path.resolve().is_relative_to(self.outputs):
                raise PlatformError("INVALID_SPEC", "Archive target escapes configured outputs")
            archive = native_path(archive_path)
            archive.parent.mkdir(parents=True, exist_ok=True)
            os.rename(native_path(old_view), archive)
        for old_view in sorted(obsolete_material_views):
            archive_path = (
                self.outputs
                / "reading-room"
                / "superseded-material-views"
                / uuid4().hex
                / old_view.name
            )
            if not archive_path.resolve().is_relative_to(self.outputs):
                raise PlatformError("INVALID_SPEC", "Material archive escapes configured outputs")
            archive = native_path(archive_path)
            archive.parent.mkdir(parents=True, exist_ok=True)
            os.rename(native_path(old_view), archive)
        atomic_write(self.workspace / "00-开始阅读.html", output["00-开始阅读.html"])
        atomic_write(
            self.outputs / "reading-room" / "project-view.json",
            canonical({"edition": edition_base, "kind": "derived_project_view"}),
        )
        return str(self.workspace / "00-开始阅读.html")
