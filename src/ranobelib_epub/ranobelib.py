from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse


_ALLOWED_HOSTS = {"ranobelib.me", "www.ranobelib.me"}
_ALLOWED_SCHEMES = {"http", "https"}


@dataclass(frozen=True, slots=True)
class RanobeLibTitleUrl:
    """Parsed public RanobeLib title URL."""

    title_id: int
    slug: str
    locale: str | None

    @property
    def canonical_url(self) -> str:
        locale_prefix = f"/{self.locale}" if self.locale else ""
        return f"https://ranobelib.me{locale_prefix}/book/{self.title_id}--{self.slug}"


@dataclass(frozen=True, slots=True)
class Attachment:
    """Offline attachment metadata referenced by a chapter image node."""

    name: str
    url: str | None = None
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class TextMark:
    """Inline text mark from RanobeLib document content."""

    type: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TextRun:
    """Plain text with optional formatting marks."""

    text: str
    marks: tuple[TextMark, ...] = ()


@dataclass(frozen=True, slots=True)
class Paragraph:
    """Paragraph block. Empty paragraphs are preserved with no runs."""

    runs: tuple[TextRun, ...] = ()


@dataclass(frozen=True, slots=True)
class Heading:
    """Heading block."""

    level: int
    runs: tuple[TextRun, ...] = ()


@dataclass(frozen=True, slots=True)
class ListItem:
    """Single ordered or bullet list item."""

    blocks: tuple["ChapterBlock", ...]


@dataclass(frozen=True, slots=True)
class ChapterList:
    """Ordered or bullet list block."""

    kind: Literal["ordered", "bullet"]
    items: tuple[ListItem, ...]


@dataclass(frozen=True, slots=True)
class Blockquote:
    """Blockquote containing nested paragraph/list/other blocks."""

    blocks: tuple["ChapterBlock", ...]


@dataclass(frozen=True, slots=True)
class HorizontalRule:
    """Horizontal rule block."""


@dataclass(frozen=True, slots=True)
class Image:
    """Image block linked to attachment metadata when available."""

    name: str | None = None
    attachment: Attachment | None = None
    alt: str | None = None
    title: str | None = None
    src: str | None = None


ChapterBlock = Paragraph | Heading | ChapterList | Blockquote | HorizontalRule | Image


@dataclass(frozen=True, slots=True)
class NormalizedChapter:
    """Offline normalized representation of a RanobeLib read-response chapter payload."""

    blocks: tuple[ChapterBlock, ...]
    attachments: dict[str, Attachment]


def parse_title_url(raw_url: str) -> RanobeLibTitleUrl:
    """Parse a public RanobeLib title URL without performing network requests.

    Supported examples:
    - https://ranobelib.me/ru/book/12345--title-slug
    - https://ranobelib.me/book/12345--title-slug

    Query strings and fragments are ignored. Chapter and branch URLs are intentionally
    rejected because the MVP accepts only title pages.
    """

    url = raw_url.strip()
    if not url:
        raise ValueError("RanobeLib URL is empty")

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError("RanobeLib URL must use http or https")

    host = parsed.hostname.lower() if parsed.hostname else ""
    if host not in _ALLOWED_HOSTS:
        raise ValueError("RanobeLib URL host must be ranobelib.me")

    parts = [part for part in parsed.path.split("/") if part]
    locale: str | None = None
    if len(parts) == 3:
        locale, book_segment, title_segment = parts
        if len(locale) != 2 or not locale.isalpha():
            raise ValueError("RanobeLib locale segment must be a two-letter code")
    elif len(parts) == 2:
        book_segment, title_segment = parts
    else:
        raise ValueError("RanobeLib URL must point to a title page")

    if book_segment != "book":
        raise ValueError("RanobeLib URL must contain /book/")

    title_id_text, separator, slug = title_segment.partition("--")
    if separator != "--" or not title_id_text.isdecimal() or not slug:
        raise ValueError("RanobeLib title segment must look like 12345--title-slug")

    return RanobeLibTitleUrl(title_id=int(title_id_text), slug=slug, locale=locale)


def normalize_chapter_payload(payload: dict[str, Any]) -> NormalizedChapter:
    """Normalize an offline RanobeLib read-response payload.

    The normalizer accepts already-captured JSON-like dictionaries only. It does not perform
    HTTP requests, download images, authenticate, or create EPUB/runtime artifacts.
    """

    data = _expect_mapping(payload.get("data"), "data")
    content = _expect_mapping(data.get("content"), "data.content")
    if content.get("type") != "doc":
        raise ValueError('RanobeLib chapter content must have type "doc"')

    attachments = _normalize_attachments(data.get("attachments", []))
    blocks = tuple(_normalize_block(node, attachments) for node in _iter_nodes(content))
    return NormalizedChapter(blocks=blocks, attachments=attachments)


