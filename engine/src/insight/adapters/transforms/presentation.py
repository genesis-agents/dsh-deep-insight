"""Bounded OOXML package validation without an authoring runtime."""

import io
import posixpath
import re
import zipfile
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from insight.domain.contracts import PlatformError


class PptxInspector:
    def slide_count(self, content: bytes) -> int:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = archive.namelist()
                if (
                    len(members) != len(set(members))
                    or sum(i.file_size for i in archive.infolist()) > 250_000_000
                ):
                    raise ValueError("Duplicate members or oversized OOXML package")
                if archive.testzip():
                    raise ValueError("PPTX CRC failure")
                for name in members:
                    if name.startswith("/") or ".." in name.split("/") or "\\" in name:
                        raise ValueError("Unsafe OOXML member")
                    if not name.endswith(".rels"):
                        continue
                    base = posixpath.dirname(posixpath.dirname(name))
                    for rel in ET.fromstring(archive.read(name)):
                        target = unquote(rel.attrib.get("Target", ""))
                        if rel.attrib.get("TargetMode") == "External":
                            if rel.attrib.get("Type", "").endswith(
                                "/hyperlink"
                            ) and target.startswith(("https://", "http://", "mailto:")):
                                continue
                            raise ValueError("External file dependency in presentation")
                        resolved = posixpath.normpath(posixpath.join(base, target)).lstrip("/")
                        if resolved not in members:
                            raise ValueError("Broken OOXML relationship")
                slides = [n for n in members if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
                presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
                order = presentation.find(
                    "{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst"
                )
                if not slides or order is None or len(order) != len(slides):
                    raise ValueError("Slide order and package differ")
                return len(slides)
        except (KeyError, ET.ParseError, ValueError, zipfile.BadZipFile) as exc:
            raise PlatformError("INVALID_MATERIAL", str(exc)) from exc
