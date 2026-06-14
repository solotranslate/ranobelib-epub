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
    bulk_variant: Annotated[list[str] | None, Form()] = None,
    bulk_branch_id: Annotated[str | None, Form()] = None,
    volume_from: Annotated[str | None, Form()] = None,
    volume_to: Annotated[str | None, Form()] = None,
    chapter_from: Annotated[str | None, Form()] = None,
    chapter_to: Annotated[str | None, Form()] = None,
    service: BuildService = Depends(get_build_service),
) -> Response:
    try:
        title = parse_title_url(title_url)
        variants = _selected_variants(
            selected_variant or [],
            bulk_variant or [],
            bulk_branch_id=bulk_branch_id,
            volume_from=volume_from,
            volume_to=volume_to,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
        )
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


def _selected_variants(
    raw_variants: list[str],
    bulk_variants: list[str] | None = None,
    *,
    bulk_branch_id: str | None = None,
    volume_from: str | None = None,
    volume_to: str | None = None,
    chapter_from: str | None = None,
    chapter_to: str | None = None,
) -> tuple[ChapterBranchVariant, ...]:
    if raw_variants:
        return _dedupe_variants(_parse_variant_values(raw_variants, source="Selected variant"))
    if bulk_variants:
        candidates = _parse_variant_values(bulk_variants, source="Bulk variant")
        variants = _filter_bulk_variants(
            candidates,
            bulk_branch_id=bulk_branch_id,
            volume_from=volume_from,
            volume_to=volume_to,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
        )
        if not variants:
            raise ValueError("Bulk selection did not match any buildable chapter variants")
        return _dedupe_variants(variants)
    raise ValueError("Select at least one buildable chapter variant")


def _parse_variant_values(raw_variants: list[str], *, source: str) -> tuple[ChapterBranchVariant, ...]:
    variants: list[ChapterBranchVariant] = []
    for index, raw_variant in enumerate(raw_variants, start=1):
        try:
            payload = json.loads(raw_variant)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source} at position {index} is malformed") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{source} at position {index} is malformed")

        variant = _variant_from_form_payload(payload, index, source=source)
        if not variant.is_buildable:
            raise ValueError(f"{source} at position {index} is not buildable")
        variants.append(variant)
    return tuple(variants)


def _filter_bulk_variants(
    variants: tuple[ChapterBranchVariant, ...],
    *,
    bulk_branch_id: str | None,
    volume_from: str | None,
    volume_to: str | None,
    chapter_from: str | None,
    chapter_to: str | None,
) -> tuple[ChapterBranchVariant, ...]:
    branch = _optional_text(bulk_branch_id)
    vol_min = _optional_number(volume_from, "Volume from")
    vol_max = _optional_number(volume_to, "Volume to")
    ch_min = _optional_number(chapter_from, "Chapter from")
    ch_max = _optional_number(chapter_to, "Chapter to")
    if vol_min is not None and vol_max is not None and vol_min > vol_max:
        raise ValueError("Volume range start must be less than or equal to range end")
    if ch_min is not None and ch_max is not None and ch_min > ch_max:
        raise ValueError("Chapter range start must be less than or equal to range end")

    selected: list[ChapterBranchVariant] = []
    for variant in variants:
        if branch and str(variant.branch_id) != branch:
            continue
        if not _in_range(variant.volume, vol_min, vol_max):
            continue
        if not _in_range(variant.number, ch_min, ch_max):
            continue
        selected.append(variant)
    return tuple(selected)


def _in_range(value: str | None, minimum: float | None, maximum: float | None) -> bool:
    if minimum is None and maximum is None:
        return True
    parsed = _parse_number(value)
    if parsed is None:
        return False
    if minimum is not None and parsed < minimum:
        return False
    if maximum is not None and parsed > maximum:
        return False
    return True


def _optional_number(value: str | None, label: str) -> float | None:
    text = _optional_text(value)
    if text is None:
        return None
    parsed = _parse_number(text)
    if parsed is None:
        raise ValueError(f"{label} must be a number")
    return parsed


def _parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _dedupe_variants(variants: tuple[ChapterBranchVariant, ...]) -> tuple[ChapterBranchVariant, ...]:
    deduped: list[ChapterBranchVariant] = []
    seen: set[tuple[str, str, str, str]] = set()
    for variant in variants:
        key = (
            str(variant.external_chapter_id),
            str(variant.branch_id),
            str(variant.volume),
            str(variant.number),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return tuple(deduped)


def _variant_from_form_payload(
    payload: dict[str, Any], index: int, *, source: str = "Selected variant"
) -> ChapterBranchVariant:
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
        raise ValueError(f"{source} at position {index} is malformed")
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
        f"<td>{escape(str(variant.volume or '—'))}</td>"
        f"<td>{escape(str(variant.number or '—'))}</td>"
        f"<td>{'buildable' if variant.is_buildable else 'non-buildable'}</td>"
        "</tr>"
        for variant in inventory.variants
    ) or '<tr><td colspan="5">No variants found</td></tr>'
    bulk_values = "\n".join(
        f'<input type="hidden" name="bulk_variant" value="{escape(_variant_form_value(variant), quote=True)}">'
        for variant in inventory.buildable_variants
    )
    bulk_controls = _bulk_controls(inventory)
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
      {bulk_values}
      {bulk_controls}
      <table>
        <thead><tr><th>display_label</th><th>branch_id</th><th>volume</th><th>chapter</th><th>status</th></tr></thead>
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


def _bulk_controls(inventory: ChapterInventory) -> str:
    buildable = inventory.buildable_variants
    if not buildable:
        return ""
    branch_options = "\n".join(
        f'<option value="{escape(str(branch_id), quote=True)}">{escape(label)}</option>'
        for branch_id, label in _branch_options(buildable)
    )
    return f"""
      <fieldset>
        <legend>Bulk selection controls</legend>
        <p class="muted">If no manual checkbox is selected, build all buildable variants matching this branch and range.</p>
        <label for="bulk_branch_id">Branch/team</label>
        <select id="bulk_branch_id" name="bulk_branch_id">
          <option value="">All buildable branches</option>
          {branch_options}
        </select>
        <label>Volume range <input name="volume_from" inputmode="decimal" placeholder="from"> <input name="volume_to" inputmode="decimal" placeholder="to"></label>
        <label>Chapter range <input name="chapter_from" inputmode="decimal" placeholder="from"> <input name="chapter_to" inputmode="decimal" placeholder="to"></label>
      </fieldset>
    """


def _branch_options(variants: tuple[ChapterBranchVariant, ...]) -> tuple[tuple[str, str], ...]:
    options: list[tuple[str, str]] = []
    seen: set[str] = set()
    for variant in variants:
        branch_id = str(variant.branch_id)
        if branch_id in seen:
            continue
        seen.add(branch_id)
        name = variant.branch_team or variant.branch_user or f"Branch {branch_id}"
        options.append((branch_id, f"{name} ({branch_id})"))
    return tuple(options)


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
