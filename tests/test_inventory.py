import pytest

from ranobelib_epub.inventory import (
    ChapterBranchVariant,
    ChapterRequest,
    HttpxInventoryTransport,
    build_chapter_content_request,
    build_inventory_request,
    parse_chapter_inventory,
)


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


def test_branch_id_does_not_fallback_to_branch_payload_id() -> None:
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
    assert inventory.variants[0].is_buildable is False
    assert inventory.buildable_variants == ()
    assert inventory.warnings[0].message == "Chapter branch variant is not buildable"


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
