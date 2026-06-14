from __future__ import annotations

import json
import re
from html import escape
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Form, Query
from fastapi.responses import HTMLResponse, Response

from ranobelib_epub.build import build_selected_chapter_epub
from ranobelib_epub.epub import BookMetadata
from ranobelib_epub.inventory import ChapterInventory, fetch_chapter_inventory
from ranobelib_epub.inventory import ChapterBranchVariant, HttpxInventoryTransport
from ranobelib_epub.ranobelib import RanobeLibTitleUrl, parse_title_url

app = FastAPI(title="RanobeLib EPUB Builder")
_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class InventoryService(Protocol):
    def fetch(self, title: RanobeLibTitleUrl) -> ChapterInventory: ...


class RanobeLibInventoryService:
    def __init__(self, transport: HttpxInventoryTransport | None = None) -> None:
        self._transport = transport or HttpxInventoryTransport()

    def fetch(self, title: RanobeLibTitleUrl) -> ChapterInventory:
        return fetch_chapter_inventory(title.slug, self._transport)


def get_inventory_service() -> InventoryService:
    return RanobeLibInventoryService()


class BuildService(Protocol):
    def build(
        self, title: RanobeLibTitleUrl, variants: tuple[ChapterBranchVariant, ...]
    ) -> bytes: ...


class RanobeLibBuildService:
    def __init__(self, transport: HttpxInventoryTransport | None = None) -> None:
        self._transport = transport or HttpxInventoryTransport()

    def build(self, title: RanobeLibTitleUrl, variants: tuple[ChapterBranchVariant, ...]) -> bytes:
        result = build_selected_chapter_epub(
            title.slug,
            BookMetadata(title=title.slug, identifier=title.canonical_url),
            variants,
            self._transport,
        )
        return result.epub_bytes


def get_build_service() -> BuildService:
    return RanobeLibBuildService()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>RanobeLib EPUB Builder</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      max-width: 760px;
      margin: 40px auto;
      padding: 0 16px;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }
    .card {
      border: 1px solid #ddd;
      border-radius: 16px;
      padding: 24px;
      box-shadow: 0 8px 24px rgba(0,0,0,.06);
    }
    input, button {
      font: inherit;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid #ccc;
    }
    input {
      width: 100%;
      box-sizing: border-box;
      margin: 8px 0 16px;
    }
    button {
      cursor: pointer;
    }
    .muted {
      color: #666;
      font-size: .95rem;
    }
  </style>
</head>
<body>
  <main class="card">
    <h1>RanobeLib EPUB Builder</h1>
    <p class="muted">
      Вставьте публичную ссылку на тайтл RanobeLib, чтобы посмотреть read-only preview
      доступных глав и веток перед будущей сборкой EPUB.
    </p>

    <form action="/inventory" method="get">
      <label for="title_url">Ссылка на тайтл RanobeLib</label>
      <input id="title_url" name="title_url" placeholder="https://ranobelib.me/ru/book/12345--title-slug" required>
      <button type="submit">Показать inventory</button>
    </form>
  </main>
</body>
</html>
"""


@app.get("/inventory", response_class=HTMLResponse, response_model=None)
def inventory_preview(
    title_url: str = Query(..., min_length=1),
    service: InventoryService = Depends(get_inventory_service),
) -> HTMLResponse:
    try:
        title = parse_title_url(title_url)
    except ValueError as exc:
        return _error_page(str(exc), status_code=400)

    try:
        inventory = service.fetch(title)
    except ValueError as exc:
        return _error_page(str(exc), status_code=400)

    return HTMLResponse(_inventory_page(title, inventory))


@app.post("/build", response_class=Response, response_model=None)
def build_epub_download(
    title_url: Annotated[str, Form(min_length=1)],
    selected_variant: Annotated[list[str] | None, Form()] = None,
    service: BuildService = Depends(get_build_service),
) -> Response:
    try:
        title = parse_title_url(title_url)
        variants = _selected_variants(selected_variant or [])
    except ValueError as exc:
        return _error_page(str(exc), status_code=400)

    try:
        epub_bytes = service.build(title, variants)
    except ValueError as exc:
        return _error_page(str(exc), status_code=400)

    filename = _epub_filename(title)
    return Response(
        content=epub_bytes,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _error_page(message: str, *, status_code: int) -> HTMLResponse:
    html = f"""
<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><title>Inventory error</title></head>
<body>
  <main>
    <h1>Inventory preview error</h1>
    <p>{escape(message)}</p>
    <p><a href="/">Back to form</a></p>
  </main>
