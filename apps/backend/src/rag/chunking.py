"""纯函数式的字符预算分块；不做持久化，也不调用模型。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_text_splitters import RecursiveCharacterTextSplitter

from utils.documents import DocumentElement, ParsedDocument

ChunkStrategy = Literal["recursive", "structure"]
CHUNKER_VERSIONS: dict[ChunkStrategy, str] = {
    "recursive": "recursive-v1",
    "structure": "structure-v1",
}


@dataclass(frozen=True, kw_only=True)
class ChunkMetadata:
    heading_path: list[str] = field(default_factory=list)
    chunk_strategy: ChunkStrategy | None = None
    chunker_version: str | None = None
    structure_quality: str | None = None
    section_id: str | None = None
    element_start: int | None = None
    element_end: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    split_reason: str | None = None

    def structure_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in ChunkMetadata.__dataclass_fields__}

    def chroma_metadata(self) -> dict[str, str | int]:
        payload = self.structure_payload()
        payload["heading_path_json"] = json.dumps(payload.pop("heading_path"), ensure_ascii=False)
        return {name: value for name, value in payload.items() if value is not None}

    @staticmethod
    def from_chroma(metadata: dict) -> dict[str, Any]:
        path = json.loads(metadata["heading_path_json"])
        if not isinstance(path, list) or not all(isinstance(title, str) for title in path):
            raise ValueError("Invalid chunk heading_path_json")
        strategy = metadata["chunk_strategy"]
        version = metadata["chunker_version"]
        if strategy not in CHUNKER_VERSIONS or version != CHUNKER_VERSIONS[strategy]:
            raise ValueError("Chunk metadata does not match the current chunker; rebuild the index")
        payload = {name: metadata.get(name) for name in ChunkMetadata.__dataclass_fields__}
        payload.update(heading_path=path, chunk_strategy=strategy, chunker_version=version)
        return payload


@dataclass(frozen=True)
class ChunkDraft(ChunkMetadata):
    content: str


def _validate_budget(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_size < 1 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap must be nonnegative and smaller than chunk_size")


def chunk_recursive(text: str, *, chunk_size: int, chunk_overlap: int) -> list[ChunkDraft]:
    _validate_budget(chunk_size, chunk_overlap)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", ". ", " ", ""],
    )
    drafts = [
        ChunkDraft(content=chunk.strip()) for chunk in splitter.split_text(text) if chunk.strip()
    ]
    if not drafts:
        raise ValueError("The document did not contain extractable text.")
    return drafts


def _pack(units: list[str], budget: int) -> list[str]:
    """保留全部字符，仅在单个单元超长时才将其拆分。"""
    result: list[str] = []
    current = ""
    for unit in units:
        if len(current) + len(unit) > budget and current:
            result.append(current)
            current = ""
        if len(unit) > budget:
            last_start = ((len(unit) - 1) // budget) * budget
            result.extend(unit[start : start + budget] for start in range(0, last_start, budget))
            unit = unit[last_start:]
        current += unit
    if current:
        result.append(current)
    return result


def _sentences(text: str) -> list[str]:
    return re.findall(r".*?(?:[。！？!?]+|\.(?=\s|$)|\n\n+|$)", text, re.DOTALL)


def _element_parts(element: DocumentElement, budget: int) -> list[str]:
    text = element.text
    if len(text) <= budget:
        return [text]
    if element.kind == "table":
        lines = text.splitlines(keepends=True)
        header = "".join(lines[: element.table_header_rows])
        rows = lines[element.table_header_rows :]
        if rows and header and len(header) < budget:
            result: list[str] = []
            normal_rows: list[str] = []
            for row in rows:
                if len(header) + len(row) > budget:
                    result.extend(
                        header + part for part in _pack(normal_rows, budget - len(header))
                    )
                    normal_rows = []
                    # 表头加上一行超长行无法保持表格格式。
                    result.extend(_pack([header + row], budget))
                else:
                    normal_rows.append(row)
            result.extend(header + part for part in _pack(normal_rows, budget - len(header)))
            return result
        return _pack(lines, budget)
    if element.kind == "code":
        lines = text.splitlines(keepends=True)
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", lines[0]) if lines else None
        if match and len(lines) > 1:
            opener = lines[0]
            marker = match[1]
            closed = bool(
                re.fullmatch(
                    r" {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*", lines[-1]
                )
            )
            body = lines[1:-1] if closed else lines[1:]
            closing = "\n" + (lines[-1].rstrip("\r\n") if closed else marker)
            available = budget - len(opener) - len(closing)
            if available > 0:
                return [opener + part + closing for part in _pack(body, available)]
        return _pack(lines, budget)
    if element.kind == "list":
        units = re.split(r"(?m)(?=^\s*(?:[-+*]|\d+[.)])[ \t]+)", text)
        return _pack(
            [
                part
                for unit in units
                for part in (_sentences(unit) if len(unit) > budget else [unit])
            ],
            budget,
        )
    return _pack(_sentences(text), budget)


def _prefix(path: list[str], chunk_size: int) -> str:
    if not path:
        return ""
    display = " > ".join(path)
    allowance = chunk_size // 4
    if allowance < 3:
        return ""
    if len(display) + 2 > allowance:
        tail_size = allowance - 3
        display = "…" + (display[-tail_size:] if tail_size else "")
    return display + "\n\n"


def _overlap(text: str, budget: int, *, starts_at_boundary: bool, whole_element: bool) -> str:
    if whole_element and len(text) <= budget:
        return text
    sentences = _sentences(text)
    if not starts_at_boundary:
        # 按字符切出的片段首句只是一个后缀。
        sentences = sentences[1:]
    tail = ""
    for sentence in reversed(sentences):
        if not sentence or not sentence.strip():
            continue
        # 按字符切出的句子不是完整的重叠单元。
        if not re.search(r"[。！？!?]|\.(?:\s|$)|\n\n", sentence):
            break
        if len(sentence) + len(tail) > budget:
            break
        tail = sentence + tail
    return tail


def chunk_structure(
    document: ParsedDocument, *, chunk_size: int, chunk_overlap: int
) -> list[ChunkDraft]:
    _validate_budget(chunk_size, chunk_overlap)
    drafts: list[ChunkDraft] = []
    stack: list[tuple[int, str]] = []
    section = 0
    body: list[DocumentElement] = []

    def flush_section() -> None:
        if not body:
            return
        path = [title for _, title in stack]
        prefix = _prefix(path, chunk_size)
        budget = chunk_size - len(prefix)
        overlap_budget = min(chunk_overlap, budget // 2)
        pending: list[tuple[str, DocumentElement]] = []
        previous: tuple[str, DocumentElement, bool, bool] | None = None

        def emit(
            reason: str, *, allow_overlap: bool = True, starts_at_boundary: bool = True
        ) -> None:
            nonlocal pending, previous
            if not pending:
                return
            text = "\n\n".join(part for part, _ in pending)
            sources = [element for _, element in pending]
            if (
                allow_overlap
                and previous
                and all(element.kind in {"paragraph", "list"} for element in sources)
            ):
                overlap = _overlap(
                    previous[0],
                    overlap_budget,
                    starts_at_boundary=previous[2],
                    whole_element=previous[3],
                )
                if overlap and len(overlap) + 2 + len(text) <= budget:
                    text = overlap + "\n\n" + text
                    sources.insert(0, previous[1])
            if text.strip():
                pages = [
                    element.page_number for element in sources if element.page_number is not None
                ]
                starts = [
                    element.line_start for element in sources if element.line_start is not None
                ]
                ends = [element.line_end for element in sources if element.line_end is not None]
                drafts.append(
                    ChunkDraft(
                        content=prefix + text,
                        heading_path=list(path),
                        structure_quality=document.structure_quality,
                        section_id=f"s{section:06d}",
                        element_start=min(element.position for element in sources),
                        element_end=max(element.position for element in sources),
                        page_start=min(pages) if pages else None,
                        page_end=max(pages) if pages else None,
                        line_start=min(starts) if starts else None,
                        line_end=max(ends) if ends else None,
                        split_reason=reason,
                    )
                )
            last_text, last_element = pending[-1]
            previous = (
                (last_text, last_element, starts_at_boundary, last_text == last_element.text)
                if last_element.kind in {"paragraph", "list"}
                else None
            )
            pending = []

        for element in body:
            if not element.text.strip():
                continue
            if len(element.text) > budget:
                emit("size")
                plain = element.kind in {"paragraph", "list"}
                # 为长文本的完整句重叠预留空间。
                part_budget = (
                    max(1, budget - overlap_budget - 2) if plain and overlap_budget else budget
                )
                # 正文/列表部分必须逐字保留源文本。需要跟踪句子
                # 边界，确保按字符切出的句子后缀不会被当作
                # 完整的重叠单元复制。
                boundaries = {0}
                position = 0
                if plain:
                    for sentence in _sentences(element.text):
                        position += len(sentence)
                        boundaries.add(position)
                offset = 0
                for part in _element_parts(element, part_budget):
                    pending = [(part, element)]
                    emit(
                        "oversized_element",
                        allow_overlap=plain,
                        starts_at_boundary=offset in boundaries,
                    )
                    offset += len(part)
                continue
            if (
                pending
                and sum(len(part) for part, _ in pending) + 2 * len(pending) + len(element.text)
                > budget
            ):
                emit("size")
            pending.append((element.text, element))
        emit("section")

    last_page = None
    for element in document.elements:
        if element.kind == "heading":
            flush_section()
            body = []
            section += 1
            level = element.heading_level or 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, " ".join(element.text.split())))
        else:
            if element.page_number != last_page and body:
                flush_section()
                body = []
                section += 1
            last_page = element.page_number
            body.append(element)
    flush_section()
    if not drafts:
        raise ValueError(
            "The document did not contain extractable body text (headings alone are insufficient)."
        )
    return drafts
