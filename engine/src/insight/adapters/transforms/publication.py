"""Read explicit publication metadata; retrieval timestamps never become publication dates."""

import json
from datetime import date, datetime

from bs4 import BeautifulSoup


def publication_date(data: bytes) -> str | None:
    """Return one unambiguous declared date, or None when absent, invalid or conflicting."""
    soup = BeautifulSoup(data, "html.parser")
    candidates: list[str] = []
    for tag in soup.find_all("meta"):
        key = str(tag.get("property") or tag.get("name") or tag.get("itemprop") or "").lower()
        if key in (
            "article:published_time",
            "citation_publication_date",
            "citation_date",
            "dcterms.issued",
            "parsely-pub-date",
            "datepublished",
            "dc.date.issued",
        ):
            candidates.append(str(tag.get("content", "")))
    for tag in soup.find_all("time"):
        if "datePublished" in str(tag.get("itemprop", "")).split() or tag.has_attr("pubdate"):
            candidates.append(str(tag.get("datetime", "")))
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            value = json.loads(tag.get_text())
        except (ValueError, TypeError):
            continue
        stack = value if isinstance(value, list) else [value]
        for item in stack:
            if isinstance(item, dict):
                if isinstance(item.get("datePublished"), str):
                    candidates.append(item["datePublished"])
                graph = item.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
    dates = set()
    for value in candidates:
        try:
            normalized = value.strip().replace("/", "-")
            parsed = (
                date.fromisoformat(normalized)
                if len(normalized) == 10
                else datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()
            )
            dates.add(parsed.isoformat())
        except ValueError:
            continue
    return next(iter(dates)) if len(dates) == 1 else None
