from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from rag.chunking import chunk_recursive, chunk_structure
from utils.documents import DocumentElement, ParsedDocument, extract_text, parse_document


def chunks(text, size=900, overlap=150):
    return chunk_structure(
        parse_document("doc.md", text.encode()), chunk_size=size, chunk_overlap=overlap
    )


def test_handbook_and_parent_introduction_have_distinct_sections():
    text = (Path(__file__).parents[1] / "fixtures/structure_handbook.md").read_text()
    drafts = chunks(text)
    assert [draft.heading_path for draft in drafts] == [
        ["员工手册", "请假制度"],
        ["员工手册", "请假制度", "年假"],
        ["员工手册", "请假制度", "病假"],
        ["员工手册", "报销制度"],
    ]
    assert len({draft.section_id for draft in drafts}) == 4
    assert "员工连续工作" in drafts[1].content and "提前三个工作日" in drafts[1].content
    assert "病假" not in drafts[1].content
    assert drafts[1].line_start == 6 and drafts[1].line_end == 8


def test_intro_jump_repeated_and_consecutive_headings():
    drafts = chunks(
        "开头导言。\n# 根\n### 跳级\n正文一。\n### 跳级\n正文二。\n## 中间\n### 末尾\n正文三。"
    )
    assert [draft.heading_path for draft in drafts] == [
        [],
        ["根", "跳级"],
        ["根", "跳级"],
        ["根", "中间", "末尾"],
    ]
    assert drafts[1].section_id != drafts[2].section_id
    with pytest.raises(ValueError, match="body text"):
        chunks("# 只有标题\n## 子标题")


def test_markdown_blocks_ignore_headings_in_code_and_html():
    text = "标题\n====\n正文\n\n~~~python\n# 代码标题\n    print('x')\n~~~\n\n    # 缩进代码\n\n- 项目一\n  续行\n- 项目二\n\n| 列 | 值 |\n| --- | :---: |\n| A | B |\n\n<div>\n# HTML 内文本\n</div>\n\n末尾"
    parsed = parse_document("doc.markdown", text.encode())
    assert [element.kind for element in parsed.elements] == [
        "heading",
        "paragraph",
        "code",
        "code",
        "list",
        "table",
        "paragraph",
        "paragraph",
    ]
    assert parsed.elements[2].text == "~~~python\n# 代码标题\n    print('x')\n~~~"
    assert parsed.elements[5].table_header_rows == 2
    assert all(
        draft.heading_path == ["标题"]
        for draft in chunk_structure(parsed, chunk_size=100, chunk_overlap=10)
    )


def test_txt_uses_only_paragraphs():
    parsed = parse_document("doc.txt", "第一章\n一、短句\n\n下一段".encode())
    assert parsed.structure_quality == "paragraphs"
    assert [element.kind for element in parsed.elements] == ["paragraph", "paragraph"]
    assert parsed.elements[1].line_start == 4


def test_docx_preserves_order_and_explicit_styles_for_both_strategies():
    doc = Document()
    doc.add_heading("章节", level=1)
    doc.add_paragraph("表格之前")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "甲"
    table.cell(0, 1).text = "甲"  # 相等的独立单元格必须都保留。
    doc.add_paragraph("表格之后")
    style = doc.styles.add_style("Explicit outline", WD_STYLE_TYPE.PARAGRAPH)
    outline = OxmlElement("w:outlineLvl")
    outline.set(qn("w:val"), "2")
    style.element.get_or_add_pPr().append(outline)
    doc.add_paragraph("子章节", style=style)
    doc.add_paragraph("列表项", style="List Bullet")
    stream = BytesIO()
    doc.save(stream)
    parsed = parse_document("doc.docx", stream.getvalue())
    assert [element.text for element in parsed.elements] == [
        "章节",
        "表格之前",
        "甲 | 甲",
        "表格之后",
        "子章节",
        "列表项",
    ]
    assert parsed.elements[4].heading_level == 3
    assert parsed.elements[5].kind == "list"
    assert parsed.elements[2].table_header_rows == 0
    assert all(element.page_number is None for element in parsed.elements)
    assert (
        extract_text("doc.docx", stream.getvalue())
        == "章节\n\n表格之前\n\n甲 | 甲\n\n表格之后\n\n子章节\n\n列表项"
    )


def test_pdf_records_real_pages_without_invented_line_numbers():
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for text in ("First page.", "Second page."):
        page = writer.add_blank_page(width=200, height=200)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 10 150 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    parsed = parse_document("doc.pdf", output.getvalue())
    drafts = chunk_structure(parsed, chunk_size=900, chunk_overlap=150)
    assert [draft.page_start for draft in drafts] == [1, 2]
    assert all(
        draft.page_start == draft.page_end
        and draft.heading_path == []
        and draft.line_start is None
        and draft.structure_quality == "page_text"
        for draft in drafts
    )
    blank = PdfWriter()
    blank.add_blank_page(width=100, height=100)
    output = BytesIO()
    blank.write(output)
    with pytest.raises(ValueError, match="body text"):
        chunk_structure(
            parse_document("blank.pdf", output.getvalue()), chunk_size=100, chunk_overlap=10
        )


