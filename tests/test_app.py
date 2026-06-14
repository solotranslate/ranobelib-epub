import json

from fastapi.testclient import TestClient

from ranobelib_epub.app import app, get_build_service, get_inventory_service
from ranobelib_epub.inventory import (
    ChapterBranchVariant,
    ChapterInventory,
    InventoryWarning,
    LogicalChapter,
)
from ranobelib_epub.ranobelib import RanobeLibTitleUrl


class FakeInventoryService:
    def __init__(self) -> None:
        self.seen: list[RanobeLibTitleUrl] = []

    def fetch(self, title: RanobeLibTitleUrl) -> ChapterInventory:
        self.seen.append(title)
        buildable = ChapterBranchVariant(
            external_chapter_id=101,
            branch_id=55,
            volume="1",
            number="2",
            number_secondary=None,
            chapter_title="Two roads",
            branch_team="Team A",
        )
        blocked = ChapterBranchVariant(
            external_chapter_id=102,
            branch_id=None,
            volume="1",
            number="3",
            number_secondary=None,
            chapter_title="Missing branch",
        )
        return ChapterInventory(
            slug=title.slug,
            logical_chapters=(
                LogicalChapter(
                    logical_id=1,
                    volume="1",
                    number="2",
                    number_secondary=None,
                    name="Two roads",
                    variants=(buildable,),
                ),
                LogicalChapter(
                    logical_id=2,
                    volume="1",
                    number="3",
                    number_secondary=None,
                    name="Missing branch",
                    variants=(blocked,),
                ),
            ),
            variants=(buildable, blocked),
            warnings=(InventoryWarning("Chapter branch variant is not buildable", 2, 102),),
        )


class FakeBuildService:
    def __init__(self) -> None:
        self.calls: list[tuple[RanobeLibTitleUrl, tuple[ChapterBranchVariant, ...]]] = []

    def build(self, title: RanobeLibTitleUrl, variants: tuple[ChapterBranchVariant, ...]) -> bytes:
        self.calls.append((title, variants))
        return b"fake epub bytes"


def _variant_payload(
    *,
    external_chapter_id: int | None = 101,
    branch_id: int | None = 55,
    volume: str | None = "1",
    number: str | None = "2",
    chapter_title: str | None = "Two roads",
) -> str:
    return json.dumps(
        {
            "external_chapter_id": external_chapter_id,
            "branch_id": branch_id,
            "volume": volume,
            "number": number,
            "number_secondary": None,
            "chapter_title": chapter_title,
            "branch_team": "Team A",
            "branch_user": None,
            "published_at": None,
            "created_at": None,
        }
    )


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "RanobeLib EPUB Builder" in response.text
    assert 'name="title_url"' in response.text
    assert 'action="/inventory"' in response.text


def test_inventory_preview_uses_fake_service_without_network() -> None:
    service = FakeInventoryService()
    app.dependency_overrides[get_inventory_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.get(
            "/inventory", params={"title_url": "https://ranobelib.me/ru/book/12345--demo-title"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert service.seen == [RanobeLibTitleUrl(title_id=12345, slug="demo-title", locale="ru")]
    assert "https://ranobelib.me/ru/book/12345--demo-title" in response.text
    assert "demo-title" in response.text
    assert "Logical chapters</dt><dd>2" in response.text
    assert "Variants</dt><dd>2" in response.text
    assert "Buildable variants</dt><dd>1" in response.text
    assert "Volume 1 Chapter 2: Two roads — Team A" in response.text
    assert "buildable" in response.text
    assert 'action="/build"' in response.text
    assert 'method="post"' in response.text
    assert 'name="title_url"' in response.text
    assert 'name="selected_variant"' in response.text
    assert response.text.count('name="selected_variant"') == 1
    assert "non-buildable" in response.text
    assert "not selectable" in response.text
    assert "Chapter branch variant is not buildable" in response.text


def test_inventory_preview_rejects_invalid_url_without_fetching() -> None:
    service = FakeInventoryService()
    app.dependency_overrides[get_inventory_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.get("/inventory", params={"title_url": "https://example.test/book/1--bad"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "RanobeLib URL host must be ranobelib.me" in response.text
    assert "Traceback" not in response.text
    assert service.seen == []


def test_build_route_returns_epub_download_from_fake_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payload(),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    assert response.headers["content-disposition"] == 'attachment; filename="demo-title.epub"'
    assert response.content == b"fake epub bytes"
    assert len(service.calls) == 1
    title, variants = service.calls[0]
    assert title == RanobeLibTitleUrl(title_id=12345, slug="demo-title", locale="ru")
    assert variants[0].branch_id == 55


def test_build_route_preserves_selected_order() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": [
                    _variant_payload(external_chapter_id=101, number="1"),
                    _variant_payload(external_chapter_id=102, number="2"),
                ],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    _, variants = service.calls[0]
    assert [variant.external_chapter_id for variant in variants] == [101, 102]
    assert [variant.number for variant in variants] == ["1", "2"]


def test_build_route_rejects_empty_selection_before_build_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build", data={"title_url": "https://ranobelib.me/ru/book/12345--demo-title"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Select at least one buildable chapter variant" in response.text
    assert "Traceback" not in response.text
    assert service.calls == []


def test_build_route_rejects_malformed_selection_before_build_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": "not json",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Selected variant at position 1 is malformed" in response.text
    assert "Traceback" not in response.text
    assert service.calls == []


def test_build_route_rejects_non_buildable_selection_before_build_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payload(branch_id=None),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Selected variant at position 1 is not buildable" in response.text
    assert "Traceback" not in response.text
    assert service.calls == []


def test_build_route_rejects_invalid_title_url_without_stack_trace() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://example.test/book/1--bad",
                "selected_variant": _variant_payload(),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "RanobeLib URL host must be ranobelib.me" in response.text
    assert "Traceback" not in response.text
    assert service.calls == []
