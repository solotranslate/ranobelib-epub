import json

from fastapi.testclient import TestClient

import ranobelib_epub.app as app_module
from ranobelib_epub.app import (
    MAX_SYNC_BUILD_VARIANTS,
    app,
    get_build_service,
    get_inventory_service,
    get_title_detail_service,
)
from ranobelib_epub.epub import BookMetadata
from ranobelib_epub.inventory import (
    ChapterBranchVariant,
    ChapterInventory,
    InventoryWarning,
    LogicalChapter,
    parse_chapter_inventory,
)
from ranobelib_epub.jobs import BuildJobSnapshot
from ranobelib_epub.ranobelib import RanobeLibTitleUrl
from ranobelib_epub.title_detail import TitleDetailMetadata


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


class FakeDefaultBranchInventoryService:
    def fetch(self, title: RanobeLibTitleUrl) -> ChapterInventory:
        return parse_chapter_inventory(
            title.slug,
            {
                "data": [
                    {
                        "id": 4163383,
                        "volume": 1,
                        "number": 1,
                        "branches_count": 1,
                        "branches": [
                            {
                                "id": 4163383,
                                "branch_id": None,
                                "teams": [{"slug": "solotranslating"}],
                            }
                        ],
                    }
                ]
            },
        )


class FakeTitleDetailService:
    def __init__(self, detail: TitleDetailMetadata | None = None, *, fail: bool = False) -> None:
        self.detail = detail or TitleDetailMetadata(
            display_title="Русское название",
            author="Автор Один",
            cover_url="https://img.example.test/cover.jpg",
            uploaded_count=12,
            status_label="Онгоинг",
            type_label="Япония",
        )
        self.fail = fail

    def fetch(self, title: RanobeLibTitleUrl) -> TitleDetailMetadata:
        if self.fail:
            raise ValueError("detail unavailable")
        return self.detail


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
        progress_callback=None,
    ) -> bytes:
        if progress_callback is not None:
            progress_callback(
                "fetching_chapters",
                message="Fetching chapter 1 of 1",
                chapter_current=1,
                chapter_total=1,
            )
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
    assert "Сборщик EPUB для RanobeLib" in response.text
    assert "Показать список глав" in response.text
    assert 'name="title_url"' in response.text
    assert 'action="/inventory"' in response.text
    assert "/book/" in response.text
    assert "/manga/" in response.text


