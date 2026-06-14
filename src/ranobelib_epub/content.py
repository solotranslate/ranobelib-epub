from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


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

    id: int | None
    volume: str | None
    number: str | None
    number_secondary: str | None
    source_title: str | None
    source_name: str | None
    slug: str | None
    branch_id: int | None
    manga_id: int | None
    generated_title: str
    toc_title: str
    blocks: tuple[ChapterBlock, ...]
    attachments: dict[str, Attachment]
    warnings: tuple[str, ...] = ()


def normalize_chapter_payload(payload: dict[str, Any]) -> NormalizedChapter:
    """Normalize an offline RanobeLib read-response payload.

    The normalizer accepts already-captured JSON-like dictionaries only. It does not perform
    HTTP requests, download images, authenticate, or create EPUB/runtime artifacts. Recoverable
    unknown or missing content is skipped and recorded in ``warnings``.
    """

    warnings: list[str] = []
    data = _mapping_or_warning(payload.get("data"), "data", warnings)
    metadata_source = _metadata_source(data)
    metadata = _normalize_metadata(metadata_source)
    generated_title = _generate_title(metadata)
    toc_title = metadata.source_title or metadata.source_name or generated_title

    content = _mapping_or_warning(data.get("content"), "data.content", warnings)
    if content.get("type") != "doc":
        if content:
            warnings.append('data.content type is not "doc"; chapter content skipped')
        else:
            warnings.append("data.content is missing; chapter content skipped")
        blocks: tuple[ChapterBlock, ...] = ()
    else:
        attachments = _normalize_attachments(data.get("attachments", []), warnings)
        blocks = _normalize_blocks(
            _iter_nodes(content, "data.content", warnings), attachments, warnings
        )
        return NormalizedChapter(
            id=metadata.id,
            volume=metadata.volume,
            number=metadata.number,
            number_secondary=metadata.number_secondary,
            source_title=metadata.source_title,
            source_name=metadata.source_name,
            slug=metadata.slug,
            branch_id=metadata.branch_id,
            manga_id=metadata.manga_id,
            generated_title=generated_title,
            toc_title=toc_title,
            blocks=blocks,
            attachments=attachments,
            warnings=tuple(warnings),
        )

    attachments = _normalize_attachments(data.get("attachments", []), warnings)
    return NormalizedChapter(
        id=metadata.id,
        volume=metadata.volume,
        number=metadata.number,
        number_secondary=metadata.number_secondary,
        source_title=metadata.source_title,
        source_name=metadata.source_name,
        slug=metadata.slug,
        branch_id=metadata.branch_id,
        manga_id=metadata.manga_id,
        generated_title=generated_title,
        toc_title=toc_title,
        blocks=blocks,
        attachments=attachments,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True, slots=True)
class _ChapterMetadata:
    id: int | None
    volume: str | None
    number: str | None
    number_secondary: str | None
    source_title: str | None
    source_name: str | None
    slug: str | None
    branch_id: int | None
    manga_id: int | None


def _metadata_source(data: dict[str, Any]) -> dict[str, Any]:
    chapter = data.get("chapter")
    if isinstance(chapter, dict):
        merged = dict(data)
        merged.update(chapter)
        return merged
    return data


def _normalize_metadata(data: dict[str, Any]) -> _ChapterMetadata:
    return _ChapterMetadata(
        id=_optional_int(data.get("id")),
        volume=_optional_chapter_number(data.get("volume")),
        number=_optional_chapter_number(data.get("number")),
        number_secondary=_optional_chapter_number(
            data.get("number_secondary") or data.get("numberSecondary")
        ),
        source_title=_optional_str(data.get("title")),
        source_name=_optional_str(data.get("name")),
        slug=_optional_str(data.get("slug")),
        branch_id=_optional_int(data.get("branch_id") or data.get("branchId")),
        manga_id=_optional_int(data.get("manga_id") or data.get("mangaId")),
    )


