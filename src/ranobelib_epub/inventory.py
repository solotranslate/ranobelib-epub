from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, cast
from urllib.parse import quote, urlencode

import httpx

from ranobelib_epub.display_numbering import display_chapter_number

RANOBELIB_API_BASE_URL = "https://api.cdnlibs.org"
INVENTORY_HEADERS = {"Accept": "application/json", "Site-Id": "3"}
_FORBIDDEN_HEADER_PARTS = ("authorization", "cookie", "token", "session")


@dataclass(frozen=True, slots=True)
class ChapterRequest:
    """Safe public read-only request plan for RanobeLib chapter inventory/content APIs."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InventoryWarning:
    message: str
    logical_id: int | str | None = None
    variant_id: int | str | None = None


@dataclass(frozen=True, slots=True)
class ChapterBranchVariant:
    external_chapter_id: int | str | None
    branch_id: int | str | None
    volume: str | None
    number: str | None
    number_secondary: str | None
    chapter_title: str | None
    branch_team: str | None = None
    branch_user: str | None = None
    published_at: str | None = None
    created_at: str | None = None
    is_default_branch: bool = False

    @property
    def is_buildable(self) -> bool:
        has_branch_selector = self.branch_id is not None or self.is_default_branch
        return has_branch_selector and self.volume is not None and self.number is not None

    @property
    def display_label(self) -> str:
        label = _chapter_label(self.volume, self.number, self.number_secondary, self.chapter_title)
        hint = self.branch_team or self.branch_user
        return f"{label} — {hint}" if hint else label


@dataclass(frozen=True, slots=True)
class BuildableChapterVariant(ChapterBranchVariant):
    branch_id: int | str | None
    volume: str
    number: str

    def __post_init__(self) -> None:
        if self.branch_id is None and not self.is_default_branch:
            raise ValueError("Buildable default branch variants must be marked explicitly")


@dataclass(frozen=True, slots=True)
class LogicalChapter:
    logical_id: int | str | None
    volume: str | None
    number: str | None
    number_secondary: str | None
    name: str | None
    bundle_id: int | str | None = None
    item: int | str | None = None
    index: int | str | None = None
    variants: tuple[ChapterBranchVariant, ...] = ()


@dataclass(frozen=True, slots=True)
class ChapterInventory:
    slug: str
    logical_chapters: tuple[LogicalChapter, ...]
    variants: tuple[ChapterBranchVariant, ...]
    warnings: tuple[InventoryWarning, ...] = ()

    @property
    def buildable_variants(self) -> tuple[BuildableChapterVariant, ...]:
        buildable: list[BuildableChapterVariant] = []
        for variant in self.variants:
            if variant.is_buildable:
                buildable.append(
                    BuildableChapterVariant(
                        external_chapter_id=variant.external_chapter_id,
                        branch_id=cast(int | str | None, variant.branch_id),
                        volume=cast(str, variant.volume),
                        number=cast(str, variant.number),
                        number_secondary=variant.number_secondary,
                        chapter_title=variant.chapter_title,
                        branch_team=variant.branch_team,
                        branch_user=variant.branch_user,
                        published_at=variant.published_at,
                        created_at=variant.created_at,
                        is_default_branch=variant.is_default_branch,
                    )
                )
        return tuple(buildable)


class InventoryTransport(Protocol):
    def get_json(self, request: ChapterRequest) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class HttpxInventoryTransport:
    timeout: float = 20.0

    def get_json(self, request: ChapterRequest) -> dict[str, Any]:
        if request.method.upper() != "GET":
            raise ValueError("RanobeLib inventory transport supports only read-only GET requests")
        safe_headers = _public_headers(request.headers)
        response = httpx.request(
            request.method, request.url, headers=safe_headers, timeout=self.timeout
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("RanobeLib inventory response must be a JSON object")
        return payload


def build_inventory_request(
    slug: str,
    *,
    base_url: str = RANOBELIB_API_BASE_URL,
    headers: dict[str, str] | None = None,
) -> ChapterRequest:
    safe_headers = _public_headers(headers)
    clean_base = base_url.rstrip("/")
    clean_slug = _validate_slug(slug)
    return ChapterRequest(
        method="GET",
        url=f"{clean_base}/api/manga/{quote(clean_slug, safe='')}/chapters",
        headers=safe_headers,
    )


def build_chapter_content_request(
    slug: str, variant: ChapterBranchVariant, *, base_url: str = RANOBELIB_API_BASE_URL
) -> ChapterRequest:
    if not variant.is_buildable:
        raise ValueError("Chapter content request requires a buildable branch variant")
    query_params: dict[str, int | str | None] = {}
    if not variant.is_default_branch:
        query_params["branch_id"] = variant.branch_id
    query_params["number"] = variant.number
    query_params["volume"] = variant.volume
    query = urlencode(query_params)
    clean_slug = quote(_validate_slug(slug), safe="")
    return ChapterRequest(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/manga/{clean_slug}/chapter?{query}",
        headers=dict(INVENTORY_HEADERS),
    )


def fetch_chapter_inventory(
    slug: str, transport: InventoryTransport, *, base_url: str = RANOBELIB_API_BASE_URL
) -> ChapterInventory:
    request = build_inventory_request(slug, base_url=base_url)
    return parse_chapter_inventory(slug, transport.get_json(request))


def parse_chapter_inventory(slug: str, payload: dict[str, Any]) -> ChapterInventory:
    raw_items = _inventory_items(payload)
    logicals: list[LogicalChapter] = []
    variants: list[ChapterBranchVariant] = []
    warnings: list[InventoryWarning] = []
    for row in raw_items:
        logical = _logical_chapter(row)
        branches = _branches(row)
        row_variants = tuple(
            _variant_from_branch(
                logical,
                row,
                branch,
                is_default_branch=_is_single_default_branch(row, branches, branch),
            )
            for branch in branches
        )
        if not row_variants:
            row_variants = (_variant_from_branch(logical, row, None),)
        for variant in row_variants:
            if not variant.is_buildable:
                warnings.append(
                    InventoryWarning(
                        "Chapter branch variant is not buildable",
                        logical.logical_id,
                        variant.external_chapter_id,
                    )
                )
        logicals.append(_replace_variants(logical, row_variants))
        variants.extend(row_variants)
    return ChapterInventory(
        slug=slug,
        logical_chapters=tuple(logicals),
        variants=tuple(variants),
        warnings=tuple(warnings),
    )


def _public_headers(custom: dict[str, str] | None) -> dict[str, str]:
    headers = dict(INVENTORY_HEADERS if custom is None else custom)
    unsafe = [
        name for name in headers if any(part in name.lower() for part in _FORBIDDEN_HEADER_PARTS)
    ]
    if unsafe:
        raise ValueError(
            f"Forbidden private headers for public RanobeLib request: {', '.join(sorted(unsafe))}"
        )
    return headers


def _validate_slug(slug: str) -> str:
    clean = slug.strip()
    if not clean or "/" in clean or "?" in clean or "#" in clean:
        raise ValueError("RanobeLib slug must be a non-empty title slug")
    return clean


def _inventory_items(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    candidate: Any = payload.get("data", payload)
    if isinstance(candidate, dict):
        candidate = (
            candidate.get("chapters") or candidate.get("items") or candidate.get("data") or []
        )
    if not isinstance(candidate, list):
        raise ValueError("RanobeLib inventory payload does not contain a chapter list")
    return tuple(item for item in candidate if isinstance(item, dict))


def _logical_chapter(row: dict[str, Any]) -> LogicalChapter:
    return LogicalChapter(
        logical_id=_first(row, "id", "chapter_id", "chapterId"),
        volume=_text(_first(row, "volume")),
        number=_text(_first(row, "number")),
        number_secondary=_text(_first(row, "number_secondary", "numberSecondary")),
        name=_text(_first(row, "name", "title")),
        bundle_id=_first(row, "bundle_id", "bundleId"),
        item=_first(row, "item"),
        index=_first(row, "index"),
    )


def _branches(row: dict[str, Any]) -> tuple[dict[str, Any] | None, ...]:
    branches = row.get("branches")
    if not isinstance(branches, list):
        return ()
    return tuple(branch for branch in branches if isinstance(branch, dict))


def _variant_from_branch(
    logical: LogicalChapter,
    row: dict[str, Any],
    branch: dict[str, Any] | None,
    *,
    is_default_branch: bool = False,
) -> ChapterBranchVariant:
    return ChapterBranchVariant(
        external_chapter_id=_branch_first(row, branch, "chapter_id", "chapterId", "id")
        or logical.logical_id,
        branch_id=_branch_first(row, branch, "branch_id", "branchId"),
        volume=_text(_branch_first(row, branch, "volume")) or logical.volume,
        number=_text(_branch_first(row, branch, "number")) or logical.number,
        number_secondary=_text(_branch_first(row, branch, "number_secondary", "numberSecondary"))
        or logical.number_secondary,
        chapter_title=_text(_branch_first(row, branch, "name", "title")) or logical.name,
        branch_team=_display(_branch_first(row, branch, "team", "teams", "branch")),
        branch_user=_display(_branch_first(row, branch, "user", "creator")),
        published_at=_text(_branch_first(row, branch, "published_at", "publishedAt")),
        created_at=_text(_branch_first(row, branch, "created_at", "createdAt")),
        is_default_branch=is_default_branch,
    )


def _is_single_default_branch(
    row: dict[str, Any],
    branches: tuple[dict[str, Any] | None, ...],
    branch: dict[str, Any] | None,
) -> bool:
    if branch is None or len(branches) != 1:
        return False
    if _branch_first(row, branch, "branch_id", "branchId") is not None:
        return False
    return _text(_branch_first(row, branch, "volume")) is not None and _text(
        _branch_first(row, branch, "number")
    ) is not None


def _branch_first(row: dict[str, Any], branch: dict[str, Any] | None, *keys: str) -> Any:
    if branch is not None:
        value = _first(branch, *keys)
        if value is not None:
            return value
    return _first(row, *keys)


def _replace_variants(
    logical: LogicalChapter, variants: tuple[ChapterBranchVariant, ...]
) -> LogicalChapter:
    return LogicalChapter(
        logical_id=logical.logical_id,
        volume=logical.volume,
        number=logical.number,
        number_secondary=logical.number_secondary,
        name=logical.name,
        bundle_id=logical.bundle_id,
        item=logical.item,
        index=logical.index,
        variants=variants,
    )


def _chapter_label(
    volume: str | None, number: str | None, secondary: str | None, title: str | None
) -> str:
    parts: list[str] = []
    if volume:
        parts.append(f"Volume {volume}")
    chapter_number = display_chapter_number(number, secondary)
    if chapter_number:
        parts.append(f"Chapter {chapter_number}")
    base = " ".join(parts) if parts else "Chapter"
    return f"{base}: {title}" if title else base


def _display(value: Any) -> str | None:
    if isinstance(value, list):
        names = [_display(item) for item in value]
        return ", ".join(name for name in names if name) or None
    if isinstance(value, dict):
        return _text(_first(value, "name", "title", "username", "login", "slug"))
    return _text(value)


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
