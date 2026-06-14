import pytest

from ranobelib_epub.chapter_client import fetch_chapter_content
from ranobelib_epub.inventory import ChapterBranchVariant, ChapterRequest


class FakeTransport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[ChapterRequest] = []

    def get_json(self, request: ChapterRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.payload


def test_fetch_chapter_content_builds_request_and_normalizes_payload() -> None:
    transport = FakeTransport(
        {
            "data": {
                "id": 42,
                "volume": "3",
                "number": "7",
                "title": "A Name",
                "branch_id": 10,
                "content": {
                    "type": "doc",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hi"}]}],
                },
            }
        }
    )
    variant = ChapterBranchVariant(501, 10, "3", "7", None, "A Name")

    result = fetch_chapter_content(
        "demo-title", variant, transport, base_url="https://api.example.test"
    )

    assert result.request.method == "GET"
    assert result.request.url == (
        "https://api.example.test/api/manga/demo-title/chapter?branch_id=10&number=7&volume=3"
    )
    assert transport.requests == [result.request]
    assert result.chapter.id == 42
    assert result.chapter.toc_title == "A Name"
    assert result.chapter.blocks[0].runs[0].text == "Hi"
    assert result.warnings == ()


def test_fetch_chapter_content_preserves_normalizer_warnings() -> None:
    transport = FakeTransport({"data": {"content": {"type": "paragraph"}}})
    variant = ChapterBranchVariant(501, 10, "3", "7", None, "A Name")

    result = fetch_chapter_content("demo-title", variant, transport)

    assert result.chapter.warnings == ('data.content type is not "doc"; chapter content skipped',)
    assert result.warnings == result.chapter.warnings


def test_fetch_chapter_content_rejects_non_buildable_variant_without_transport_call() -> None:
    transport = FakeTransport({"data": {"content": {"type": "doc", "content": []}}})
    variant = ChapterBranchVariant(501, None, "3", "7", None, "A Name")

    with pytest.raises(ValueError, match="requires a buildable branch variant"):
        fetch_chapter_content("demo-title", variant, transport)

    assert transport.requests == []