def _generate_title(metadata: _ChapterMetadata) -> str:
    parts: list[str] = []
    if metadata.volume:
        parts.append(f"Volume {metadata.volume}")
    if metadata.number:
        chapter_number = metadata.number
        if metadata.number_secondary:
            chapter_number = f"{chapter_number}.{metadata.number_secondary}"
        parts.append(f"Chapter {chapter_number}")
    if parts:
        return " ".join(parts)
    if metadata.slug:
        return metadata.slug.replace("-", " ").strip() or "Chapter"
    if metadata.id is not None:
        return f"Chapter {metadata.id}"
    return "Chapter"


def _normalize_attachments(raw_attachments: Any, warnings: list[str]) -> dict[str, Attachment]:
    if raw_attachments is None:
        return {}
    if not isinstance(raw_attachments, list):
        warnings.append("data.attachments is not a list; attachments skipped")
        return {}

    attachments: dict[str, Attachment] = {}
    for index, raw_attachment in enumerate(raw_attachments):
        attachment = _mapping_or_warning(raw_attachment, f"data.attachments[{index}]", warnings)
        name = attachment.get("name")
        if not isinstance(name, str) or not name:
            warnings.append(f"data.attachments[{index}] has no name; attachment skipped")
            continue
        attachments[name] = Attachment(
            name=name,
            url=_optional_str(
                attachment.get("url")
                or attachment.get("previewUrl")
                or attachment.get("originalUrl")
                or attachment.get("path")
                or attachment.get("src")
            ),
            width=_optional_int(attachment.get("width")),
            height=_optional_int(attachment.get("height")),
            mime_type=_optional_str(
                attachment.get("mime_type") or attachment.get("mimeType") or attachment.get("type")
            ),
        )
    return attachments


def _normalize_blocks(
    nodes: tuple[dict[str, Any], ...], attachments: dict[str, Attachment], warnings: list[str]
) -> tuple[ChapterBlock, ...]:
    blocks: list[ChapterBlock] = []
    for node in nodes:
        block = _normalize_block(node, attachments, warnings)
        if block is not None:
            blocks.append(block)
    return tuple(blocks)


def _normalize_block(
    node: dict[str, Any], attachments: dict[str, Attachment], warnings: list[str]
) -> ChapterBlock | None:
    node_type = node.get("type")
    if node_type == "paragraph":
        return Paragraph(runs=_normalize_inline_content(node, warnings))
    if node_type == "heading":
        attrs = _optional_mapping(node.get("attrs"))
        return Heading(
            level=_normalize_heading_level(attrs.get("level")),
            runs=_normalize_inline_content(node, warnings),
        )
    if node_type == "orderedList":
        return ChapterList(kind="ordered", items=_normalize_list_items(node, attachments, warnings))
    if node_type == "bulletList":
        return ChapterList(kind="bullet", items=_normalize_list_items(node, attachments, warnings))
    if node_type == "listItem":
        return ChapterList(
            kind="bullet",
            items=(ListItem(blocks=_normalize_child_blocks(node, attachments, warnings)),),
        )
    if node_type == "blockquote":
        return Blockquote(blocks=_normalize_child_blocks(node, attachments, warnings))
    if node_type == "horizontalRule":
        return HorizontalRule()
    if node_type == "image":
        return _normalize_image(node, attachments, warnings)

    warnings.append(f"Unsupported RanobeLib content node type {node_type!r}; node skipped")
    return None


def _normalize_inline_content(node: dict[str, Any], warnings: list[str]) -> tuple[TextRun, ...]:
    runs: list[TextRun] = []
    for child in _iter_nodes(node, "inline content", warnings):
        child_type = child.get("type")
        if child_type != "text":
            warnings.append(f"Unsupported inline content node type {child_type!r}; node skipped")
            continue
        text = child.get("text", "")
        if not isinstance(text, str):
            warnings.append("text node text is not a string; node skipped")
            continue
        runs.append(TextRun(text=text, marks=_normalize_marks(child.get("marks", []), warnings)))
    return tuple(runs)


