import pytest

from antler_rag.documents import UnsupportedDocument, extract_text


def test_extracts_utf8_text() -> None:
    assert extract_text("notes.md", b"# Hello\n\nWorld") == "# Hello\n\nWorld"


def test_rejects_unsupported_format() -> None:
    with pytest.raises(UnsupportedDocument, match="Unsupported file type"):
        extract_text("sheet.xlsx", b"not really an xlsx")
