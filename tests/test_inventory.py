import pytest

from ranobelib_epub.inventory import (
    ChapterBranchVariant,
    ChapterRequest,
    HttpxInventoryTransport,
    build_chapter_content_request,
    build_inventory_request,
    parse_chapter_inventory,
)
from ranobelib_epub.ranobelib import RanobeLibTitleUrl
from ranobelib_epub.title_detail import build_title_detail_request, parse_title_detail


def test_httpx_transport_rejects_non_get_requests_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_request(*args: object, **kwargs: object) -> None:
        raise AssertionError("transport attempted to send a non-GET request")

    monkeypatch.setattr("ranobelib_epub.inventory.httpx.request", fail_request)

    with pytest.raises(ValueError, match="only read-only GET"):
        HttpxInventoryTransport().get_json(ChapterRequest("POST", "https://api.example.test"))


def test_httpx_transport_rejects_private_headers_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_request(*args: object, **kwargs: object) -> None:
        raise AssertionError("transport attempted to send a private header")

    monkeypatch.setattr("ranobelib_epub.inventory.httpx.request", fail_request)

    with pytest.raises(ValueError, match="Forbidden private headers"):
        HttpxInventoryTransport().get_json(
            ChapterRequest("GET", "https://api.example.test", {"Authorization": "Bearer x"})
        )


def test_builds_expected_inventory_request_for_valid_slug() -> None:
    request = build_inventory_request("demo-title", base_url="https://api.example.test/")

    assert request.method == "GET"
    assert request.url == "https://api.example.test/api/manga/demo-title/chapters"
    assert request.headers == {"Accept": "application/json", "Site-Id": "3"}


def test_rejects_unsafe_public_request_headers() -> None:
    with pytest.raises(ValueError, match="Forbidden private headers"):
        build_inventory_request(
            "demo-title", headers={"Accept": "application/json", "Cookie": "sid=1"}
        )


def test_expands_one_logical_chapter_with_two_branches_into_two_variants() -> None:
    inventory = parse_chapter_inventory(
        "demo-title",
        {
            "data": [
                {
                    "id": 100,
                    "volume": "1",
                    "number": "2",
                    "name": "Two roads",
                    "branches": [
                        {
                            "chapter_id": 501,
                            "branch_id": 10,
                            "team": {"name": "Team A"},
                            "created_at": "2026-01-01T00:00:00Z",
                        },
                        {
                            "chapter_id": 502,
                            "branch_id": 20,
                            "user": {"username": "solo"},
                            "published_at": "2026-01-02T00:00:00Z",
                        },
                    ],
                }
            ]
        },
    )

    assert len(inventory.logical_chapters) == 1
    assert len(inventory.variants) == 2
    assert inventory.variants[0].branch_id == 10
    assert inventory.variants[0].display_label == "Volume 1 Chapter 2: Two roads — Team A"
    assert inventory.variants[1].branch_id == 20
    assert inventory.variants[1].display_label == "Volume 1 Chapter 2: Two roads — solo"
    assert len(inventory.buildable_variants) == 2


def test_row_level_branch_id_without_branches_list_becomes_buildable() -> None:
    inventory = parse_chapter_inventory(
        "single-branch-title",
        {
            "data": [
                {
                    "id": 100,
                    "branch_id": 55,
                    "volume": "1",
                    "number": "2",
                    "name": "Row branch",
                }
            ]
        },
    )

    assert len(inventory.variants) == 1
    assert inventory.variants[0].external_chapter_id == 100
    assert inventory.variants[0].branch_id == 55
    assert inventory.variants[0].is_buildable is True
    assert len(inventory.buildable_variants) == 1
    assert inventory.warnings == ()


def test_row_level_branch_id_accepts_camel_case_and_chapter_id_fallbacks() -> None:
    inventory = parse_chapter_inventory(
        "single-branch-title",
        {
            "data": [
                {
                    "chapterId": 501,
                    "branchId": 55,
                    "volume": "1",
                    "number": "2",
                    "title": "Camel row branch",
                }
            ]
        },
    )

    assert inventory.variants[0].external_chapter_id == 501
    assert inventory.variants[0].branch_id == 55
    assert inventory.variants[0].display_label == "Volume 1 Chapter 2: Camel row branch"
    assert len(inventory.buildable_variants) == 1


def test_row_level_teams_appears_in_branch_label() -> None:
    inventory = parse_chapter_inventory(
        "single-branch-title",
        {
            "data": [
                {
                    "id": 100,
                    "branch_id": 55,
                    "volume": "1",
                    "number": "2",
                    "teams": [{"name": "Team A"}, {"name": "Team B"}],
                }
            ]
        },
    )

    assert inventory.variants[0].branch_team == "Team A, Team B"
    assert inventory.variants[0].display_label == "Volume 1 Chapter 2 — Team A, Team B"


