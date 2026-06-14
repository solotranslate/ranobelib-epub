import pytest

from ranobelib_epub.inventory import (
    ChapterBranchVariant,
    build_chapter_content_request,
    build_inventory_request,
    parse_chapter_inventory,
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
