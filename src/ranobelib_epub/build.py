from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, cast

from ranobelib_epub.chapter_client import fetch_chapter_content
from ranobelib_epub.content import (
    Blockquote,
    ChapterBlock,
    ChapterList,
    Heading,
    Image,
    NormalizedChapter,
    Paragraph,
)
from ranobelib_epub.epub import BookMetadata, build_epub_bytes
from ranobelib_epub.images import ImageAssetFetcher, ImageFetchLimits, collect_image_assets
from ranobelib_epub.inventory import (
    RANOBELIB_API_BASE_URL,
    BuildableChapterVariant,
    ChapterBranchVariant,
    ChapterRequest,
    InventoryTransport,
)


@dataclass(frozen=True, slots=True)
class ChapterBuildResult:
    """DB-less EPUB build result for explicitly selected chapter variants."""

    epub_bytes: bytes
    chapters: tuple[NormalizedChapter, ...]
    request_plans: tuple[ChapterRequest, ...]
    warnings: tuple[str, ...] = ()


ChapterVariantSelection = Sequence[ChapterBranchVariant | BuildableChapterVariant]


def build_selected_chapter_epub(
    slug: str,
    metadata: BookMetadata,
    selected_variants: ChapterVariantSelection,
    transport: InventoryTransport,
    *,
    base_url: str = RANOBELIB_API_BASE_URL,
    image_fetcher: ImageAssetFetcher | None = None,
    image_limits: ImageFetchLimits | None = None,
) -> ChapterBuildResult:
    """Fetch selected buildable chapter variants in order and build EPUB bytes.

    The orchestration is intentionally read-only and DB-less. It validates the complete
    selection before the injected transport is used, fetches each selected variant through
    the existing chapter-content client, preserves input order, and returns the normalized
    chapters, public request plans, normalizer/image warnings, and final EPUB bytes.
    Images remain disabled by default; callers may opt in with a bounded read-only fetcher.
    """

    buildable_variants = _validate_selection(selected_variants)

    chapters: list[NormalizedChapter] = []
    requests: list[ChapterRequest] = []
    warnings: list[str] = []
    for variant in buildable_variants:
        content = fetch_chapter_content(slug, variant, transport, base_url=base_url)
        chapters.append(content.chapter)
        requests.append(content.request)
        warnings.extend(content.warnings)

    normalized_chapters = tuple(chapters)
    _reject_empty_normalized_chapters(normalized_chapters)

    image_assets = None
    if image_fetcher is not None:
        image_assets, image_warnings = collect_image_assets(
            normalized_chapters, image_fetcher, image_limits
        )
        warnings.extend(image_warnings)

    return ChapterBuildResult(
        epub_bytes=build_epub_bytes(metadata, normalized_chapters, image_assets=image_assets),
        chapters=normalized_chapters,
        request_plans=tuple(requests),
        warnings=tuple(warnings),
    )


def _validate_selection(
    selected_variants: ChapterVariantSelection,
) -> tuple[BuildableChapterVariant, ...]:
    if not selected_variants:
        raise ValueError("Chapter build selection must not be empty")

    buildable: list[BuildableChapterVariant] = []
    for index, variant in enumerate(selected_variants, start=1):
        if not variant.is_buildable:
            raise ValueError(f"Selected chapter variant at position {index} is not buildable")
        buildable.append(
            BuildableChapterVariant(
                external_chapter_id=variant.external_chapter_id,
                branch_id=cast(int | str | None, variant.branch_id),
                volume=cast(str, variant.volume),
                number=cast(str, variant.number),
                number_secondary=variant.number_secondary,
                chapter_title=variant.chapter_title,
                branch_team=variant.branch_team,
                branch_user=variant.branch_user,
                published_at=variant.published_at,
                created_at=variant.created_at,
                is_default_branch=variant.is_default_branch,
            )
        )
    return tuple(buildable)


def _reject_empty_normalized_chapters(chapters: tuple[NormalizedChapter, ...]) -> None:
    for chapter in chapters:
        if not _chapter_has_meaningful_content(chapter):
            raise ValueError(
                f"Chapter {_safe_chapter_context(chapter)} normalized to empty content; "
                "check branch selection or source payload."
            )


def _chapter_has_meaningful_content(chapter: NormalizedChapter) -> bool:
    return any(_block_has_meaningful_content(block) for block in chapter.blocks)


def _block_has_meaningful_content(block: ChapterBlock) -> bool:
    if isinstance(block, Paragraph | Heading):
        return any(run.text.strip() for run in block.runs)
    if isinstance(block, ChapterList):
        return any(
            _block_has_meaningful_content(child)
            for item in block.items
            for child in item.blocks
        )
    if isinstance(block, Blockquote):
        return any(_block_has_meaningful_content(child) for child in block.blocks)
    if isinstance(block, Image):
        return any((block.name, block.src, block.attachment))
    return False


def _safe_chapter_context(chapter: NormalizedChapter) -> str:
    parts: list[str] = []
    if chapter.volume:
        parts.append(f"volume {chapter.volume}")
    if chapter.number:
        number = chapter.number
        if chapter.number_secondary:
            number = f"{number}.{chapter.number_secondary}"
        parts.append(f"number {number}")
    title = (
        chapter.source_title or chapter.source_name or chapter.toc_title or chapter.generated_title
    )
    if title:
        parts.append(f"title {title!r}")
    if chapter.branch_id is not None:
        parts.append(f"branch id {chapter.branch_id}")
    if chapter.id is not None:
        parts.append(f"chapter id {chapter.id}")
    return ", ".join(parts) or "unknown chapter"