def test_inventory_preview_uses_fake_service_without_network() -> None:
    service = FakeInventoryService()
    app.dependency_overrides[get_inventory_service] = lambda: service
    app.dependency_overrides[get_title_detail_service] = lambda: FakeTitleDetailService()
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
    assert "Inventory preview" not in response.text
    assert "Русское название" in response.text
    assert "Автор Один" in response.text
    assert 'class="title-cover"' in response.text
    assert 'src="https://img.example.test/cover.jpg"' in response.text
    assert 'alt="Обложка: Русское название"' in response.text
    assert "Глав доступно: 1" in response.text
    assert "Загружено: 12" in response.text
    assert "Статус: Онгоинг" in response.text
    assert "Тип: Япония" in response.text
    assert "Ветки перевода" in response.text
    assert "Team A" in response.text
    assert "ID ветки: 55" in response.text
    assert "Глав доступно: 1" in response.text
    assert "Диапазон томов: 1–1" in response.text
    assert "Диапазон глав: 2–2" in response.text
    assert "Том 1" in response.text
    assert "Two roads" in response.text
    assert 'action="/build"' in response.text
    assert 'method="post"' in response.text
    assert 'name="title_url"' in response.text
    assert 'name="book_title"' in response.text
    assert 'value="Русское название"' in response.text
    assert 'name="author"' in response.text
    assert '<label>Translator' not in response.text
    assert '<label>Team' not in response.text
    assert '<label>Language' not in response.text
    assert 'type="hidden" name="language" value="ru"' in response.text
    assert "Настройки сборки" in response.text
    assert 'name="include_images"' in response.text
    assert 'name="include_images" value="true" checked' in response.text
    assert "Иллюстрации могут замедлить сборку и увеличить размер EPUB." in response.text
    assert 'name="selected_variant"' in response.text
    assert response.text.count('<input type="checkbox" name="selected_variant"') == 1
    assert "недоступно для сборки" in response.text
    assert "нельзя выбрать" in response.text
    assert "Chapter branch variant is not buildable" in response.text
    assert f"Текущий лимит синхронной сборки: {MAX_SYNC_BUILD_VARIANTS}" in response.text
    assert "Выбрать диапазон внутри этой ветки" in response.text
    assert "Собрать эту ветку/диапазон" in response.text
    assert "Собрать отмеченные главы" in response.text
    assert "Собираю EPUB…" in response.text
    assert "Загружаю выбранные главы и иллюстрации, затем упаковываю EPUB. Не закрывайте эту вкладку." in response.text
    assert 'data-build-active-state' in response.text
    assert 'data-build-complete-state' in response.text
    assert "Файл готов / скачивание началось." in response.text
    assert 'data-build-error-state' in response.text
    assert "fetch('/build-jobs'" in response.text
    assert "pollJob" in response.text
    assert "/build-jobs/${encodeURIComponent(jobId)}" in response.text
    assert "data-build-status-message" in response.text
    assert "data-build-status-counts" in response.text
    assert "data-build-download-link" in response.text
    assert (
        "const body = submitter ? new FormData(form, submitter) : new FormData(form);"
        in response.text
    )
    assert "triggerDownload" in response.text
    assert "используйте фильтры ветки/диапазона или разделите тайтл на несколько EPUB-файлов" in response.text
    assert "background worker" not in response.text.lower()
    assert "progress polling" not in response.text.lower()
    assert "Предупреждения" in response.text
    assert "No warnings" not in response.text
    assert "Сервис сейчас занят. Попробуйте чуть позже." in response.text
    assert "start.status === 429 || start.status === 409" in response.text
    assert "target.textContent = error.message || 'Сборка не удалась.'" in response.text
    assert "form.classList.remove('is-building')" in response.text
    assert "submitter.disabled = false" in response.text