def test_branch_payload_values_override_row_level_fallbacks() -> None:
    inventory = parse_chapter_inventory(
        "multi-branch-title",
        {
            "data": [
                {
                    "id": 100,
                    "chapter_id": 400,
                    "branch_id": 55,
                    "volume": "1",
                    "number": "2",
                    "name": "Row title",
                    "team": {"name": "Row Team"},
                    "branches": [
                        {
                            "chapter_id": 501,
                            "branch_id": 66,
                            "volume": "3",
                            "number": "4",
                            "title": "Branch title",
                            "team": {"name": "Branch Team"},
                        }
                    ],
                }
            ]
        },
    )

    assert inventory.variants[0].external_chapter_id == 501
    assert inventory.variants[0].branch_id == 66
    assert inventory.variants[0].volume == "3"
    assert inventory.variants[0].number == "4"
    assert inventory.variants[0].chapter_title == "Branch title"
    assert inventory.variants[0].branch_team == "Branch Team"


def test_branch_payload_uses_row_level_values_as_fallbacks() -> None:
    inventory = parse_chapter_inventory(
        "multi-branch-title",
        {
            "data": [
                {
                    "id": 100,
                    "branch_id": 55,
                    "volume": "1",
                    "number": "2",
                    "name": "Row title",
                    "user": {"username": "row-user"},
                    "branches": [{"chapter_id": 501}],
                }
            ]
        },
    )

    assert inventory.variants[0].external_chapter_id == 501
    assert inventory.variants[0].branch_id == 55
    assert inventory.variants[0].volume == "1"
    assert inventory.variants[0].number == "2"
    assert inventory.variants[0].chapter_title == "Row title"
    assert inventory.variants[0].branch_user == "row-user"
    assert inventory.variants[0].is_buildable is True


@pytest.mark.parametrize(
    ("branch_id", "volume", "number"),
    [(None, "1", "2"), (10, None, "2"), (10, "1", None)],
)
def test_marks_variants_missing_required_build_fields_as_non_buildable(
    branch_id: int | None, volume: str | None, number: str | None
) -> None:
    variant = ChapterBranchVariant(
        external_chapter_id=501,
        branch_id=branch_id,
        volume=volume,
        number=number,
        number_secondary=None,
        chapter_title="Incomplete",
    )

    assert variant.is_buildable is False


def test_inventory_retains_non_buildable_variants_with_warnings() -> None:
    inventory = parse_chapter_inventory(
        "demo-title",
        {
            "data": [
                {
                    "id": 100,
                    "volume": "1",
                    "name": "No number",
                    "branches": [{"branch_id": 10}],
                }
            ]
        },
    )

    assert len(inventory.variants) == 1
    assert inventory.variants[0].is_buildable is False
    assert inventory.buildable_variants == ()
    assert inventory.warnings[0].message == "Chapter branch variant is not buildable"


def test_row_without_branch_id_remains_non_buildable_with_warning() -> None:
    inventory = parse_chapter_inventory(
        "demo-title",
        {"data": [{"id": 100, "volume": "1", "number": "2", "name": "Missing branch"}]},
    )

    assert len(inventory.variants) == 1
    assert inventory.variants[0].branch_id is None
    assert inventory.variants[0].is_buildable is False
    assert inventory.buildable_variants == ()
    assert inventory.warnings[0].message == "Chapter branch variant is not buildable"
    assert inventory.warnings[0].logical_id == 100
    assert inventory.warnings[0].variant_id == 100


def test_single_missing_branch_id_does_not_use_branch_payload_id_as_branch_id() -> None:
    inventory = parse_chapter_inventory(
        "demo-title",
        {
            "data": [
                {
                    "id": 100,
                    "volume": "1",
                    "number": "2",
                    "name": "Branch id missing",
                    "branches": [{"id": 999, "chapter_id": 501}],
                }
            ]
        },
    )

    assert len(inventory.variants) == 1
    assert inventory.variants[0].external_chapter_id == 501
    assert inventory.variants[0].branch_id is None
    assert inventory.variants[0].is_default_branch is True
    assert inventory.variants[0].is_buildable is True
    assert len(inventory.buildable_variants) == 1
    assert inventory.warnings == ()


