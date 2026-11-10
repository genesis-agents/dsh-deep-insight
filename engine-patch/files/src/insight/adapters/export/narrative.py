"""Safe report view models and bounded rendering of fixed original PDF pages."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from insight.domain.contracts import PlatformError


def citation_fragments(text: str, citations: list[dict[str, Any]], source_ids: list[str]) -> list[dict[str, Any]]:
    """Keep report text escaped while resolving explicit references to saved quotations."""
    fragments: list[dict[str, Any]] = []
    pattern = r"\{\{evidence:([A-Za-z0-9_.-]+)\}\}|(ev_[a-f0-9]{32})|\[(\d+)[，,]\s*原文单元\s*(\d+)\]"
    end = 0
    for match in re.finditer(pattern, text):
        fragments.append({"text": text[end:match.start()]})
        if match[3]:
            source_index = int(match[3]) - 1
            rows = [e for e in citations if 0 <= source_index < len(source_ids)
                    and e["source_id"] == source_ids[source_index]
                    and e["locator"]["unit_index"] == int(match[4])]
        else:
            rows = [e for e in citations if e["evidence_id"] == (match[1] or match[2])]
        fragments.extend({"number": e["number"], "publisher": e["publisher"]} for e in rows)
        if not rows:
            fragments.append({"text": match[0]})
        end = match.end()
    fragments.append({"text": text[end:]})
    return fragments


def chart_view(block: dict[str, Any]) -> dict[str, Any]:
    padded = max([p["value"] for p in block["points"]] + [block.get("reference") or 0, 1]) * 1.12
    target = padded / 4
    magnitude = 10 ** math.floor(math.log10(target))
    step = min((magnitude * n for n in (1, 2, 2.5, 5, 10)), key=lambda n: abs(n - target))
    count = math.ceil(padded / step)
    maximum = count * step
    return {
        **block,
        "maximum": maximum,
        "points": [
            {**p, "width": p["value"] / maximum * 640, "y": 42 + i * 70}
            for i, p in enumerate(block["points"])
        ],
        "ticks": [{"x": 225 + 640 * i / count, "value": step * i} for i in range(count + 1)],
        "reference_x": 225 + (block.get("reference") or 0) / maximum * 640,
        "height": 90 + 70 * len(block["points"]),
    }


def report_view(package: dict[str, Any]) -> dict[str, Any]:
    sources = {s["source_id"]: s for s in package["frozen_input"]["sources"]}
    versions = {v["version_id"]: v for v in package["source_versions"]}
    citations = []
    for index, evidence in enumerate(package["context"]["evidence"], 1):
        version = versions[evidence["source_version_id"]]
        source = sources[version["source_id"]]
        citations.append(
            {
                **evidence,
                "number": index,
                "publisher": source["publisher"],
                "source_id": source["source_id"],
                "raw_path": package["materials"][version["raw_artifact_id"]],
                "origin": version["origin_uri"],
            }
        )
    numbered = {e["evidence_id"]: e for e in citations}
    claims = [
        {
            **c,
            "number": index,
            "citations": [numbered[link["evidence_id"]] for link in c["evidence_links"]],
        }
        for index, c in enumerate(package["analysis"]["claims"], 1)
    ]
    narrative = package["analysis"].get("narrative")
    if narrative:
        sections = []
        for section in narrative["sections"]:
            blocks = []
            for block in section["blocks"]:
                if block["kind"] == "diagram":
                    blocks.extend({"kind": "paragraph", "text": node["label"] + "：" + node["detail"], "claim_ids": block["claim_ids"]}
                                  for node in block["nodes"] if node["detail"].strip())
                elif block["kind"] == "chart":
                    blocks.append(chart_view(block))
                elif block["kind"] == "figure":
                    key = block["source_version_id"] + ":" + str(block["unit_index"])
                    version = versions[block["source_version_id"]]
                    blocks.append(
                        {
                            **block,
                            "image_path": package["figures"][key],
                            "raw_path": package["materials"][version["raw_artifact_id"]],
                            "publisher": sources[version["source_id"]]["publisher"],
                        }
                    )
                else:
                    blocks.append(block)
            sections.append({**section, "blocks": blocks})
        narrative = {**narrative, "sections": sections}
    source_rows = []
    for version in package["source_versions"]:
        source = sources[version["source_id"]]
        public_origin = version["origin_uri"]
        if not public_origin.startswith(("https://", "http://")):
            urls = re.findall(r"https?://[^\s；，。]+", " ".join(source["identity_basis"]))
            public_origin = urls[0] if urls else ""
        source_rows.append(
            {
                **version,
                **source,
                "public_origin": public_origin,
                "raw_path": package["materials"][version["raw_artifact_id"]],
            }
        )
    texts: dict[str, list[dict[str, Any]]] = {}

    def collect(value: Any) -> None:
        if isinstance(value, str):
            texts[value] = citation_fragments(value, citations, list(sources))
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    collect(package["analysis"])
    collect(narrative)
    return {
        "texts": texts,
        "narrative": narrative,
        "claims": claims,
        "citations": citations,
        "sources": source_rows,
    }


def render_pdf_page(data: bytes, page: int, staging: Path) -> bytes:
    executable = shutil.which("pdftoppm")
    if not executable:
        raise PlatformError(
            "UNSUPPORTED_CAPABILITY", "PDF figures require the configured pdftoppm executable"
        )
    with tempfile.TemporaryDirectory(prefix="figure-", dir=staging) as name:
        directory = Path(name)
        source, target = directory / "original.pdf", directory / "page"
        source.write_bytes(data)
        try:
            subprocess.run(
                [
                    executable,
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-singlefile",
                    "-scale-to",
                    "1800",
                    "-png",
                    str(source),
                    str(target),
                ],
                capture_output=True,
                check=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            result = target.with_suffix(".png").read_bytes()
        except (OSError, subprocess.SubprocessError) as exc:
            raise PlatformError("EXPORT_FAILED", "Original PDF page could not be rendered") from exc
        if len(result) > 15_000_000 or not result.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PlatformError("EXPORT_FAILED", "Invalid or oversized rendered PDF page")
        return result


def narrative_markdown(package: dict[str, Any]) -> str:
    analysis = package["analysis"]
    narrative = analysis.get("narrative")
    if not narrative:
        return "\n".join(
            [
                "# " + analysis["title"],
                "",
                analysis["synthesis"],
                *[
                    "\n## " + c["statement"] + "\n\n" + "\n\n".join(c["conditions"])
                    for c in analysis["claims"]
                ],
            ]
        )
    lines = [
        "# " + narrative["headline"],
        "",
        narrative["standfirst"],
        "",
        "## 核心判断",
        *["- " + t["text"] for t in narrative["takeaways"]],
    ]
    for section in narrative["sections"]:
        lines.extend(
            [
                "",
                "## " + section["question"],
                "",
                section["bridge"],
                "",
                "**" + section["answer"] + "**",
            ]
        )
        for block in section["blocks"]:
            if block["kind"] == "paragraph":
                lines.extend(["", block["text"]])
            elif block["kind"] == "table":
                lines.extend(
                    [
                        "",
                        block["caption"],
                        " | ".join(block["columns"]),
                        " | ".join(["---"] * len(block["columns"])),
                        *[" | ".join(row["cells"]) for row in block["rows"]],
                    ]
                )
            elif block["kind"] == "figure":
                key = block["source_version_id"] + ":" + str(block["unit_index"])
                lines.extend(
                    [
                        "",
                        "![" + block["caption"] + "](" + package["figures"][key] + ")",
                        block["explanation"],
                    ]
                )
            elif block["kind"] == "diagram":
                lines.extend(
                    [
                        "",
                        block["caption"],
                        *[n["label"] + "：" + n["detail"] for n in block["nodes"]],
                        block["note"],
                    ]
                )
            elif block["kind"] == "chart":
                lines.extend(
                    [
                        "",
                        block["caption"],
                        *[
                            p["label"] + "：" + str(p["value"]) + " " + block["unit"]
                            for p in block["points"]
                        ],
                        block["note"],
                    ]
                )
    if narrative.get("conclusion"):
        lines.extend(["", "## 总结与判断", narrative["conclusion"]["text"]])
    if narrative.get("recommendations"):
        lines.extend(
            ["", "## 下一步建议", *["- " + item["text"] for item in narrative["recommendations"]]]
        )
    lines.extend(["", "## 范围与限制", *["- " + text for text in analysis["limitations"]]])
    return "\n".join(lines)
