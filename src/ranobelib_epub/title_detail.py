from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlencode

import httpx

from ranobelib_epub.inventory import (
    INVENTORY_HEADERS,
    RANOBELIB_API_BASE_URL,
    ChapterRequest,
    _public_headers,
)
from ranobelib_epub.ranobelib import RanobeLibTitleUrl

TITLE_DETAIL_FIELDS = (
    "background",
    "eng_name",
    "otherNames",
    "summary",
    "releaseDate",
    "type_id",
    "caution",
    "views",
    "close_view",
    "rate_avg",
    "rate",
    "genres",
    "tags",
    "teams",
    "user",
    "franchise",
    "authors",
    "publisher",
    "userRating",
    "moderated",
    "metadata",
    "metadata.count",
    "metadata.close_comments",
    "translation_quality_rating",
    "manga_status_id",
    "chap_count",
    "status_id",
    "artists",
    "format",
)


@dataclass(frozen=True, slots=True)
class TitleDetailMetadata:
    display_title: str
    author: str = ""
    cover_url: str | None = None
    uploaded_count: int | str | None = None
    status_label: str | None = None
    type_label: str | None = None


class TitleDetailTransport(Protocol):
    def get_json(self, request: ChapterRequest) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class HttpxTitleDetailTransport:
    timeout: float = 20.0

    def get_json(self, request: ChapterRequest) -> dict[str, Any]:
        if request.method.upper() != "GET":
            raise ValueError("RanobeLib title detail transport supports only read-only GET requests")
        response = httpx.request(
            request.method,
            request.url,
            headers=_public_headers(request.headers),
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("RanobeLib title detail response must be a JSON object")
        return payload


def build_title_detail_request(
    title: RanobeLibTitleUrl,
    *,
    base_url: str = RANOBELIB_API_BASE_URL,
    headers: dict[str, str] | None = None,
) -> ChapterRequest:
    clean_base = base_url.rstrip("/")
    title_path = quote(f"{title.title_id}--{title.slug}", safe="")
    query = urlencode([("fields[]", field_name) for field_name in TITLE_DETAIL_FIELDS])
    return ChapterRequest(
        method="GET",
        url=f"{clean_base}/api/manga/{title_path}?{query}",
        headers=_public_headers(headers or dict(INVENTORY_HEADERS)),
    )


def fetch_title_detail(
    title: RanobeLibTitleUrl,
    transport: TitleDetailTransport,
    *,
    base_url: str = RANOBELIB_API_BASE_URL,
) -> TitleDetailMetadata:
    request = build_title_detail_request(title, base_url=base_url)
    return parse_title_detail(title.slug, transport.get_json(request))


def fallback_title_detail(slug: str) -> TitleDetailMetadata:
    return TitleDetailMetadata(display_title=slug)


def parse_title_detail(slug: str, payload: dict[str, Any]) -> TitleDetailMetadata:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return fallback_title_detail(slug)

    display_title = _first_text(data.get("rus_name"), data.get("name"), data.get("eng_name"), slug)
    author = ", ".join(
        name
        for name in (
            _first_text(author.get("rus_name"), author.get("name"))
            for author in _dict_items(data.get("authors"))
        )
        if name
    )
    cover = data.get("cover")
    cover_url = None
    if isinstance(cover, dict):
        cover_url = _first_text(cover.get("default"), cover.get("md"), cover.get("thumbnail"))

    items_count = data.get("items_count")
    uploaded_count = items_count.get("uploaded") if isinstance(items_count, dict) else None

    return TitleDetailMetadata(
        display_title=display_title,
        author=author,
        cover_url=cover_url,
        uploaded_count=uploaded_count if isinstance(uploaded_count, (int, str)) else None,
        status_label=_nested_label(data.get("status")),
        type_label=_nested_label(data.get("type")),
    )


def _dict_items(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _nested_label(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return _first_text(value.get("label"))


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
