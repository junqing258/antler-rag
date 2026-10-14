from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf", ".docx"}


class UnsupportedDocument(ValueError):
    pass


def extract_text(filename: str, content: bytes) -> str:
    """Extract text without invoking an external service."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise UnsupportedDocument(f"Unsupported file type '{suffix}'. Supported: {supported}")
    if suffix in {".txt", ".md", ".markdown"}:
        return content.decode("utf-8", errors="replace").strip()
    if suffix == ".pdf":
        reader = PdfReader(BytesIO(content))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
    return "\n\n".join(element.text for element in _docx_elements(content)).strip()


@dataclass(frozen=True)
class DocumentElement:
    kind: Literal["heading", "paragraph", "list", "table", "code"]
    text: str
    position: int
    heading_level: int | None = None
    page_number: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    table_header_rows: int = 0


@dataclass(frozen=True)
class ParsedDocument:
    elements: list[DocumentElement]
    structure_quality: Literal["headings", "paragraphs", "page_text"]


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?)|[ \t]*)$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_LIST = re.compile(r"^\s*(?:[-+*]|\d+[.)])[ \t]+")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _text_elements(text: str, *, markdown: bool = False) -> list[DocumentElement]:
    lines = text.splitlines()
    result: list[DocumentElement] = []
    i = 0

    def emit(kind, start, end, *, title=None, level=None, headers=0):
        result.append(
            DocumentElement(
                kind=kind,
                text=title if title is not None else "\n".join(lines[start:end]),
                position=len(result),
                heading_level=level,
                line_start=start + 1,
                line_end=end,
                table_header_rows=headers,
            )
        )

    def special(index: int) -> bool:
        line = lines[index]
        return bool(
            _FENCE.match(line)
            or _ATX.match(line)
            or _LIST.match(line)
            or line.startswith(("    ", "\t"))
            or (
                index + 1 < len(lines)
                and (
                    _SETEXT.match(lines[index + 1])
                    or ("|" in line and _TABLE_RULE.match(lines[index + 1]))
                )
            )
        )

    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        start = i
        fence = _FENCE.match(lines[i]) if markdown else None
        if fence:
            marker = fence[1]
            i += 1
            while i < len(lines):
                closing = re.fullmatch(
                    r" {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*",
                    lines[i],
                )
                i += 1
                if closing:
                    break
            emit("code", start, i)
        elif markdown and (
            html := re.match(
                r"^ {0,3}(?:<!--|<(div|table|pre|script|style|section|article)(?:[ \t>]|$))",
                lines[i],
                re.IGNORECASE,
            )
        ):
            tag = html[1]
            terminator = "-->" if tag is None else f"</{tag}>"
            i += 1
            if terminator not in lines[start].lower():
                while i < len(lines):
                    closed = terminator in lines[i].lower()
                    if not lines[i].strip() and tag not in {None, "script", "style", "pre"}:
                        break
                    i += 1
                    if closed:
                        break
            emit("paragraph", start, i)
        elif markdown and lines[i].startswith(("    ", "\t")):
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith(("    ", "\t"))):
                i += 1
            emit("code", start, i)
        elif markdown and (heading := _ATX.match(lines[i])):
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading[2] or "").strip()
            emit("heading", i, i + 1, title=title, level=len(heading[1]))
            i += 1
        elif markdown and i + 1 < len(lines) and (underline := _SETEXT.match(lines[i + 1])):
            emit(
                "heading",
                i,
                i + 2,
                title=lines[i].strip(),
                level=1 if underline[1][0] == "=" else 2,
            )
            i += 2
        elif (
            markdown and i + 1 < len(lines) and "|" in lines[i] and _TABLE_RULE.match(lines[i + 1])
        ):
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                i += 1
            emit("table", start, i, headers=2)
        elif markdown and _LIST.match(lines[i]):
            i += 1
            while (
                i < len(lines)
                and lines[i].strip()
                and (_LIST.match(lines[i]) or lines[i].startswith((" ", "\t")))
                and not _FENCE.match(lines[i])
            ):
                i += 1
            emit("list", start, i)
        else:
            i += 1
            while i < len(lines) and lines[i].strip() and not (markdown and special(i)):
                i += 1
            emit("paragraph", start, i)
    return result


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style
    visited: set[str] = set()
    # Explicit outline levels override the style's named hierarchy.
    properties = [paragraph._p.pPr]
    named = None
    while style is not None and style.style_id not in visited:
        visited.add(style.style_id)
        match = re.fullmatch(r"Heading\s*([1-9])", style.name or "", re.IGNORECASE)
        if match and named is None:
            named = int(match[1])
        properties.append(style.element.pPr)
        style = style.base_style
    for prop in properties:
        if prop is not None:
            outline = prop.find(qn("w:outlineLvl"))
            if outline is not None:
                value = int(outline.get(qn("w:val")))
                return value + 1 if 0 <= value <= 8 else None
    return named


def _docx_elements(content: bytes) -> list[DocumentElement]:
    document = DocxDocument(BytesIO(content))
    elements: list[DocumentElement] = []
    for child in document.element.body:
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            if not paragraph.text.strip():
                continue
            level = _heading_level(paragraph)
            style = paragraph.style
            is_list = paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None
            while style is not None and not is_list:
                is_list = (
                    style.element.pPr is not None
                    and style.element.pPr.numPr is not None
                    or (style.name or "").lower().startswith("list")
                )
                style = style.base_style
            elements.append(
                DocumentElement(
                    kind="heading" if level else "list" if is_list else "paragraph",
                    text=paragraph.text,
                    position=len(elements),
                    heading_level=level,
                )
            )
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            rows: list[str] = []
            headers = 0
            for index, row in enumerate(table.rows):
                cells: list[str] = []
                previous = None
                for cell in row.cells:
                    # Only discard a repeated merged cell, not equal independent cells.
                    if cell._tc is not previous:
                        cells.append(cell.text.strip())
                    previous = cell._tc
                rows.append(" | ".join(cells))
                header = row._tr.trPr.find(qn("w:tblHeader")) if row._tr.trPr is not None else None
                if (
                    index == headers
                    and header is not None
                    and header.get(qn("w:val"), "1") not in {"0", "false", "off"}
                ):
                    headers += 1
            if any(row.strip(" |") for row in rows):
                elements.append(
                    DocumentElement(
                        kind="table",
                        text="\n".join(rows),
                        position=len(elements),
                        table_header_rows=headers,
                    )
                )
    return elements


def parse_document(filename: str, content: bytes) -> ParsedDocument:
    """Parse a bounded set of block structures without guessing layout or headings."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocument(
            f"Unsupported file type '{suffix}'. Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    if suffix == ".docx":
        elements = _docx_elements(content)
    elif suffix == ".pdf":
        elements = []
        for page_number, page in enumerate(PdfReader(BytesIO(content)).pages, 1):
            for element in _text_elements(page.extract_text() or ""):
                elements.append(
                    DocumentElement(
                        kind="paragraph",
                        text=element.text,
                        position=len(elements),
                        page_number=page_number,
                    )
                )
        return ParsedDocument(elements, "page_text")
    else:
        elements = _text_elements(
            content.decode("utf-8", errors="replace"), markdown=suffix in {".md", ".markdown"}
        )
    quality = "headings" if any(element.kind == "heading" for element in elements) else "paragraphs"
    return ParsedDocument(elements, quality)
