from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from ranobelib_epub.content import (
    Blockquote,
    ChapterList,
    Heading,
    HorizontalRule,
    Image,
    ListItem,
    NormalizedChapter,
    Paragraph,
    TextMark,
    TextRun,
)
from ranobelib_epub.epub import BookMetadata, build_epub, build_epub_bytes, write_epub


def test_build_epub_bytes_uses_deterministic_toc_and_filenames() -> None:
    first = _chapter(
        1,
        "Free form !? title",
        "Volume 1 Chapter 1",
        (Paragraph((_run("Hello"),)),),
    )
    second = _chapter(2, "Named TOC", "Volume 1 Chapter 2", (Paragraph((_run("World"),)),))

    payload = build_epub_bytes(BookMetadata(title="Книга", author="Автор"), [first, second])

    with ZipFile(BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert "EPUB/chapters/chapter-0001.xhtml" in names
        assert "EPUB/chapters/chapter-0002.xhtml" in names
        assert not any("Free form" in name for name in names)
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8")
        assert "Free form !? title" in nav
        assert "Named TOC" in nav


def test_build_epub_renders_supported_blocks_and_marks() -> None:
    chapter = _chapter(
        1,
        "TOC",
        "Generated",
        (
            Heading(2, (_run("Heading"),)),
            Paragraph(
                (
                    _run("bold", TextMark("bold")),
                    _run(" italic", TextMark("italic")),
                    _run(" underline", TextMark("underline")),
                    _run(" strike", TextMark("strike")),
                )
            ),
            Paragraph(()),
            ChapterList("ordered", (ListItem((Paragraph((_run("First"),)),)),)),
            ChapterList("bullet", (ListItem((Paragraph((_run("Bullet"),)),)),)),
            Blockquote((Paragraph((_run("Quote"),)),)),
            HorizontalRule(),
        ),
    )

    payload = build_epub_bytes(BookMetadata(title="Book"), [chapter])

    with ZipFile(BytesIO(payload)) as archive:
        html = archive.read("EPUB/chapters/chapter-0001.xhtml").decode("utf-8")
        assert "<h1>TOC</h1>" in html
        assert "<h2>Heading</h2>" in html
        assert "<strong>bold</strong>" in html
        assert "<em> italic</em>" in html
        assert "<u> underline</u>" in html
        assert "<s> strike</s>" in html
        assert "<p><br" in html
        assert "<ol>" in html
        assert "<ul>" in html
        assert "<blockquote>" in html
        assert "<hr" in html


def test_build_epub_skips_images_with_warning() -> None:
    chapter = _chapter(1, "TOC", "Generated", (Image(name="cover.png"),))

    with pytest.warns(UserWarning, match="Image block 'cover.png' skipped"):
        payload = build_epub_bytes(BookMetadata(title="Book"), [chapter])

    with ZipFile(BytesIO(payload)) as archive:
        html = archive.read("EPUB/chapters/chapter-0001.xhtml").decode("utf-8")
        assert "cover.png" not in html
        assert "<img" not in html


def test_write_epub_writes_only_explicit_target(tmp_path) -> None:
    target = tmp_path / "book.epub"
    chapter = _chapter(1, "TOC", "Generated", (Paragraph((_run("Text"),)),))

    assert build_epub(BookMetadata(title="Book"), [chapter], output=target) is None

    assert target.exists()
    with ZipFile(target) as archive:
        assert "EPUB/chapters/chapter-0001.xhtml" in archive.namelist()


def test_write_epub_accepts_file_like_object() -> None:
    buffer = BytesIO()
    chapter = _chapter(1, "TOC", "Generated", (Paragraph((_run("Text"),)),))

    write_epub(BookMetadata(title="Book"), [chapter], buffer)

    buffer.seek(0)
    with ZipFile(buffer) as archive:
        assert "EPUB/chapters/chapter-0001.xhtml" in archive.namelist()


def _run(text: str, *marks: TextMark) -> TextRun:
    return TextRun(text=text, marks=marks)


def _chapter(
    chapter_id: int,
    toc_title: str,
    generated_title: str,
    blocks: tuple,
) -> NormalizedChapter:
    return NormalizedChapter(
        id=chapter_id,
        volume=None,
        number=None,
        number_secondary=None,
        source_title=None,
        source_name=None,
        slug=None,
        branch_id=None,
        manga_id=None,
        generated_title=generated_title,
        toc_title=toc_title,
        blocks=blocks,
        attachments={},
    )