def _normalize_attachments(raw_attachments: Any) -> dict[str, Attachment]:
    if raw_attachments is None:
        return {}
    if not isinstance(raw_attachments, list):
        raise ValueError("data.attachments must be a list")

    attachments: dict[str, Attachment] = {}
    for index, raw_attachment in enumerate(raw_attachments):
        attachment = _expect_mapping(raw_attachment, f"data.attachments[{index}]")
        name = attachment.get("name")
        if not isinstance(name, str) or not name:
            continue
        attachments[name] = Attachment(
            name=name,
            url=_optional_str(
                attachment.get("url") or attachment.get("path") or attachment.get("src")
            ),
            width=_optional_int(attachment.get("width")),
            height=_optional_int(attachment.get("height")),
            mime_type=_optional_str(
                attachment.get("mime_type") or attachment.get("mimeType") or attachment.get("type")
            ),
        )
    return attachments


def _normalize_block(node: dict[str, Any], attachments: dict[str, Attachment]) -> ChapterBlock:
    node_type = node.get("type")
    if node_type == "paragraph":
        return Paragraph(runs=_normalize_inline_content(node))
    if node_type == "heading":
        attrs = _optional_mapping(node.get("attrs"))
        return Heading(
            level=_normalize_heading_level(attrs.get("level")),
            runs=_normalize_inline_content(node),
        )
    if node_type == "orderedList":
        return ChapterList(kind="ordered", items=_normalize_list_items(node, attachments))
    if node_type == "bulletList":
        return ChapterList(kind="bullet", items=_normalize_list_items(node, attachments))
    if node_type == "listItem":
        return ChapterList(
            kind="bullet",
            items=(ListItem(blocks=_normalize_child_blocks(node, attachments)),),
        )
    if node_type == "blockquote":
        return Blockquote(blocks=_normalize_child_blocks(node, attachments))
    if node_type == "horizontalRule":
        return HorizontalRule()
    if node_type == "image":
        return _normalize_image(node, attachments)

    raise ValueError(f"Unsupported RanobeLib content node type: {node_type!r}")


def _normalize_inline_content(node: dict[str, Any]) -> tuple[TextRun, ...]:
    runs: list[TextRun] = []
    for child in _iter_nodes(node):
        child_type = child.get("type")
        if child_type != "text":
            raise ValueError(f"Unsupported inline content node type: {child_type!r}")
        text = child.get("text", "")
        if not isinstance(text, str):
            raise ValueError("text node text must be a string")
        runs.append(TextRun(text=text, marks=_normalize_marks(child.get("marks", []))))
    return tuple(runs)


def _normalize_marks(raw_marks: Any) -> tuple[TextMark, ...]:
    if raw_marks is None:
        return ()
    if not isinstance(raw_marks, list):
        raise ValueError("text node marks must be a list")
    marks: list[TextMark] = []
    for index, raw_mark in enumerate(raw_marks):
        mark = _expect_mapping(raw_mark, f"marks[{index}]")
        mark_type = mark.get("type")
        if not isinstance(mark_type, str) or not mark_type:
            raise ValueError("text mark type must be a non-empty string")
        marks.append(TextMark(type=mark_type, attrs=dict(_optional_mapping(mark.get("attrs")))))
    return tuple(marks)


def _normalize_list_items(
    node: dict[str, Any], attachments: dict[str, Attachment]
) -> tuple[ListItem, ...]:
    items: list[ListItem] = []
    for child in _iter_nodes(node):
        if child.get("type") != "listItem":
            raise ValueError("list content must contain only listItem nodes")
        items.append(ListItem(blocks=_normalize_child_blocks(child, attachments)))
    return tuple(items)


def _normalize_child_blocks(
    node: dict[str, Any], attachments: dict[str, Attachment]
) -> tuple[ChapterBlock, ...]:
    return tuple(_normalize_block(child, attachments) for child in _iter_nodes(node))


def _normalize_image(node: dict[str, Any], attachments: dict[str, Attachment]) -> Image:
    attrs = _optional_mapping(node.get("attrs"))
    images = attrs.get("images")
    image_meta: dict[str, Any] = {}
    if isinstance(images, list) and images:
        image_meta = _optional_mapping(images[0])
    elif isinstance(images, dict):
        image_meta = _optional_mapping(images)

    image_name = _optional_str(image_meta.get("image") or attrs.get("image") or attrs.get("name"))
    return Image(
        name=image_name,
        attachment=attachments.get(image_name) if image_name else None,
        alt=_optional_str(attrs.get("alt")),
        title=_optional_str(attrs.get("title")),
        src=_optional_str(image_meta.get("url") or attrs.get("src")),
    )


def _iter_nodes(node: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    content = node.get("content", [])
    if content is None:
        return ()
    if not isinstance(content, list):
        raise ValueError("content must be a list")
    return tuple(_expect_mapping(child, "content[]") for child in content)


def _normalize_heading_level(raw_level: Any) -> int:
    level = raw_level if isinstance(raw_level, int) else 1
    return min(max(level, 1), 6)


def _expect_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _optional_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None
