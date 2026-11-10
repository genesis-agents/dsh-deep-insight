"""Classified, rebuildable reading editions; never mutate source or delivery versions."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from bs4 import BeautifulSoup

from insight.adapters.export.project_workspace import ProjectWorkspaceWriter
from insight.adapters.export.reading_html import (
    collection_table,
    esc,
    listing,
    page,
    paragraph,
    relative_link,
    table,
)
from insight.adapters.persistence.objects import atomic_write, native_path
from insight.domain.contracts import Artifact, ExtractedDocument, PlatformError
from insight.domain.rules import canonical, fingerprint
from insight.ports.storage import BlobStore

PROVIDERS = {
    "local": "用户提供资料",
    "http": "公开网页与文件",
    "conference": "会议资料",
    "youtube": "YouTube关联资料",
    "x": "X专业账户",
    "feed": "订阅发现",
    "browser": "浏览器实际观察",
}
ROLES = {
    "raw_document": "文档正文",
    "original_slides": "作者原始投影片",
    "extracted_text": "提取文本",
    "source_metadata": "来源元数据",
    "post": "帖子正文",
    "transcript": "口述转录",
    "derived_slide_frames": "视频抽帧",
    "reconstructed_deck": "重建演示稿",
    "raw_video": "视频原件",
    "raw_audio": "音频原件",
    "browser_capture": "浏览器观察附件",
}
LABELS = {
    "run_created": "研究批次创建",
    "source_processed": "完成一次来源处理",
    "acquisition_checkpoint": "采集断点已保存",
    "evidence_selected": "证据摘录已登记",
    "context_prepared": "分析证据包已固定",
    "analysis_submitted": "分析判断已提交",
    "semantic_verification_submitted": "逐条语义复核已提交",
    "human_review_recorded": "人工审阅决定已记录",
    "delivery_prepared": "交付版本已装配",
    "delivery_published": "交付入口已更新",
    "acquisition_resumed": "采集已接续",
    "cancellation_requested": "已请求取消",
    "worker_failed": "执行器处理失败",
    "document_text": "文档正文",
    "slides_only": "原始投影片",
    "editable_original_pptx": "可编辑原始PPTX",
    "metadata": "来源元数据",
    "full_talk_analysis": "完整演讲分析",
    "latest_posts": "窗口内最新帖子",
    "met": "取得目标已满足",
    "not_met": "取得目标未满足",
    "unknown": "尚不能确认",
    "source_claim": "来源主张",
    "observation": "事实观察",
    "inference": "研究推断",
    "hypothesis": "待验证假设",
    "supports": "支持",
    "contradicts": "反驳",
    "context": "背景",
    "supported": "支持",
    "contradicted": "不支持",
    "unclear": "不明确",
    "passed": "通过",
    "failed": "失败",
    "not_performed": "未执行",
    "accepted": "接受",
    "changes_requested": "要求修改",
    "verified": "身份已核对",
    "user_provided": "用户提供身份依据",
    "needs_verification": "身份待核对",
    "machine_verified": "机器核验通过",
    "reviewed": "已审阅",
    "draft": "草稿",
    "evidence_incomplete": "证据不完整",
    "succeeded": "执行完成",
    "queued": "排队中",
    "waiting_input": "等待输入",
    "cancelled": "已取消",
    "running": "执行中",
}
STAGES = (
    "01-任务说明",
    "02-信源计划",
    "03-采集记录",
    "04-证据摘录",
    "05-分析判断",
    "06-核验记录",
    "07-人工审阅",
    "08-成果交付",
)


def label(value: Any) -> str:
    return LABELS.get(str(value), str(value))


def component(value: str, limit: int = 28) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(" .") or "未命名"
    return value[:limit].rstrip(" .") or "未命名"


def document_title(
    source: dict[str, Any], document: ExtractedDocument, raw: bytes, media: str, role: str = ""
) -> str:
    # Machine receipts and attachments describe acquisition, not the work's title.
    # Keep their bytes intact while giving the derived reading view a usable name.
    if role in ("source_metadata", "browser_capture", "transcript"):
        description = {
            "source_metadata": "更新目录" if source["provider"] == "feed" else "采集记录",
            "browser_capture": "浏览器画面" if media.startswith("image/") else "浏览器附件",
            "transcript": "演讲字幕",
        }[role]
        return f"{source['publisher']} · {description}"
    if media == "text/html":
        title = BeautifulSoup(raw, "html.parser").title
        if title and title.get_text(strip=True):
            return title.get_text(" ", strip=True)[:180]
    if source["provider"] == "local":
        return unquote(source["resource_uri"].rsplit("/", 1)[-1])
    for unit in document.units:
        for line in unit.text.splitlines():
            if len(line.strip()) >= 8:
                if re.search(r"capability needed|all rights reserved|copyright", line, re.I):
                    return str(source["publisher"])
                return line.strip()[:180]
    return unquote(urlparse(source["resource_uri"]).path.rsplit("/", 1)[-1]) or source["source_id"]


class ReadingRoomPublisher:
    def __init__(self, output_root: Path, blobs: BlobStore, workspace: Path) -> None:
        self.root, self.blobs = output_root.resolve(), blobs
        self.project_workspace = ProjectWorkspaceWriter(workspace, output_root)

    def publish(self, snapshot: dict[str, Any], artifacts: tuple[Artifact, ...]) -> dict[str, Any]:
        by_id = {a.artifact_id: a for a in artifacts}
        # Include renderer code, so a renderer change cannot reuse a prior edition silently.
        edition = fingerprint(
            {
                "snapshot": snapshot,
                "renderer": hashlib.sha256(
                    Path(__file__).read_bytes()
                    + Path(__file__).with_name("project_workspace.py").read_bytes()
                    + Path(__file__).with_name("reading_html.py").read_bytes()
                ).hexdigest(),
            }
        )
        base = "reading-room/editions/" + edition[:16]
        files: dict[str, bytes] = {}
        cards: dict[str, dict[str, Any]] = {}
        for run in snapshot["runs"]:
            sources = {s["source_id"]: s for s in run["input"]["sources"]}
            for version in run["versions"]:
                source = sources[version["source_id"]]
                raw = by_id[version["raw_artifact_id"]]
                data = self.blobs.read(raw)
                extracted_id = version["extracted_artifact_id"]
                document = (
                    ExtractedDocument.model_validate_json(self.blobs.read(by_id[extracted_id]))
                    if extracted_id
                    else ExtractedDocument(processor_ref="none", units=())
                )
                title = document_title(source, document, data, raw.media_type, raw.role)
                category = PROVIDERS[source["provider"]]
                publisher = (
                    component(source["publisher"], 20) + "--" + fingerprint(source["publisher"])[:8]
                )
                folder = f"资料库/{category}/{publisher}/{component(title)}--{fingerprint(version['version_id'])[:16]}"
                path = folder + "/index.html"
                extension = {
                    "application/pdf": ".pdf",
                    "image/png": ".png",
                    "video/mp4": ".mp4",
                    "video/webm": ".webm",
                    "application/xml": ".xml",
                    "text/html": ".html",
                    "text/plain": ".txt",
                    "application/json": ".json",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                }.get(raw.media_type, ".bin")
                filename = component(title, 32)
                if not filename.casefold().endswith(extension):
                    filename += extension
                raw_path = folder + "/" + filename
                if PurePosixPath(raw_path).name.casefold() == "index.html":
                    raw_path = folder + "/原件-index.html"
                record_path = folder + "/来源记录.json"
                record = canonical(
                    {"source": source, "version": version, "artifact": raw.model_dump(mode="json")}
                )
                if record_path in files and files[record_path] != record:
                    raise PlatformError("REVISION_CONFLICT", "Readable material path collision")
                files[raw_path] = data
                text = "\n\n".join(
                    f"## 单元 {u.index}（{u.kind}）\n\n{u.text}" for u in document.units
                )
                files[folder + "/逐页或逐条文本.md"] = ("# " + title + "\n\n" + text).encode()
                card = dict(
                    title=title,
                    category=category,
                    publisher=source["publisher"],
                    role=ROLES[raw.role],
                    path=path,
                    project=run["view"]["project_id"],
                    source_id=source["source_id"],
                    version_id=version["version_id"],
                )
                cards[version["version_id"]] = card
                body = table(
                    ["资料属性", "记录"],
                    [
                        ["浏览分类（取得方式）", esc(category)],
                        [
                            "原始出处类别",
                            esc(
                                (source.get("origin") or {}).get(
                                    "channel", "历史记录未结构化分类；请核对出处依据"
                                )
                            ),
                        ],
                        [
                            "原始发布地址",
                            esc(
                                (source.get("origin") or {}).get("publication_url")
                                or "见下方出处依据"
                            ),
                        ],
                        [
                            "论文/会议发表状态",
                            esc(
                                (source.get("origin") or {}).get(
                                    "publication_status", "未核验，不能据此称为顶会论文"
                                )
                            ),
                        ],
                        ["发布机构（登记值）", esc(source["publisher"])],
                        ["材料类型", esc(ROLES[raw.role])],
                        ["身份状态", esc(label(source["identity_status"]))],
                        ["采集时间", esc(version["acquired_at"])],
                        [
                            "发布时间",
                            esc(version.get("published_at") or "未记录；不能以采集时间代替"),
                        ],
                        ["来源位置", esc(version["origin_uri"])],
                        ["来源编号", esc(source["source_id"])],
                        ["版本编号", esc(version["version_id"])],
                        ["原件SHA256", esc(raw.sha256)],
                        [
                            "文字提取范围",
                            esc(
                                f"{len(document.units)} 个单元；{sum(len(u.text) for u in document.units)} 字符；不代表已完成全文、图表或口述审阅"
                            ),
                        ],
                        ["关联研究项目", esc(card["project"])],
                    ],
                )
                body += "<h2>原始出处与取得依据</h2>" + listing(source["identity_basis"])
                body += paragraph(
                    "标题取自网页标题、文件名或提取首行，仅用于浏览；分类不证明内容真实或来源独立。",
                    "notice",
                )
                body += paragraph("提取文本不能替代原图、图表或演讲口述核对。", "notice")
                body += "<p>" + relative_link(path, raw_path, "下载原始材料", download=True) + " · "
                body += relative_link(path, folder + "/逐页或逐条文本.md", "完整提取文本") + "</p>"
                if raw.media_type == "image/png":
                    body += (
                        '<img style="max-width:100%" src="'
                        + PurePosixPath(raw_path).name
                        + '" alt="归档视频抽帧"/>'
                    )
                body += listing(document.warnings)
                body += "".join(
                    f'<section id="unit-{u.index}"><h2>单元 {u.index} · {esc(u.kind)}</h2>'
                    + (
                        paragraph(f"视频时间 {u.start_seconds:.3f}–{u.end_seconds:.3f} 秒")
                        if u.start_seconds is not None and u.end_seconds is not None
                        else ""
                    )
                    + paragraph(u.text)
                    + "</section>"
                    for u in document.units
                )
                files[path] = page(title, body, relative_link(path, "index.html", "返回阅读台"))
                files[record_path] = record
        project_specs = {p["project_id"]: p for p in snapshot["projects"]}
        projects: dict[str, list[dict[str, Any]]] = {p: [] for p in project_specs}
        for run in snapshot["runs"]:
            project_id = run["view"]["project_id"]
            projects.setdefault(project_id, []).append(run)
            self._run_pages(run, cards, files, base)
        for project_id, runs in projects.items():
            path = f"研究项目/{project_id}/index.html"
            spec = project_specs[project_id]
            body = paragraph(spec["question"])
            if not runs:
                body += paragraph("任务已登记；尚未启动研究，没有已采集资料或成果。", "notice")
                task_path = f"研究项目/{project_id}/01-任务说明.html"
                body += "<p>" + relative_link(path, task_path, "查看已登记任务") + "</p>"
                files[task_path] = page(
                    "研究任务",
                    paragraph(spec["question"])
                    + "<h2>决策用途</h2>"
                    + paragraph(spec["decision"])
                    + "<h2>子问题</h2>"
                    + listing(spec["subquestions"]),
                    relative_link(task_path, path, "返回项目"),
                )
            body += table(
                ["研究批次", "执行状态", "质量状态（已记录）", "资料 / 证据 / 判断"],
                [
                    [
                        relative_link(
                            path,
                            f"研究项目/{project_id}/批次/{r['view']['run_id']}/index.html",
                            r["view"]["run_id"],
                        ),
                        esc(label(r["view"]["execution_state"])),
                        esc(label(r["view"]["quality_state"])),
                        f"{len(r['versions'])} / {len(r['evidence'])} / {len((r['analysis'] or {}).get('claims', []))}",
                    ]
                    for r in runs
                ],
            )
            files[path] = page(project_id, body, relative_link(path, "index.html", "返回阅读台"))
        files["index.html"] = self._home(projects, cards, project_specs)
        files["阅读说明.md"] = (
            "# 阅读台\n\n从 index.html 进入。资料库按来源类别、发布机构、材料标题分类；"
            "每条资料同时标明材料类型和关联项目。研究项目按批次展示八个阶段。\n\n"
            "这是数据库与原件的只读派生视图，不是新的权威数据库；请勿在此修改研究记录。"
            "更新请运行 insight --workspace <工作区> reading-room。每次内容变化产生新阅读版本。"
            "底层原件、旧研究和旧交付保持原样。\n\n"
            "阅读台内资料原件与文本可离线浏览；报告链接指向同一工作区 outputs 中的交付。"
            "整体移动工作区后相对链接有效，单独复制阅读版本不包含外部交付。"
            "尚未登记到数据库的PPT分析不会被当作已登记研究。\n"
        ).encode()
        manifest = {
            "schema_version": 1,
            "kind": "readable_workspace_projection",
            "edition": edition,
            "runs": len(snapshot["runs"]),
            "materials": len(cards),
            "files": [
                {"path": p, "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}
                for p, b in sorted(files.items())
            ],
        }
        target = native_path(self.root / base)
        if not target.exists():
            staging = native_path(self.root / "reading-room" / ".staging" / uuid4().hex)
            for name, data in files.items():
                atomic_write(staging / name, data)
            atomic_write(staging / "manifest.json", canonical(manifest))
            self._verify(staging, manifest)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
        self._verify(target, manifest)
        user_index = self.project_workspace.publish(
            files,
            cards,
            snapshot["runs"],
            base,
            tuple(project_specs),
            snapshot.get("publications", []),
            {
                p["publication_id"]: {
                    f["name"]: self.blobs.read(by_id[f["artifact_id"]])
                    for f in (p["presentation"], *p["supplements"])
                }
                for p in snapshot.get("publications", [])
            },
        )
        home = f"editions/{edition[:16]}/index.html"
        atomic_write(
            self.root / "reading-room" / "index.html",
            page(
                "个人洞察阅读台",
                '<p><a href="'
                + home
                + '">进入资料分类与研究过程</a></p>'
                + paragraph("此入口始终指向最近一次生成的阅读版本；研究变更后需刷新阅读台。")
                + f'<meta http-equiv="refresh" content="0;url={home}">',
            ),
        )
        return {
            "user_index": user_index,
            "index": str(self.root / "reading-room" / "index.html"),
            "edition": edition,
            "projects": len(projects),
            "runs": len(snapshot["runs"]),
            "materials": len(cards),
            "files_verified": len(files),
            "research_state_changed": False,
        }

    @staticmethod
    def _verify(directory: Path, expected: dict[str, Any]) -> None:
        if json.loads((directory / "manifest.json").read_bytes()) != expected:
            raise PlatformError("EVIDENCE_INVALID", "Reading edition manifest differs")
        for entry in expected["files"]:
            data = (directory / entry["path"]).read_bytes()
            if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise PlatformError("EVIDENCE_INVALID", "Reading edition file failed verification")

    def _home(
        self,
        projects: dict[str, list[dict[str, Any]]],
        cards: dict[str, dict[str, Any]],
        project_specs: dict[str, dict[str, Any]],
    ) -> bytes:
        body = paragraph(
            "先选研究项目查看任务、过程与成果；也可以按来源、机构和材料类型查阅原始资料。"
        )
        body += '<h2>研究项目</h2><div class="grid">'
        for project_id, runs in projects.items():
            body += (
                '<article class="card"><h3>'
                + relative_link("index.html", f"研究项目/{project_id}/index.html", project_id)
                + "</h3>"
            )
            body += (
                paragraph(project_specs[project_id]["question"])
                + paragraph(f"{len(runs)} 个研究批次")
                + "</article>"
            )
        body += "</div><h2>资料库</h2>"
        body += paragraph(
            "只列已取得的材料版本。未取得来源与覆盖缺口在各研究批次的信源计划、采集记录中查看。",
            "notice",
        )
        body += '<div class="filters"><input id="search" aria-label="搜索资料" placeholder="搜索标题、机构或项目">'
        for key, title in (
            ("category", "来源类别"),
            ("publisher", "发布机构"),
            ("role", "材料类型"),
            ("project", "研究项目"),
        ):
            body += f'<select data-field="{key}" aria-label="{title}"><option value="">全部{title}</option>'
            body += (
                "".join(
                    f'<option value="{esc(v)}">{esc(v)}</option>'
                    for v in sorted({c[key] for c in cards.values()})
                )
                + "</select>"
            )
        body += '</div><p id="count"></p><table><thead><tr><th>材料</th><th>来源类别</th><th>发布机构</th><th>材料类型</th><th>项目</th></tr></thead><tbody id="materials">'
        for card in cards.values():
            body += (
                "<tr "
                + " ".join(
                    f'data-{k}="{esc(card[k])}"'
                    for k in ("category", "publisher", "role", "project")
                )
                + ">"
            )
            body += "<td>" + relative_link("index.html", card["path"], card["title"]) + "</td>"
            body += (
                "".join(
                    "<td>" + esc(card[k]) + "</td>"
                    for k in ("category", "publisher", "role", "project")
                )
                + "</tr>"
            )
        body += """</tbody></table><script>
