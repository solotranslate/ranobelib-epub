from fastapi.testclient import TestClient

from ranobelib_epub.app import app, get_inventory_service
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
    assert "non-buildable" in response.text
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
