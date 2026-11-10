from __future__ import annotations

import io
import json
import zipfile
from importlib.metadata import version

from bs4 import BeautifulSoup

from insight.domain.contracts import ExtractedDocument, MaterialRole, PlatformError, TextUnit


def sniff_type(data: bytes, declared: str) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if sum(i.file_size for i in z.infolist()) > 200_000_000:
                    raise PlatformError(
                        "INVALID_MATERIAL", "Office archive expansion limit exceeded"
                    )
                if "ppt/presentation.xml" in z.namelist():
                    return (
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                    )
                if "word/document.xml" in z.namelist():
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except zipfile.BadZipFile as exc:
            raise PlatformError("INVALID_MATERIAL", "Invalid Office archive") from exc
    if data.lstrip()[:200].lower().startswith((b"<!doctype html", b"<html")):
        return "text/html"
    return declared.split(";", 1)[0].lower()


class DocumentExtractor:
    def __init__(self, revision: str = "2") -> None:
        libraries = ",".join(
            f"{n}={version(n)}" for n in ("pypdf", "python-docx", "python-pptx", "trafilatura")
        )
        self._processor_ref = f"document-text@{revision};{libraries}"

    @property
    def processor_ref(self) -> str:
        return self._processor_ref

    def extract(self, data: bytes, media_type: str, role: MaterialRole) -> ExtractedDocument:
        media_type = sniff_type(data, media_type)
        units: list[TextUnit] = []
        warnings: list[str] = []
        try:
            if role == "source_metadata":
                units = [TextUnit(index=1, kind="metadata", text=data.decode("utf-8"))]
            elif role in ("raw_video", "raw_audio", "derived_slide_frames", "browser_capture"):
                return ExtractedDocument(
                    processor_ref=self.processor_ref,
                    units=(),
                    warnings=(
                        "Binary media archived; no fabricated text or OCR. See associated timestamp manifest and open original media for visual review",
                    ),
                )
            elif role == "transcript" and media_type == "application/json":
                transcript = json.loads(data)
                previous = -1.0
                for i, segment in enumerate(transcript["segments"], 1):
                    start, duration = float(segment["start"]), float(segment["duration"])
                    if (
                        start < previous
                        or start < 0
                        or duration <= 0
                        or not segment["text"].strip()
                    ):
                        raise ValueError("Invalid or unordered transcript segment")
                    previous = start
                    units.append(
                        TextUnit(
                            index=i,
                            kind="transcript_segment",
                            text=segment["text"],
                            start_seconds=start,
                            end_seconds=start + duration,
                        )
                    )
                warnings.append(
                    "Timed caption/ASR text; generated subtitles and proper names require verification; not a visual interpretation"
                )
            elif media_type == "application/pdf":
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(data))
                if reader.is_encrypted:
                    raise PlatformError(
                        "ACCESS_REQUIRED", "Encrypted PDF requires a separate authorized import"
                    )
                if len(reader.pages) > 1000:
                    raise PlatformError("INVALID_MATERIAL", "PDF page limit exceeded")
                for i, page in enumerate(reader.pages, 1):
                    text = page.extract_text() or ""
                    units.append(TextUnit(index=i, kind="page", text=text))
                    if not text.strip():
                        warnings.append(f"Page {i} has no text; OCR not performed")
            elif "presentationml" in media_type:
                from pptx import Presentation

                presentation = Presentation(io.BytesIO(data))
                for i, slide in enumerate(presentation.slides, 1):
                    texts = []
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            texts.append(shape.text)
                        elif shape.has_table:
                            texts.extend(
                                " | ".join(c.text for c in row.cells) for row in shape.table.rows
                            )
                    units.append(TextUnit(index=i, kind="slide", text="\n".join(texts)))
                warnings.append(
                    "Slide text extracted; diagrams, animations and images require visual review"
                )
            elif "wordprocessingml" in media_type:
                from docx import Document

                document = Document(io.BytesIO(data))
                text = "\n".join(p.text for p in document.paragraphs)
                for table in document.tables:
                    text += "\n" + "\n".join(
                        " | ".join(c.text for c in r.cells) for r in table.rows
                    )
                units = [TextUnit(index=1, kind="document", text=text)]
                warnings.append(
                    "DOCX text order groups tables after paragraphs; locator is extracted text, not rendered page"
                )
            elif media_type == "text/html":
                from trafilatura import extract

                soup = BeautifulSoup(data, "html.parser")
                title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
                if any(
                    s in title for s in ("just a moment", "access denied", "sign in", "log in")
                ) or soup.select_one('input[type="password"]'):
                    raise PlatformError("ACCESS_REQUIRED", "Login, challenge or access-denied page")
                text = (
                    extract(data, include_tables=True, include_links=False, favor_precision=True)
                    or ""
                )
                # Publisher-supplied Article JSON-LD can contain a complete body on JS-heavy pages.
                for script in soup.select('script[type="application/ld+json"]'):
                    try:
                        structured = json.loads(script.get_text())
                        nodes = structured if isinstance(structured, list) else [structured]
                        for node in list(nodes):
                            if isinstance(node, dict) and isinstance(node.get("@graph"), list):
                                nodes.extend(node["@graph"])
                        for node in nodes:
                            body = node.get("articleBody") if isinstance(node, dict) else None
                            if isinstance(body, str):
                                body = BeautifulSoup(body, "html.parser").get_text(" ", strip=True)
                                if len(body) > len(text):
                                    text = body
                                    warnings.append(
                                        "Body extracted from publisher Article JSON-LD; rendered visuals still require review"
                                    )
                    except (ValueError, TypeError):
                        continue
                if not text or len(text.strip()) < 80:
                    raise PlatformError(
                        "INVALID_MATERIAL", "No substantive article body was extracted"
                    )
                units = [TextUnit(index=1, kind="document", text=text)]
                warnings.append(
                    "HTML text extraction is derived content; visual charts require separate inspection"
                )
            elif role == "post" and media_type == "application/json":
                post = json.loads(data)
                note = post.get("note_tweet") or post.get("note_post")
                text = (
                    note["text"]
                    if isinstance(note, dict) and isinstance(note.get("text"), str)
                    else post["text"]
                )
                units = [TextUnit(index=1, kind="post", text=text)]
            elif media_type.startswith("text/"):
                units = [
                    TextUnit(
                        index=1, kind="document", text=data.decode("utf-8-sig", errors="strict")
                    )
                ]
            else:
                raise PlatformError("UNSUPPORTED_CAPABILITY", f"No extractor for {media_type}")
        except PlatformError:
            raise
        except Exception as exc:
            raise PlatformError(
                "INVALID_MATERIAL", f"Document parser failed ({type(exc).__name__})"
            ) from exc
        if not any(u.text.strip() for u in units):
            raise PlatformError(
                "NO_TEXT", "No text found; scanned material requires an OCR capability"
            )
        return ExtractedDocument(
            processor_ref=self.processor_ref, units=tuple(units), warnings=tuple(warnings)
        )
