from __future__ import annotations

from html import escape
from typing import Protocol

from fastapi import Depends, FastAPI, Query
from fastapi.responses import HTMLResponse, Response

from ranobelib_epub.inventory import ChapterInventory, fetch_chapter_inventory
from ranobelib_epub.inventory import HttpxInventoryTransport
from ranobelib_epub.ranobelib import RanobeLibTitleUrl, parse_title_url

app = FastAPI(title="RanobeLib EPUB Builder")


class InventoryService(Protocol):
    def fetch(self, title: RanobeLibTitleUrl) -> ChapterInventory: ...


class RanobeLibInventoryService:
    def __init__(self, transport: HttpxInventoryTransport | None = None) -> None:
        self._transport = transport or HttpxInventoryTransport()

    def fetch(self, title: RanobeLibTitleUrl) -> ChapterInventory:
        return fetch_chapter_inventory(title.slug, self._transport)


def get_inventory_service() -> InventoryService:
    return RanobeLibInventoryService()


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


@app.get("/inventory", response_class=HTMLResponse)
def inventory_preview(
    title_url: str = Query(..., min_length=1),
    service: InventoryService = Depends(get_inventory_service),
) -> str | Response:
    try:
        title = parse_title_url(title_url)
    except ValueError as exc:
        return _error_page(str(exc), status_code=400)

    try:
        inventory = service.fetch(title)
    except ValueError as exc:
        return _error_page(str(exc), status_code=400)

    return _inventory_page(title, inventory)


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


def _inventory_page(title: RanobeLibTitleUrl, inventory: ChapterInventory) -> str:
    variant_rows = "\n".join(
        "<tr>"
        f"<td>{escape(variant.display_label)}</td>"
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
    <table>
      <thead><tr><th>display_label</th><th>branch_id</th><th>status</th></tr></thead>
      <tbody>{variant_rows}</tbody>
    </table>
    <h2>Warnings</h2>
    <ul>{warning_items}</ul>
  </main>
</body>
</html>
"""