def _normalize_marks(raw_marks: Any, warnings: list[str]) -> tuple[TextMark, ...]:
    if raw_marks is None:
        return ()
    if not isinstance(raw_marks, list):
        warnings.append("text node marks is not a list; marks skipped")
        return ()
    marks: list[TextMark] = []
    for index, raw_mark in enumerate(raw_marks):
        mark = _mapping_or_warning(raw_mark, f"marks[{index}]", warnings)
        mark_type = mark.get("type")
        if not isinstance(mark_type, str) or not mark_type:
            warnings.append(f"marks[{index}] has no type; mark skipped")
            continue
        marks.append(TextMark(type=mark_type, attrs=dict(_optional_mapping(mark.get("attrs")))))
    return tuple(marks)


def _normalize_list_items(
    node: dict[str, Any], attachments: dict[str, Attachment], warnings: list[str]
) -> tuple[ListItem, ...]:
    items: list[ListItem] = []
    for child in _iter_nodes(node, "list content", warnings):
        if child.get("type") != "listItem":
            warnings.append("list content contains non-listItem node; node skipped")
            continue
        items.append(ListItem(blocks=_normalize_child_blocks(child, attachments, warnings)))
    return tuple(items)


def _normalize_child_blocks(
    node: dict[str, Any], attachments: dict[str, Attachment], warnings: list[str]
) -> tuple[ChapterBlock, ...]:
    return _normalize_blocks(_iter_nodes(node, "child content", warnings), attachments, warnings)


def _normalize_image(
    node: dict[str, Any], attachments: dict[str, Attachment], warnings: list[str]
) -> Image:
    attrs = _optional_mapping(node.get("attrs"))
    images = attrs.get("images")
    image_meta: dict[str, Any] = {}
    if isinstance(images, list) and images:
        image_meta = _optional_mapping(images[0])
    elif isinstance(images, dict):
        image_meta = _optional_mapping(images)

    image_name = _optional_str(image_meta.get("image") or attrs.get("image") or attrs.get("name"))
    attachment = attachments.get(image_name) if image_name else None
    if image_name and attachment is None:
        warnings.append(f"Image attachment {image_name!r} is missing; image preserved")
    elif not image_name:
        warnings.append("Image node has no attachment name; image preserved")

    return Image(
        name=image_name,
        attachment=attachment,
        alt=_optional_str(attrs.get("alt")),
        title=_optional_str(attrs.get("title")),
        src=_optional_str(
            image_meta.get("url")
            or image_meta.get("previewUrl")
            or image_meta.get("originalUrl")
            or image_meta.get("src")
            or attrs.get("url")
            or attrs.get("previewUrl")
            or attrs.get("originalUrl")
            or attrs.get("src")
        ),
    )


def _iter_nodes(
    node: dict[str, Any], label: str, warnings: list[str]
) -> tuple[dict[str, Any], ...]:
    content = node.get("content", [])
    if content is None:
        return ()
    if not isinstance(content, list):
        warnings.append(f"{label} content is not a list; content skipped")
        return ()
    nodes: list[dict[str, Any]] = []
    for index, child in enumerate(content):
        child_node = _mapping_or_warning(child, f"{label}.content[{index}]", warnings)
        if child_node:
            nodes.append(child_node)
    return tuple(nodes)


def _normalize_heading_level(raw_level: Any) -> int:
    level = raw_level if isinstance(raw_level, int) else 1
    return min(max(level, 1), 6)


def _mapping_or_warning(value: Any, label: str, warnings: list[str]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    warnings.append(f"{label} is not an object; skipped")
    return {}


def _optional_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_chapter_number(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, int | float):
        return str(value)
    return None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None