def test_inventory_preview_omits_warnings_card_when_clean() -> None:
    service = FakeRowLevelBranchInventoryService()
    app.dependency_overrides[get_inventory_service] = lambda: service
    app.dependency_overrides[get_title_detail_service] = lambda: FakeTitleDetailService()
    client = TestClient(app)

    try:
        response = client.get(
            "/inventory", params={"title_url": "https://ranobelib.me/ru/book/12345--demo-title"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Предупреждения" not in response.text
    assert "Warnings" not in response.text
    assert "No warnings" not in response.text


def test_build_jobs_busy_response_is_controlled_russian_message() -> None:
    service = FakeBuildService()
    app.dependency_overrides[get_build_service] = lambda: service
    client = TestClient(app)
    app_module.BUILD_JOBS._jobs["active"] = BuildJobSnapshot(
        job_id="active",
        status="fetching_chapters",
        message="Загружаю главу 1 из 1",
        created_at=app_module.BUILD_JOBS._clock(),
        updated_at=app_module.BUILD_JOBS._clock(),
    )

    try:
        response = client.post(
            "/build-jobs",
            data={
                "title_url": "https://ranobelib.me/ru/book/12345--demo-title",
                "selected_variant": _variant_payload(),
            },
        )
    finally:
        app.dependency_overrides.clear()
        app_module.BUILD_JOBS._jobs.pop("active", None)

    assert response.status_code == 429
    assert response.json() == {"message": "Сервис сейчас занят. Попробуйте чуть позже."}
    assert service.calls == []


def test_inventory_preview_accepts_manga_url_with_fake_service_without_network() -> None:
    service = FakeInventoryService()
    app.dependency_overrides[get_inventory_service] = lambda: service
    app.dependency_overrides[get_title_detail_service] = lambda: FakeTitleDetailService()
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
    app.dependency_overrides[get_title_detail_service] = lambda: FakeTitleDetailService()
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
    assert "Название книги не должно быть пустым" in response.text
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
    assert "Язык должен быть корректным языковым тегом" in response.text
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
    assert "Выберите хотя бы одну доступную для сборки главу" in response.text
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
    assert "Выбранная глава на позиции 1 содержит некорректные данные" in response.text
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
    assert "Выбранная глава на позиции 1 недоступна для сборки" in response.text
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
    app.dependency_overrides[get_title_detail_service] = lambda: FakeTitleDetailService()
    client = TestClient(app)

    try:
        response = client.get(
            "/inventory", params={"title_url": "https://ranobelib.me/ru/book/12345--demo-title"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Выбрать диапазон внутри этой ветки" in response.text
    assert 'name="bulk_variant"' in response.text
    assert response.text.count('name="bulk_variant"') == 1
    assert 'name="bulk_branch_id"' in response.text
    assert 'value="55"' in response.text
    assert "Team A" in response.text
    assert "ID ветки: 55" in response.text
    assert 'name="volume_from"' in response.text
    assert 'name="volume_to"' in response.text
    assert 'name="chapter_from"' in response.text
    assert 'name="chapter_to"' in response.text


def test_inventory_preview_renders_row_level_branch_id_variant() -> None:
    service = FakeRowLevelBranchInventoryService()
    app.dependency_overrides[get_inventory_service] = lambda: service
    app.dependency_overrides[get_title_detail_service] = lambda: FakeTitleDetailService()
    client = TestClient(app)

    try:
        response = client.get(
            "/inventory", params={"title_url": "https://ranobelib.me/ru/book/12345--demo-title"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Нет доступных для сборки вариантов." not in response.text
    assert "ID ветки: 55" in response.text
    assert "Глав доступно: 1" in response.text
    assert "Row branch" in response.text
    assert "Team A" in response.text
    assert 'name="selected_variant"' in response.text
    assert response.text.count('<input type="checkbox" name="selected_variant"') == 1


def test_inventory_preview_renders_default_branch_variant() -> None:
    service = FakeDefaultBranchInventoryService()
    app.dependency_overrides[get_inventory_service] = lambda: service
    app.dependency_overrides[get_title_detail_service] = lambda: FakeTitleDetailService()
    client = TestClient(app)

    try:
        response = client.get(
            "/inventory", params={"title_url": "https://ranobelib.me/ru/book/12345--demo-title"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Нет доступных для сборки вариантов." not in response.text
    assert "ID ветки: default" in response.text
    assert "Глав доступно: 1" in response.text
    assert "solotranslating" in response.text
    assert 'name="selected_variant"' in response.text
    assert "&quot;is_default_branch&quot;:true" in response.text


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
    assert "Отметьте хотя бы одну главу для сборки" in response.text
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
    assert "Выбранный диапазон не содержит доступных для сборки глав" in response.text
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
    assert "Глава из диапазона на позиции 1 содержит некорректные данные" in response.text
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
    assert str(MAX_SYNC_BUILD_VARIANTS + 1) in response.text
    assert f"настроенный максимум — {MAX_SYNC_BUILD_VARIANTS}" in response.text
    assert "разделите большой тайтл на несколько EPUB" in response.text
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
    assert str(MAX_SYNC_BUILD_VARIANTS + 1) in response.text
    assert f"настроенный максимум — {MAX_SYNC_BUILD_VARIANTS}" in response.text
    assert "разделите большой тайтл на несколько EPUB" in response.text
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


def test_inventory_preview_falls_back_when_title_detail_is_unavailable() -> None:
    service = FakeInventoryService()
    app.dependency_overrides[get_inventory_service] = lambda: service
    app.dependency_overrides[get_title_detail_service] = lambda: FakeTitleDetailService(fail=True)
    client = TestClient(app)

    try:
        response = client.get(
            "/inventory", params={"title_url": "https://ranobelib.me/ru/book/12345--demo-title"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert '<h1 id="title-name">demo-title</h1>' in response.text
    assert 'class="title-cover"' not in response.text
    assert 'name="book_title" value="demo-title"' in response.text
    assert 'type="hidden" name="language" value="ru"' in response.text
