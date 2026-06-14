from __future__ import annotations

from dataclasses import dataclass

from ranobelib_epub.content import NormalizedChapter, normalize_chapter_payload
from ranobelib_epub.inventory import (
    RANOBELIB_API_BASE_URL,
    ChapterBranchVariant,
    ChapterRequest,
    InventoryTransport,
    build_chapter_content_request,
)


@dataclass(frozen=True, slots=True)
class ChapterContentResult:
    """Read-only chapter content response with its public request plan."""

    request: ChapterRequest
    chapter: NormalizedChapter
    warnings: tuple[str, ...] = ()


def fetch_chapter_content(
    slug: str,
    variant: ChapterBranchVariant,
    transport: InventoryTransport,
    *,
    base_url: str = RANOBELIB_API_BASE_URL,
) -> ChapterContentResult:
    """Fetch and normalize one buildable RanobeLib chapter variant.

    The function is intentionally DB-less and read-only: it builds the existing public
    chapter-content request plan, delegates JSON retrieval to an injected transport, and
    normalizes the payload offline. Non-buildable variants are rejected while building the
    request plan, before the transport can be called.
    """

    request = build_chapter_content_request(slug, variant, base_url=base_url)
    chapter = normalize_chapter_payload(transport.get_json(request))
    return ChapterContentResult(request=request, chapter=chapter, warnings=chapter.warnings)