const search=document.getElementById('search'),filters=[...document.querySelectorAll('select[data-field]')],rows=[...document.querySelectorAll('#materials tr')];
function filter(){let n=0;for(const row of rows){const yes=row.textContent.toLowerCase().includes(search.value.toLowerCase())&&filters.every(f=>!f.value||row.dataset[f.dataset.field]===f.value);row.hidden=!yes;if(yes)n++;}document.getElementById('count').textContent='显示 '+n+' / '+rows.length+' 个材料版本';}
search.addEventListener('input',filter);filters.forEach(f=>f.addEventListener('change',filter));filter();
</script>"""
        body += paragraph(
            "阅读台是可重建的只读快照；新的采集、分析或交付登记后须重新生成。没有自动语义主题分类，也没有将外部PPT新增分析自动回写数据库。",
            "notice",
        )
        return page("个人洞察阅读台", body)

    def _run_pages(
        self,
        run: dict[str, Any],
        cards: dict[str, dict[str, Any]],
        files: dict[str, bytes],
        base: str,
    ) -> None:
        project = run["input"]["project"]
        root = f"研究项目/{project['project_id']}/批次/{run['view']['run_id']}"
        sources = {s["source_id"]: s for s in run["input"]["sources"]}
        evidence = {e["evidence_id"]: e for e in run["evidence"]}
        analysis = run["analysis"]
        stages: list[str] = []
        stages.append(
            "<h2>研究问题</h2>"
            + paragraph(project["question"])
            + "<h2>决策用途</h2>"
            + paragraph(project["decision"])
            + "<h2>范围</h2>"
            + paragraph(
                "地域："
                + "、".join(project["scope"]["regions"])
                + "；截至："
                + project["scope"]["as_of"]
                + "；研究侧重点："
                + project["profile_ref"]
            )
            + listing(project["scope"]["exclusions"])
            + "<h2>子问题</h2>"
            + listing(project["subquestions"])
        )
        stages.append(
            table(
                ["来源 / 身份", "取得目标 / 必需性", "时间窗", "完成标准 / 新鲜度要求"],
                [
                    [
                        esc(sources[i["source_ref"]]["publisher"])
                        + "<br>"
                        + esc(i["source_ref"])
                        + "<br>"
                        + esc(sources[i["source_ref"]]["resource_uri"])
                        + "<br>"
                        + esc(label(sources[i["source_ref"]]["identity_status"])),
                        esc(label(i["goal"])) + " / " + ("必需" if i["required"] else "可选"),
                        esc(
                            (i["requested_window"]["start"] or "未指定起点")
                            + " → "
                            + i["requested_window"]["end"]
                        ),
                        esc(i["completion_rule"]) + "<br>" + esc(i["freshness_rule"]),
                    ]
                    for i in run["input"]["plan"]["items"]
                ],
            )
        )
        stages[-1] = collection_table(run.get("collection_coverage", {})) + stages[-1]
        acquisition = collection_table(run.get("collection_coverage", {}))
        for source_id, source in sources.items():
            acquisition += "<h2>" + esc(source["publisher"]) + " · " + esc(source_id) + "</h2>"
            observations = [o for o in run["observations"] if o["source_id"] == source_id]
            acquisition += (
                table(
                    ["取得结果", "原因", "分页 / 覆盖"],
                    [
                        [
                            esc(label(o["goal_result"]["state"])),
                            esc(o["goal_result"]["detail"]),
                            (
                                "分页已完成"
                                if o["pagination_complete"]
                                else "分页未完成或不适用；参照覆盖说明"
                            )
                            + listing(o["coverage_notes"]),
                        ]
                        for o in observations
                    ],
                )
                if observations
                else paragraph("尚无采集记录；不代表没有相关信息。", "notice")
            )
            path = root + "/" + STAGES[2] + ".html"
            acquisition += (
                "<ul>"
                + "".join(
                    "<li>"
                    + relative_link(
                        path, cards[v["version_id"]]["path"], cards[v["version_id"]]["title"]
                    )
                    + " · "
                    + esc(v["acquired_at"])
                    + "</li>"
                    for v in run["versions"]
                    if v["source_id"] == source_id
                )
                + "</ul>"
            )
        stages.append(acquisition)
        excerpts = paragraph("引文定位到固定提取版本；文字匹配不代表图表和语义已经核对。", "notice")
        for item in evidence.values():
            card = cards[item["source_version_id"]]
            locator = item["locator"]
            path = root + "/" + STAGES[3] + ".html"
            excerpts += f'<section id="{esc(item["evidence_id"])}"><h2>{esc(card["title"])}</h2>'
            excerpts += "<p>" + relative_link(path, card["path"], "查看原件与完整提取文本") + "</p>"
            excerpts += paragraph(
                (
                    f"原件第 {locator['unit_index']} 页；视觉观察（非原文引文）；观察者 {locator['observer']}；{locator['limitations']}"
                    if locator.get("modality") == "visual_page"
                    else f"单元 {locator['unit_index']}；字符 {locator['char_start']}–{locator['char_end']}"
                )
                + f"；证据编号 {item['evidence_id']}",
                "muted",
            )
            excerpts += "<blockquote>" + esc(item["quote"]) + "</blockquote></section>"
        stages.append(excerpts if evidence else paragraph("尚未选择证据。", "notice"))
        judgments = paragraph("尚未提交分析。", "notice")
        if analysis:
            judgments = "<h2>" + esc(analysis["title"]) + "</h2>" + paragraph(analysis["synthesis"])
            judgments += "<h2>判断与依据</h2>"
            for claim in analysis["claims"]:
                judgments += (
                    "<h3>"
                    + esc(claim["claim_id"])
                    + " · "
                    + esc(label(claim["kind"]))
                    + "</h3>"
                    + paragraph(claim["statement"])
                )
                judgments += "<b>成立条件</b>" + listing(claim["conditions"])
                for ref in claim["evidence_links"]:
                    item = evidence[ref["evidence_id"]]
                    link = relative_link(
                        root + "/" + STAGES[4] + ".html",
                        root + "/" + STAGES[3] + ".html",
                        label(ref["relation"]) + "：" + ref["evidence_id"],
                    )
                    link = link.replace('.html"', ".html#" + esc(ref["evidence_id"]) + '"')
                    judgments += (
                        "<p>" + link + "</p><blockquote>" + esc(item["quote"]) + "</blockquote>"
                    )
                judgments += "<b>反证或反向条件</b>" + listing(claim["counterevidence"])
            judgments += "<h2>限制与未解决项</h2>" + listing(analysis["limitations"])
            judgments += table(
                ["子问题", "证据编号", "未解决项"],
                [
                    [
                        esc(c["subquestion"]),
                        esc("、".join(c["evidence_ids"])),
                        esc(c["unresolved"] or "未另外登记；不代表不存在缺口"),
                    ]
                    for c in analysis["coverage"]
                ],
            )
        stages.append(judgments)
        verification = run["verification"]
        checks = paragraph("尚无逐条语义复核记录。", "notice")
        if verification:
            checks = paragraph(
                "语义复核对应当前分析。"
                if run["verification_current"]
                else "此复核对应旧分析，不能用于当前分析。",
                "notice",
            )
            checks += paragraph(
                "复核者："
                + verification["verifier"]["name"]
                + "；"
                + verification["verifier"]["notes"]
            )
            checks += table(
                ["判断编号", "语义核验", "依据说明"],
                [
                    [esc(c["claim_id"]), esc(label(c["verdict"])), esc(c["rationale"])]
                    for c in verification["checks"]
                ],
            )
        checks += "<h2>已记录的质量门槛</h2>" + paragraph(
            "以下为运行中最后记录的结果；阅读操作不会重新执行质量核验。", "muted"
        )
        checks += table(
            ["门槛", "状态", "说明"],
            [
                [esc(g["gate_id"]), esc(label(g["state"])), esc(g["detail"])]
                for g in run["view"]["gates"]
            ],
        )
        stages.append(checks)
        review = run["review"]
        review_body = paragraph("尚未记录人工审阅，不能视为用户接受。", "notice")
        if review:
            review_body = paragraph(
                "该审阅对应当前研究依据。"
                if run["review_current"]
                else "这是历史审阅；当前研究依据已变化，需要重新审阅。",
                "notice",
            )
            review_body += paragraph(
                "审阅人：" + review["reviewer"] + "；决定：" + label(review["decision"])
            )
            review_body += paragraph(review["notes"]) + listing(review["checked_items"])
        stages.append(review_body)
        delivery_body = paragraph(
            "这里列出数据库登记的报告版本；PPT的逐页依据、文件保全与核验状态请在项目成果交付中查看。",
            "notice",
        )
        path = base + "/" + root + "/" + STAGES[7] + ".html"
        delivery_body += table(
            ["生成时间", "打开报告", "质量状态", "与当前依据关系"],
            [
                [
                    esc(d["created_at"]),
                    relative_link(path, d["relative_path"] + "/index.html", "研究报告与证据包"),
                    esc(label(d["quality_state"])),
                    "对应当前依据" if d["current_basis"] else "历史研究依据",
                ]
                for d in run["deliveries"]
            ],
        )
        stages.append(delivery_body)
        for name, body in zip(STAGES, stages, strict=True):
            path = root + "/" + name + ".html"
            files[path] = page(
                name, body, relative_link(path, root + "/index.html", "返回本轮研究过程")
            )
        path = root + "/index.html"
        body = paragraph(project["question"])
        body += paragraph(
            "执行："
            + label(run["view"]["execution_state"])
            + "；质量状态（已记录）："
            + label(run["view"]["quality_state"])
        )
        if run["view"]["waiting_reason"]:
            body += paragraph(run["view"]["waiting_reason"], "notice")
        summaries = [
            "任务范围与用途已冻结",
            f"{len(sources)} 项具体来源目标",
            f"{len(run['versions'])} 个取得的材料版本",
            f"{len(evidence)} 条精确证据",
            f"{len((analysis or {}).get('claims', []))} 条已提交判断",
            "当前分析已有复核" if run["verification_current"] else "未复核或复核已过期",
            "当前依据已有审阅记录（查看具体决定）"
            if run["review_current"]
            else "未审阅或历史审阅已过期",
            f"{len(run['deliveries'])} 个已登记报告版本",
        ]
        body += (
            '<div class="grid">'
            + "".join(
                '<article class="card"><h3>'
                + relative_link(path, root + "/" + name + ".html", name)
                + "</h3>"
                + paragraph(summary)
                + "</article>"
                for name, summary in zip(STAGES, summaries, strict=True)
            )
            + "</div>"
        )
        body += "<h2>真实执行时间线</h2>" + table(
            ["时间", "事件"],
            [
                [esc(event.get("at", event.get("created_at", "未记录"))), esc(label(event["kind"]))]
                for event in run["events"]
            ],
        )
        body += paragraph(
            "阶段页面是已记录内容的阅读视图，页面存在不代表该阶段通过。完整正文和图表请进入成果交付中的报告。",
            "notice",
        )
        files[path] = page(
            "研究过程 · " + project["project_id"],
            body,
            relative_link(path, f"研究项目/{project['project_id']}/index.html", "返回项目"),
        )
