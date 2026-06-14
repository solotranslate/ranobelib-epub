from __future__ import annotations

import pytest

from ranobelib_epub.build import build_selected_chapter_epub
from ranobelib_epub.epub import BookMetadata
from ranobelib_epub.inventory import ChapterBranchVariant, ChapterRequest


class FakeTransport:
    def __init__(self, payloads: list[dict[str, object]] | None = None) -> None:
        self.payloads = list(payloads or [])
        self.requests: list[ChapterRequest] = []

    def get_json(self, request: ChapterRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.payloads.pop(0)


def test_build_selected_chapter_epub_fetches_two_buildable_variants() -> None:
    transport = FakeTransport([_payload(1, "1", "First"), _payload(2, "2", "Second")])
    variants = [_variant(10, "1"), _variant(20, "2")]

    result = build_selected_chapter_epub(
        "demo-title", BookMetadata(title="Demo"), variants, transport, base_url="https://api.test"
    )

    assert result.epub_bytes
    assert len(result.chapters) == 2
    assert len(result.request_plans) == 2
    assert transport.requests == list(result.request_plans)


def test_build_selected_chapter_epub_preserves_selection_order() -> None:
    transport = FakeTransport([_payload(2, "2", "Second"), _payload(1, "1", "First")])
    variants = [_variant(20, "2"), _variant(10, "1")]

    result = build_selected_chapter_epub(
        "demo-title", BookMetadata(title="Demo"), variants, transport
    )

    assert [chapter.id for chapter in result.chapters] == [2, 1]
    assert [request.url for request in result.request_plans] == [
        "https://api.cdnlibs.org/api/manga/demo-title/chapter?branch_id=20&number=2&volume=1",
        "https://api.cdnlibs.org/api/manga/demo-title/chapter?branch_id=10&number=1&volume=1",
    ]


def test_build_selected_chapter_epub_rejects_non_buildable_before_transport_call() -> None:
    transport = FakeTransport([_payload(1, "1", "First")])
    variants = [_variant(10, "1"), ChapterBranchVariant(2, None, "1", "2", None, "Broken")]

    with pytest.raises(ValueError, match="position 2 is not buildable"):
        build_selected_chapter_epub("demo-title", BookMetadata(title="Demo"), variants, transport)

    assert transport.requests == []


def test_build_selected_chapter_epub_rejects_empty_selection_before_transport_call() -> None:
    transport = FakeTransport()

    with pytest.raises(ValueError, match="selection must not be empty"):
        build_selected_chapter_epub("demo-title", BookMetadata(title="Demo"), [], transport)

    assert transport.requests == []


def test_build_selected_chapter_epub_preserves_normalizer_warnings() -> None:
    transport = FakeTransport([{"data": {"id": 1, "content": {"type": "paragraph"}}}])

    result = build_selected_chapter_epub(
        "demo-title", BookMetadata(title="Demo"), [_variant(10, "1")], transport
    )

    assert result.warnings == ('data.content type is not "doc"; chapter content skipped',)
    assert result.chapters[0].warnings == result.warnings


def _variant(branch_id: int, number: str) -> ChapterBranchVariant:
    return ChapterBranchVariant(
        external_chapter_id=branch_id,
        branch_id=branch_id,
        volume="1",
        number=number,
        number_secondary=None,
        chapter_title=f"Chapter {number}",
    )


def _payload(chapter_id: int, number: str, text: str) -> dict[str, object]:
    return {
        "data": {
            "id": chapter_id,
            "volume": "1",
            "number": number,
            "title": f"Chapter {number}",
            "content": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": text}]}
                ],
            },
        }
    }
