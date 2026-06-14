import json

from fastapi.testclient import TestClient

from ranobelib_epub.app import (
    MAX_SYNC_BUILD_VARIANTS,
    app,
    get_build_service,
    get_inventory_service,
)
from ranobelib_epub.epub import BookMetadata
from ranobelib_epub.inventory import (
    ChapterBranchVariant,
    ChapterInventory,
    InventoryWarning,
    LogicalChapter,
    parse_chapter_inventory,
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


class FakeRowLevelBranchInventoryService:
    def fetch(self, title: RanobeLibTitleUrl) -> ChapterInventory:
        return parse_chapter_inventory(
            title.slug,
            {
                "data": [
                    {
                        "id": 100,
                        "branch_id": 55,
                        "volume": "1",
                        "number": "2",
                        "name": "Row branch",
                        "teams": [{"name": "Team A"}],
                    }
                ]
            },
        )


class FakeBuildService:
    def __init__(self) -> None:
        self.calls: list[
            tuple[RanobeLibTitleUrl, BookMetadata, tuple[ChapterBranchVariant, ...], bool]
        ] = []

    def build(
        self,
        title: RanobeLibTitleUrl,
        metadata: BookMetadata,
        variants: tuple[ChapterBranchVariant, ...],
        *,
        include_images: bool = False,
    ) -> bytes:
        self.calls.append((title, metadata, variants, include_images))
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
    assert "/book/" in response.text
    assert "/manga/" in response.text


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
    assert "Branch cards" in response.text
    assert "Team A" in response.text
    assert "Branch ID: 55" in response.text
    assert "Buildable chapters: 1" in response.text
    assert "Volume range: 1–1" in response.text
    assert "Chapter range: 2–2" in response.text
    assert "Volume 1" in response.text
    assert "Two roads" in response.text
    assert 'action="/build"' in response.text
    assert 'method="post"' in response.text
    assert 'name="title_url"' in response.text
    assert 'name="book_title"' in response.text
    assert 'value="demo-title"' in response.text
    assert 'name="author"' in response.text
    assert 'name="translator"' in response.text
    assert 'name="team"' in response.text
    assert 'name="language"' in response.text
    assert 'value="ru"' in response.text
    assert "Build settings" in response.text
    assert 'name="include_images"' in response.text
    assert 'name="include_images" value="true" checked' not in response.text
    assert "Images can make the build slower and the EPUB larger." in response.text
    assert 'name="selected_variant"' in response.text
    assert response.text.count('<input type="checkbox" name="selected_variant"') == 1
    assert "non-buildable" in response.text
    assert "not selectable" in response.text
    assert "Chapter branch variant is not buildable" in response.text
    assert f"Synchronous build limit</dt><dd>{MAX_SYNC_BUILD_VARIANTS} variants" in response.text
    assert f"Current synchronous build limit: {MAX_SYNC_BUILD_VARIANTS}" in response.text
    assert "Apply range inside this branch" in response.text
    assert "Build this branch/range" in response.text
    assert "Build checked chapters" in response.text
    assert "Building EPUB…" in response.text
    assert "Fetching selected chapters and optional images, then packaging EPUB. Keep this tab open." in response.text
    assert 'data-build-active-state' in response.text
    assert 'data-build-complete-state' in response.text
    assert "Download ready / Download started." in response.text
    assert 'data-build-error-state' in response.text
    assert "fetch(form.action" in response.text
    assert (
        "const body = submitter ? new FormData(form, submitter) : new FormData(form);"
        in response.text
    )
    assert "triggerDownload" in response.text
    assert "use branch/range filters or split the title into multiple EPUB files" in response.text
    assert "background worker" not in response.text.lower()
    assert "progress polling" not in response.text.lower()


def test_inventory_preview_accepts_manga_url_with_fake_service_without_network() -> None:
    service = FakeInventoryService()
    app.dependency_overrides[get_inventory_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.get(
            "/inventory",
            params={
                "title_url": "https://ranobelib.me/ru/manga/264055--the-shut-in-apothecary-slime"
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert service.seen == [
        RanobeLibTitleUrl(
            title_id=264055,
            slug="the-shut-in-apothecary-slime",
            locale="ru",
            path_kind="manga",
        )
    ]
    assert (
        "https://ranobelib.me/ru/manga/264055--the-shut-in-apothecary-slime"
        in response.text
    )


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
                "book_title": "Custom Book",
                "author": "Author One",
                "translator": "Translator One",
                "team": "Team One",
                "language": "ru",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    assert response.headers["content-disposition"] == 'attachment; filename="demo-title.epub"'
    assert response.content == b"fake epub bytes"
    assert len(service.calls) == 1
    title, metadata, variants, include_images = service.calls[0]
    assert title == RanobeLibTitleUrl(title_id=12345, slug="demo-title", locale="ru")
    assert metadata == BookMetadata(
        title="Custom Book",
        author="Author One",
        translator="Translator One",
        team="Team One",
        language="ru",
        identifier="https://ranobelib.me/ru/book/12345--demo-title",
    )
    assert variants[0].branch_id == 55
    assert include_images is False


def test_build_route_passes_include_images_true_when_checked() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payload(),
                "include_images": "true",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    _, _, variants, include_images = service.calls[0]
    assert [variant.external_chapter_id for variant in variants] == [101]
    assert include_images is True


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
    _, _, variants, include_images = service.calls[0]
    assert [variant.external_chapter_id for variant in variants] == [101, 102]
    assert [variant.number for variant in variants] == ["1", "2"]
    assert include_images is False


def test_build_route_rejects_blank_title_before_build_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payload(),
                "book_title": "   ",
                "language": "ru",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Book title must not be blank" in response.text
    assert "Traceback" not in response.text
    assert service.calls == []


def test_build_route_rejects_malformed_language_before_build_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payload(),
                "book_title": "Demo",
                "language": "ru_123",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Language must be a valid language tag" in response.text
    assert "Traceback" not in response.text
    assert service.calls == []


def test_build_route_normalizes_blank_optional_metadata_fields_to_none() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payload(),
                "book_title": "Demo",
                "author": " ",
                "translator": "",
                "team": " ",
                "language": "ru",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    _, metadata, _, include_images = service.calls[0]
    assert metadata.author is None
    assert metadata.translator is None
    assert metadata.team is None
    assert include_images is False


def test_build_filename_remains_slug_based_with_free_form_title() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payload(),
                "book_title": "Название?! / free form",
                "language": "ru",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="demo-title.epub"'


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


def test_inventory_preview_renders_branch_card_range_controls() -> None:
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
    assert "Apply range inside this branch" in response.text
    assert 'name="bulk_variant"' in response.text
    assert response.text.count('name="bulk_variant"') == 1
    assert 'name="bulk_branch_id"' in response.text
    assert 'value="55"' in response.text
    assert "Team A" in response.text
    assert "Branch ID: 55" in response.text
    assert 'name="volume_from"' in response.text
    assert 'name="volume_to"' in response.text
    assert 'name="chapter_from"' in response.text
    assert 'name="chapter_to"' in response.text


def test_inventory_preview_renders_row_level_branch_id_variant() -> None:
    service = FakeRowLevelBranchInventoryService()
    app.dependency_overrides[get_inventory_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.get(
            "/inventory", params={"title_url": "https://ranobelib.me/ru/book/12345--demo-title"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "No buildable variants available." not in response.text
    assert "Branch ID: 55" in response.text
    assert "Buildable chapters: 1" in response.text
    assert "Row branch" in response.text
    assert "Team A" in response.text
    assert 'name="selected_variant"' in response.text
    assert response.text.count('<input type="checkbox" name="selected_variant"') == 1


def test_build_route_accepts_bulk_payload_when_no_manual_checkbox_selected() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "bulk_variant": [
                    _variant_payload(external_chapter_id=101, branch_id=55, number="1"),
                    _variant_payload(external_chapter_id=102, branch_id=55, number="2"),
                    _variant_payload(external_chapter_id=103, branch_id=66, number="2"),
                ],
                "bulk_branch_id": "55",
                "chapter_from": "2",
                "chapter_to": "2",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    _, _, variants, include_images = service.calls[0]
    assert [variant.external_chapter_id for variant in variants] == [102]
    assert include_images is False


def test_build_route_checked_mode_uses_selected_variants() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payload(
                    external_chapter_id=201, branch_id=55, number="7"
                ),
                "bulk_variant": _variant_payload(
                    external_chapter_id=202, branch_id=55, number="8"
                ),
                "selection_mode": "checked",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(service.calls) == 1
    _, _, variants, include_images = service.calls[0]
    assert [variant.external_chapter_id for variant in variants] == [201]
    assert include_images is False


def test_build_route_checked_mode_rejects_empty_selection_before_build_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "bulk_variant": _variant_payload(
                    external_chapter_id=202, branch_id=55, number="8"
                ),
                "selection_mode": "checked",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Select at least one checked chapter variant" in response.text
    assert "Traceback" not in response.text
    assert service.calls == []


def test_build_route_range_mode_uses_bulk_range_and_ignores_checked_variants() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payload(
                    external_chapter_id=999, branch_id=55, number="99"
                ),
                "bulk_variant": [
                    _variant_payload(external_chapter_id=301, branch_id=55, number="1"),
                    _variant_payload(external_chapter_id=302, branch_id=55, number="2"),
                    _variant_payload(external_chapter_id=303, branch_id=66, number="2"),
                ],
                "bulk_branch_id": "55",
                "chapter_from": "2",
                "chapter_to": "2",
                "selection_mode": "range",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(service.calls) == 1
    _, _, variants, include_images = service.calls[0]
    assert [variant.external_chapter_id for variant in variants] == [302]
    assert include_images is False


def test_build_route_accepts_bulk_payload_with_include_images_checked() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "bulk_variant": _variant_payload(external_chapter_id=101, branch_id=55, number="1"),
                "include_images": "true",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    _, _, variants, include_images = service.calls[0]
    assert [variant.external_chapter_id for variant in variants] == [101]
    assert include_images is True


def test_build_route_dedupes_bulk_payload_deterministically() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "bulk_variant": [
                    _variant_payload(external_chapter_id=101, branch_id=55, number="1"),
                    _variant_payload(external_chapter_id=101, branch_id=55, number="1"),
                    _variant_payload(external_chapter_id=102, branch_id=55, number="2"),
                ],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    _, _, variants, include_images = service.calls[0]
    assert [variant.external_chapter_id for variant in variants] == [101, 102]
    assert include_images is False


def test_build_route_rejects_bulk_no_match_before_build_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "bulk_variant": _variant_payload(),
                "bulk_branch_id": "999",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Bulk selection did not match any buildable chapter variants" in response.text
    assert service.calls == []


def test_build_route_rejects_malformed_bulk_payload_before_build_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "bulk_variant": "not json",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Bulk variant at position 1 is malformed" in response.text
    assert service.calls == []


def _variant_payloads(count: int) -> list[str]:
    return [
        _variant_payload(external_chapter_id=1000 + index, branch_id=55, number=str(index))
        for index in range(1, count + 1)
    ]


def test_build_route_rejects_manual_selection_over_sync_limit_before_build_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payloads(MAX_SYNC_BUILD_VARIANTS + 1),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert f"contains {MAX_SYNC_BUILD_VARIANTS + 1} chapter variants" in response.text
    assert f"configured maximum is {MAX_SYNC_BUILD_VARIANTS}" in response.text
    assert service.calls == []


def test_build_route_rejects_bulk_selection_over_sync_limit_before_build_service() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "bulk_variant": _variant_payloads(MAX_SYNC_BUILD_VARIANTS + 1),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert f"contains {MAX_SYNC_BUILD_VARIANTS + 1} chapter variants" in response.text
    assert f"configured maximum is {MAX_SYNC_BUILD_VARIANTS}" in response.text
    assert service.calls == []


def test_build_route_accepts_selection_exactly_at_sync_limit() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payloads(MAX_SYNC_BUILD_VARIANTS),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(service.calls) == 1
    _, _, variants, include_images = service.calls[0]
    assert len(variants) == MAX_SYNC_BUILD_VARIANTS
    assert include_images is False


def test_build_route_dedupes_before_sync_limit_check() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)
    duplicated_payload = _variant_payload(external_chapter_id=101, branch_id=55, number="1")

    try:
        response = client.post(
            "/build",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": [duplicated_payload] * (MAX_SYNC_BUILD_VARIANTS + 1),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(service.calls) == 1
    _, _, variants, include_images = service.calls[0]
    assert len(variants) == 1
    assert include_images is False