@pytest.mark.parametrize("size,overlap", [(100, 99), (100, 0), (200, 150), (900, 899)])
def test_long_titles_and_oversized_prose_preserve_every_character(size, overlap):
    body = "".join(chr(0x4E00 + index) for index in range(1500))
    drafts = chunks("# " + "长标题" * 600 + "\n" + body, size, overlap)
    assert all(0 < len(draft.content) <= size for draft in drafts)
    assert all(draft.heading_path == ["长标题" * 600] for draft in drafts)
    assert "".join(draft.content.split("\n\n", 1)[1] for draft in drafts) == body
    assert all(len(draft.content.split("\n\n", 1)[0]) + 2 <= size // 4 for draft in drafts)


@pytest.mark.parametrize("kind", ["list", "table", "code", "paragraph"])
def test_oversized_units_cover_all_effective_characters(kind):
    body = "".join(chr(0x5000 + index) for index in range(300))
    text = {
        "list": "- " + body,
        "table": "| h | value |\n| --- | --- |\n| " + body + " | x |",
        "code": "```python\n    " + body + "\n```",
        "paragraph": body,
    }[kind]
    draft_list = chunk_structure(
        ParsedDocument(
            [DocumentElement(kind, text, 0, table_header_rows=2 if kind == "table" else 0)],
            "paragraphs",
        ),
        chunk_size=100,
        chunk_overlap=0,
    )
    joined = "".join(draft.content for draft in draft_list)
    assert all(character in joined for character in body)
    assert all(
        len(draft.content) <= 100 and draft.split_reason == "oversized_element"
        for draft in draft_list
    )


def test_table_headers_and_code_fences_repeat_within_budget():
    rows = [f"| item{index:03} | value |" for index in range(20)]
    drafts = chunks("| Key | Value |\n| --- | --- |\n" + "\n".join(rows), 100, 99)
    assert all(
        draft.content.startswith("| Key | Value |\n| --- | --- |\n") and len(draft.content) <= 100
        for draft in drafts
    )
    assert all(any(row in draft.content for draft in drafts) for row in rows)
    code = "```python\n" + "\n".join(f"    print({index:03})" for index in range(30)) + "\n```"
    drafts = chunks(code, 100, 99)
    assert all(
        draft.content.startswith("```python\n")
        and draft.content.endswith("\n```")
        and len(draft.content) <= 100
        for draft in drafts
    )
    assert all(
        any(f"    print({index:03})" in draft.content for draft in drafts) for index in range(30)
    )


def test_overlap_stays_within_sections_and_pages():
    sentence = "每一个完整句子都有正文内容。"
    drafts = chunks("# A\n" + sentence * 20 + "\n# B\n独立正文。", 100, 30)
    assert any(draft.content.split("\n\n", 1)[1].startswith(sentence) for draft in drafts[1:-1])
    assert drafts[-1].content == "B\n\n独立正文。"
    assert all(draft.section_id != drafts[-1].section_id for draft in drafts[:-1])


def test_recursive_fixed_boundaries_and_metadata_free_drafts():
    text = "# 标题\n\n" + "甲乙丙丁。" * 30 + "\n\n" + "English words. " * 15
    drafts = chunk_recursive(text, chunk_size=100, chunk_overlap=20)
    assert [draft.content for draft in drafts] == [
        "# 标题",
        "甲乙丙丁。" * 19 + "甲乙丙丁",
        "。" + "甲乙丙丁。" * 14,
        "English words. " * 5 + "English words",
        ". " + "English words. " * 5 + "English words",
        ". " + "English words. " * 4 + "English words.",
    ]
    assert all(
        draft.heading_path == [] and draft.structure_quality is None and draft.section_id is None
        for draft in drafts
    )


def test_single_column_table_and_html_comment_are_preserved():
    parsed = parse_document(
        "doc.md", b"<!--comment\n\n# hidden\n-->\n\n| Key |\n| --- |\n| Value |"
    )
    assert [element.kind for element in parsed.elements] == ["paragraph", "table"]
    assert parsed.elements[0].text == "<!--comment\n\n# hidden\n-->"


def test_content_coverage_for_deterministic_random_prose():
    import random

    randomizer = random.Random(46)
    for _ in range(100):
        size = randomizer.randint(100, 400)
        text = "".join(
            randomizer.choice("中文English 。！？.!?\n")
            for _ in range(randomizer.randint(200, 1000))
        )
        parsed = ParsedDocument([DocumentElement("paragraph", text, 0)], "paragraphs")
        drafts = chunk_structure(parsed, chunk_size=size, chunk_overlap=0)
        assert "".join(draft.content for draft in drafts) == text
        assert all(len(draft.content) <= size for draft in drafts)


def test_mixed_table_rows_repeat_headers_except_character_fallback():
    text = (
        "| Key | Value |\n| --- | --- |\n| normal1 | A |\n| "
        + "X" * 300
        + " | B |\n| normal2 | C |"
    )
    drafts = chunks(text, 100, 0)
    assert all(len(draft.content) <= 100 for draft in drafts)
    for name in ("normal1", "normal2"):
        containing = [draft for draft in drafts if name in draft.content]
        assert containing and all(
            draft.content.startswith("| Key | Value |\n| --- | --- |\n") for draft in containing
        )
    assert sum(draft.content.count("X") for draft in drafts) == 300


def test_character_cut_sentence_suffix_is_not_reused_as_complete_overlap():
    text = "X" * 150 + "。" + "Y" * 30 + "。" + "Z" * 30 + "。"
    drafts = chunks(text, 100, 40)
    # X 句无法完整放入分块，其末尾后缀绝不能再次出现。
    assert sum(draft.content.count("X") for draft in drafts) == 150
    assert all(len(draft.content) <= 100 for draft in drafts)
