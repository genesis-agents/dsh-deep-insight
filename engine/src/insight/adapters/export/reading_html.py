"""Shared HTML primitives for immutable reading editions and project folders."""

from __future__ import annotations

import html
import os
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

CSS = """
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f3f5f7;color:#172b40;
font:16px/1.8 system-ui,'Microsoft YaHei',sans-serif}main{max-width:1240px;margin:32px auto;padding:28px;
background:white;border-radius:14px}a{color:#1756a0;overflow-wrap:anywhere}h1{font-size:30px;line-height:1.4}
h2{margin-top:32px;font-size:22px}h3{font-size:18px}p,li,td{overflow-wrap:anywhere}table{border-collapse:collapse;
width:100%;margin:20px 0;font-size:14px}th,td{padding:12px;border:1px solid #dce2e8;text-align:left;
vertical-align:top}th{background:#f0f4f8}blockquote{margin:12px 0;padding:14px 20px;background:#f4f7fa;
border-left:4px solid #3e6c9c;white-space:pre-wrap}.notice{padding:16px;background:#fff5df;border-radius:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}.card{padding:18px;
border:1px solid #dce2e8;border-radius:10px}.muted{color:#5a6875;font-size:14px}.text{white-space:pre-wrap}
input,select{font:inherit;padding:8px;border:1px solid #b6c2ce;border-radius:6px;max-width:100%}
.filters{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}nav{margin:12px 0 24px}code{font-size:13px}
@media(max-width:700px){main{margin:0;padding:16px;border-radius:0}table{display:block;overflow:auto}}
"""


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def paragraph(value: Any, css: str = "text") -> str:
    return f'<p class="{css}">{esc(value)}</p>'


def listing(values: Any) -> str:
    return "<ul>" + "".join("<li>" + esc(v) + "</li>" for v in values) + "</ul>"


def table(headers: list[str], rows: list[list[str]]) -> str:
    return (
        "<table><thead><tr>"
        + "".join("<th>" + esc(h) + "</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join("<td>" + cell + "</td>" for cell in row) + "</tr>" for row in rows
        )
        + "</tbody></table>"
    )


def relative_link(current: str, target: str, text: str, *, download: bool = False) -> str:
    path = os.path.relpath(target, str(PurePosixPath(current).parent)).replace("\\", "/")
    return (
        '<a href="'
        + esc(quote(path, safe="/"))
        + ('" download>' if download else '">')
        + esc(text)
        + "</a>"
    )


def page(title: str, body: str, home: str = "") -> bytes:
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)}</title><style>{CSS}</style><main>"
        + ("<nav>" + home + "</nav>" if home else "")
        + f"<h1>{esc(title)}</h1>{body}</main></html>"
    ).encode()


def collection_table(coverage: dict[str, Any]) -> str:
    if not coverage.get("assessed"):
        return paragraph(
            "历史研究未独立声明渠道要求；文档取得成功不代表官网、论文、X、YouTube等渠道已经覆盖。",
            "notice",
        )
    states = {
        "acquired": "已取得",
        "partial": "部分取得",
        "failed": "获取失败",
        "unsupported": "未实现或缺少依赖",
        "access_required": "待授权或限流",
        "not_planned": "漏排渠道或目标",
        "not_attempted": "尚未执行",
        "excluded": "明确排除",
    }
    channels = {
        "official": "官网",
        "paper": "论文",
        "conference": "会议原稿",
        "youtube": "YouTube",
        "x": "X",
        "feed": "RSS/Atom发现",
        "local": "本地资料",
    }
    return paragraph(
        "必需渠道均满足"
        if coverage["complete"]
        else "采集覆盖未完成：下列缺口不能由其他文档成功抵消。",
        "notice",
    ) + table(
        ["渠道", "要求", "取得目标", "实际结果", "范围与原因"],
        [
            [
                esc(channels.get(c["channel"], c["channel"])),
                esc(
                    {"required": "必需", "optional": "可选", "excluded": "明确排除"}[
                        c["disposition"]
                    ]
                ),
                esc("、".join(c["goals"])),
                esc(states[c["state"]]),
                paragraph(c["rationale"])
                + "".join(paragraph(r["reason_code"] + "：" + r["detail"]) for r in c["reasons"]),
            ]
            for c in coverage["channels"]
        ],
    )
