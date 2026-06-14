from __future__ import annotations

from dataclasses import dataclass
from html import escape
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Iterable
import warnings
from uuid import NAMESPACE_URL, uuid5

from ebooklib import epub

from ranobelib_epub.content import (
    Blockquote,
    ChapterBlock,
    ChapterList,
    Heading,
    HorizontalRule,
    Image,
    NormalizedChapter,
    Paragraph,
    TextRun,
)


@dataclass(frozen=True, slots=True)
class BookMetadata:
    """Metadata needed to build an offline EPUB."""

    title: str
    author: str | None = None
    translator: str | None = None
    team: str | None = None
    language: str = "ru"
    identifier: str | None = None


OutputTarget = str | Path | BinaryIO


def build_epub(
    metadata: BookMetadata,
    chapters: Iterable[NormalizedChapter],
    output: OutputTarget | None = None,
) -> bytes | None:
    """Build an EPUB from normalized chapters without network or filesystem side effects.

    If ``output`` is omitted, EPUB bytes are returned. If ``output`` is a path or a binary
    file-like object, bytes are written only to that explicit target and ``None`` is returned.
    Image blocks are intentionally not downloaded or embedded; every skipped image emits a
    ``UserWarning``.
    """

    chapter_list = tuple(chapters)
    book = _build_book(metadata, chapter_list)
    options = {"raise_exceptions": True}

    if output is None:
        buffer = BytesIO()
        epub.write_epub(buffer, book, options=options)
        return buffer.getvalue()

    epub.write_epub(output, book, options=options)
    return None


def build_epub_bytes(metadata: BookMetadata, chapters: Iterable[NormalizedChapter]) -> bytes:
    """Return EPUB bytes for callers that do not want to write to disk."""

    built = build_epub(metadata, chapters)
    assert built is not None
    return built


def write_epub(
    metadata: BookMetadata,
    chapters: Iterable[NormalizedChapter],
    output: OutputTarget,
) -> None:
    """Write an EPUB to an explicit path or binary file-like object."""

    build_epub(metadata, chapters, output=output)


def _build_book(metadata: BookMetadata, chapters: tuple[NormalizedChapter, ...]) -> epub.EpubBook:
    title = metadata.title.strip()
    if not title:
        raise ValueError("EPUB title must not be empty")

    language = metadata.language.strip() or "ru"
    book = epub.EpubBook()
    book.set_title(title)
    book.set_language(language)
    book.set_identifier(metadata.identifier or _deterministic_identifier(metadata, chapters))

    if metadata.author:
        book.add_author(metadata.author)
    if metadata.translator:
        book.add_metadata("DC", "contributor", metadata.translator, {"role": "trl"})
    if metadata.team:
        book.add_metadata("DC", "contributor", metadata.team, {"role": "bkp"})

    epub_chapters: list[epub.EpubHtml] = []
    for index, chapter in enumerate(chapters, start=1):
        item = epub.EpubHtml(
            title=chapter.toc_title or chapter.generated_title,
            file_name=_chapter_file_name(index),
            lang=language,
        )
        item.content = _render_chapter(chapter)
        book.add_item(item)
        epub_chapters.append(item)

    book.toc = tuple(
        epub.Link(item.file_name, item.title, f"chapter-{index:04d}")
        for index, item in enumerate(epub_chapters, start=1)
    )
    book.spine = ["nav", *epub_chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    return book


def _deterministic_identifier(
    metadata: BookMetadata, chapters: tuple[NormalizedChapter, ...]
) -> str:
    chapter_keys = [
        str(chapter.id if chapter.id is not None else chapter.generated_title)
        for chapter in chapters
    ]
    seed = "|".join([metadata.title.strip(), metadata.language.strip() or "ru", *chapter_keys])
    return f"urn:uuid:{uuid5(NAMESPACE_URL, seed)}"


def _chapter_file_name(index: int) -> str:
    return f"chapters/chapter-{index:04d}.xhtml"


def _render_chapter(chapter: NormalizedChapter) -> str:
    body = [f"<h1>{escape(chapter.toc_title or chapter.generated_title)}</h1>"]
    body.extend(_render_block(block) for block in chapter.blocks)
    return "\n".join(body)


def _render_blocks(blocks: tuple[ChapterBlock, ...]) -> str:
    return "\n".join(_render_block(block) for block in blocks)


def _render_block(block: ChapterBlock) -> str:
    if isinstance(block, Paragraph):
        if not block.runs:
            return "<p><br /></p>"
        return f"<p>{_render_runs(block.runs)}</p>"
    if isinstance(block, Heading):
        level = min(max(block.level, 1), 6)
        return f"<h{level}>{_render_runs(block.runs)}</h{level}>"
    if isinstance(block, ChapterList):
        tag = "ol" if block.kind == "ordered" else "ul"
        items = "".join(f"<li>{_render_blocks(item.blocks)}</li>" for item in block.items)
        return f"<{tag}>{items}</{tag}>"
    if isinstance(block, Blockquote):
        return f"<blockquote>{_render_blocks(block.blocks)}</blockquote>"
    if isinstance(block, HorizontalRule):
        return "<hr />"
    if isinstance(block, Image):
        image_name = block.name or block.src or block.alt or "unknown image"
        warnings.warn(
            f"Image block {image_name!r} skipped during EPUB build",
            UserWarning,
            stacklevel=2,
        )
        return ""
    raise TypeError(f"Unsupported chapter block: {block!r}")


def _render_runs(runs: tuple[TextRun, ...]) -> str:
    return "".join(_render_run(run) for run in runs)


def _render_run(run: TextRun) -> str:
    text = escape(run.text)
    for mark in run.marks:
        if mark.type == "bold":
            text = f"<strong>{text}</strong>"
        elif mark.type == "italic":
            text = f"<em>{text}</em>"
        elif mark.type == "underline":
            text = f"<u>{text}</u>"
        elif mark.type == "strike":
            text = f"<s>{text}</s>"
    return text