</body>
</html>
"""
    return HTMLResponse(html, status_code=status_code)


def _selected_variants(raw_variants: list[str]) -> tuple[ChapterBranchVariant, ...]:
    if not raw_variants:
        raise ValueError("Select at least one buildable chapter variant")

    variants: list[ChapterBranchVariant] = []
    for index, raw_variant in enumerate(raw_variants, start=1):
        try:
            payload = json.loads(raw_variant)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Selected variant at position {index} is malformed") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Selected variant at position {index} is malformed")

        variant = _variant_from_form_payload(payload, index)
        if not variant.is_buildable:
            raise ValueError(f"Selected variant at position {index} is not buildable")
        variants.append(variant)
    return tuple(variants)


def _variant_from_form_payload(payload: dict[str, Any], index: int) -> ChapterBranchVariant:
    allowed = {
        "external_chapter_id",
        "branch_id",
        "volume",
        "number",
        "number_secondary",
        "chapter_title",
        "branch_team",
        "branch_user",
        "published_at",
        "created_at",
    }
    if any(key not in allowed for key in payload):
        raise ValueError(f"Selected variant at position {index} is malformed")
    return ChapterBranchVariant(
        external_chapter_id=payload.get("external_chapter_id"),
        branch_id=payload.get("branch_id"),
        volume=_optional_text(payload.get("volume")),
        number=_optional_text(payload.get("number")),
        number_secondary=_optional_text(payload.get("number_secondary")),
        chapter_title=_optional_text(payload.get("chapter_title")),
        branch_team=_optional_text(payload.get("branch_team")),
        branch_user=_optional_text(payload.get("branch_user")),
        published_at=_optional_text(payload.get("published_at")),
        created_at=_optional_text(payload.get("created_at")),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _variant_form_value(variant: ChapterBranchVariant) -> str:
    payload = {
        "external_chapter_id": variant.external_chapter_id,
        "branch_id": variant.branch_id,
        "volume": variant.volume,
        "number": variant.number,
        "number_secondary": variant.number_secondary,
        "chapter_title": variant.chapter_title,
        "branch_team": variant.branch_team,
        "branch_user": variant.branch_user,
        "published_at": variant.published_at,
        "created_at": variant.created_at,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _epub_filename(title: RanobeLibTitleUrl) -> str:
    stem = _SAFE_FILENAME_CHARS.sub("-", title.slug).strip(".-")
    return f"{stem or 'ranobelib-title'}.epub"


def _inventory_page(title: RanobeLibTitleUrl, inventory: ChapterInventory) -> str:
    variant_rows = "\n".join(
        "<tr>"
        f"<td>{_variant_selector(variant)}</td>"
        f"<td>{escape(str(variant.branch_id or '—'))}</td>"
        f"<td>{'buildable' if variant.is_buildable else 'non-buildable'}</td>"
        "</tr>"
        for variant in inventory.variants
    ) or '<tr><td colspan="3">No variants found</td></tr>'
    warning_items = "\n".join(
        f"<li>{escape(warning.message)}"
        f" (logical: {escape(str(warning.logical_id))}, variant: {escape(str(warning.variant_id))})</li>"
        for warning in inventory.warnings
    ) or "<li>No warnings</li>"
    build_button = (
        '<button type="submit">Build selected EPUB</button>'
        if inventory.buildable_variants
        else '<p class="bad">No buildable variants available.</p>'
    )
    return f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Inventory preview</title>
  <style>body{{font-family:system-ui,sans-serif;max-width:960px;margin:40px auto;padding:0 16px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px;text-align:left}}.ok{{color:#176b32}}.bad{{color:#9f1d1d}}</style>
</head>
<body>
  <main>
    <h1>Inventory preview</h1>
    <dl>
      <dt>Canonical URL</dt><dd><a href="{escape(title.canonical_url)}">{escape(title.canonical_url)}</a></dd>
      <dt>Slug</dt><dd>{escape(title.slug)}</dd>
      <dt>Logical chapters</dt><dd>{len(inventory.logical_chapters)}</dd>
      <dt>Variants</dt><dd>{len(inventory.variants)}</dd>
      <dt>Buildable variants</dt><dd>{len(inventory.buildable_variants)}</dd>
    </dl>
    <h2>Variants</h2>
    <form action="/build" method="post">
      <input type="hidden" name="title_url" value="{escape(title.canonical_url, quote=True)}">
      <table>
        <thead><tr><th>display_label</th><th>branch_id</th><th>status</th></tr></thead>
        <tbody>{variant_rows}</tbody>
      </table>
      {build_button}
    </form>
    <h2>Warnings</h2>
    <ul>{warning_items}</ul>
  </main>
</body>
</html>
"""


def _variant_selector(variant: ChapterBranchVariant) -> str:
    label = escape(variant.display_label)
    if not variant.is_buildable:
        return f"{label} <span class=\"bad\" aria-label=\"not selectable\">not selectable</span>"
    value = escape(_variant_form_value(variant), quote=True)
    return (
        "<label>"
        f'<input type="checkbox" name="selected_variant" value="{value}"> '
        f"{label}"
        "</label>"
    )