def test_single_default_branch_variant_becomes_buildable_and_preserves_label() -> None:
    inventory = parse_chapter_inventory(
        "default-title",
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

    assert len(inventory.variants) == 1
    variant = inventory.variants[0]
    assert variant.external_chapter_id == 4163383
    assert variant.branch_id is None
    assert variant.is_default_branch is True
    assert variant.is_buildable is True
    assert variant.branch_team == "solotranslating"
    assert variant.display_label == "Volume 1 Chapter 1 — solotranslating"
    assert inventory.buildable_variants[0].is_default_branch is True
    assert inventory.warnings == ()


def test_default_branch_content_request_omits_branch_id() -> None:
    variant = ChapterBranchVariant(
        4163383,
        None,
        "1",
        "1",
        None,
        None,
        branch_team="solotranslating",
        is_default_branch=True,
    )

    request = build_chapter_content_request(
        "default-title", variant, base_url="https://api.example.test"
    )

    assert (
        request.url
        == "https://api.example.test/api/manga/default-title/chapter?number=1&volume=1"
    )


def test_multi_branch_missing_branch_id_remains_non_buildable() -> None:
    inventory = parse_chapter_inventory(
        "ambiguous-title",
        {
            "data": [
                {
                    "id": 100,
                    "volume": "1",
                    "number": "1",
                    "branches": [
                        {"id": 100, "branch_id": None, "teams": [{"slug": "team-a"}]},
                        {"id": 101, "branch_id": None, "teams": [{"slug": "team-b"}]},
                    ],
                }
            ]
        },
    )

    assert len(inventory.variants) == 2
    assert all(variant.branch_id is None for variant in inventory.variants)
    assert all(variant.is_default_branch is False for variant in inventory.variants)
    assert all(variant.is_buildable is False for variant in inventory.variants)
    assert inventory.buildable_variants == ()
    assert len(inventory.warnings) == 2


def test_produces_deterministic_display_label_for_unnamed_chapter() -> None:
    variant = ChapterBranchVariant(
        external_chapter_id=501,
        branch_id=10,
        volume="3",
        number="7",
        number_secondary="5",
        chapter_title=None,
        branch_team="Team A",
    )

    assert variant.display_label == "Volume 3 Chapter 7.5 — Team A"


def test_builds_read_only_chapter_content_request_plan_for_buildable_variant() -> None:
    variant = ChapterBranchVariant(501, 10, "3", "7", None, "Name")

    request = build_chapter_content_request(
        "demo-title", variant, base_url="https://api.example.test"
    )

    assert request.method == "GET"
    assert (
        request.url
        == "https://api.example.test/api/manga/demo-title/chapter?branch_id=10&number=7&volume=3"
    )


def test_title_detail_parser_extracts_display_author_and_cover() -> None:
    detail = parse_title_detail(
        "demo-title",
        {
            "data": {
                "rus_name": "Русское название",
                "name": "English Name",
                "eng_name": "Alt English",
                "cover": {
                    "thumbnail": "https://img.example.test/thumb.jpg",
                    "md": "https://img.example.test/md.jpg",
                    "default": "https://img.example.test/default.jpg",
                },
                "authors": [{"rus_name": "Автор Один", "name": "Author One"}],
                "items_count": {"uploaded": 42},
                "status": {"label": "Онгоинг"},
                "type": {"label": "Япония"},
            }
        },
    )

    assert detail.display_title == "Русское название"
    assert detail.author == "Автор Один"
    assert detail.cover_url == "https://img.example.test/default.jpg"
    assert detail.uploaded_count == 42
    assert detail.status_label == "Онгоинг"
    assert detail.type_label == "Япония"

def test_title_detail_parser_falls_back_when_fields_are_missing() -> None:
    detail = parse_title_detail("demo-title", {"data": {}})

    assert detail.display_title == "demo-title"
    assert detail.author == ""
    assert detail.cover_url is None


def test_title_detail_request_uses_public_get_with_safe_headers() -> None:
    request = build_title_detail_request(
        RanobeLibTitleUrl(title_id=12345, slug="demo-title", locale="ru"),
        base_url="https://api.example.test/",
    )

    assert request.method == "GET"
    assert request.url.startswith("https://api.example.test/api/manga/12345--demo-title?")
    assert "fields%5B%5D=eng_name" in request.url
    assert request.headers == {"Accept": "application/json", "Site-Id": "3"}


def test_display_label_hides_default_secondary_for_unnamed_chapter() -> None:
    variant = ChapterBranchVariant(
        external_chapter_id=501,
        branch_id=10,
        volume="1",
        number="3",
        number_secondary="1",
        chapter_title=None,
    )

    assert variant.display_label == "Volume 1 Chapter 3"


def test_display_label_preserves_meaningful_secondary_for_unnamed_chapter() -> None:
    variant = ChapterBranchVariant(
        external_chapter_id=501,
        branch_id=10,
        volume=None,
        number="3",
        number_secondary="2",
        chapter_title=None,
    )

    assert variant.display_label == "Chapter 3.2"
