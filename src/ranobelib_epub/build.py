from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, cast

from ranobelib_epub.chapter_client import fetch_chapter_content
from ranobelib_epub.content import NormalizedChapter
from ranobelib_epub.epub import BookMetadata, build_epub_bytes
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
) -> ChapterBuildResult:
    """Fetch selected buildable chapter variants in order and build EPUB bytes.

    The orchestration is intentionally read-only and DB-less. It validates the complete
    selection before the injected transport is used, fetches each selected variant through
    the existing chapter-content client, preserves input order, and returns the normalized
    chapters, public request plans, normalizer warnings, and final EPUB bytes.
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
    return ChapterBuildResult(
        epub_bytes=build_epub_bytes(metadata, normalized_chapters),
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
                branch_id=cast(int | str, variant.branch_id),
                volume=cast(str, variant.volume),
                number=cast(str, variant.number),
                number_secondary=variant.number_secondary,
                chapter_title=variant.chapter_title,
                branch_team=variant.branch_team,
                branch_user=variant.branch_user,
                published_at=variant.published_at,
                created_at=variant.created_at,
            )
        )
    return tuple(buildable)
