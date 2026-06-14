from __future__ import annotations

import json
import re
from html import escape
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Form, Query
from fastapi.responses import HTMLResponse, Response

from ranobelib_epub.build import build_selected_chapter_epub
from ranobelib_epub.epub import BookMetadata
from ranobelib_epub.images import HttpxImageAssetFetcher, ImageFetchLimits
from ranobelib_epub.inventory import ChapterInventory, fetch_chapter_inventory
from ranobelib_epub.inventory import ChapterBranchVariant, HttpxInventoryTransport
from ranobelib_epub.ranobelib import RanobeLibTitleUrl, parse_title_url

app = FastAPI(title="RanobeLib EPUB Builder")
MAX_SYNC_BUILD_VARIANTS = 100
_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


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
        self,
        title: RanobeLibTitleUrl,
        metadata: BookMetadata,
        variants: tuple[ChapterBranchVariant, ...],
        *,
        include_images: bool = False,
    ) -> bytes: ...


class RanobeLibBuildService:
    def __init__(self, transport: HttpxInventoryTransport | None = None) -> None:
        self._transport = transport or HttpxInventoryTransport()

    def build(
        self,
        title: RanobeLibTitleUrl,
        metadata: BookMetadata,
        variants: tuple[ChapterBranchVariant, ...],
        *,
        include_images: bool = False,
    ) -> bytes:
        result = build_selected_chapter_epub(
            title.slug,
            metadata,
            variants,
            self._transport,
            image_fetcher=HttpxImageAssetFetcher() if include_images else None,
            image_limits=ImageFetchLimits() if include_images else None,
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
    book_title: Annotated[str | None, Form()] = None,
    author: Annotated[str | None, Form()] = None,
    translator: Annotated[str | None, Form()] = None,
    team: Annotated[str | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
    bulk_branch_id: Annotated[str | None, Form()] = None,
    volume_from: Annotated[str | None, Form()] = None,
    volume_to: Annotated[str | None, Form()] = None,
    chapter_from: Annotated[str | None, Form()] = None,
    chapter_to: Annotated[str | None, Form()] = None,
    include_images: Annotated[bool, Form()] = False,
    selection_mode: Annotated[str | None, Form()] = None,
    service: BuildService = Depends(get_build_service),
) -> Response:
    try:
        title = parse_title_url(title_url)
        metadata = _book_metadata_from_form(
            title,
            book_title=book_title,
            author=author,
            translator=translator,
            team=team,
            language=language,
        )
        variants = _selected_variants(
            selected_variant or [],
            bulk_variant or [],
            bulk_branch_id=bulk_branch_id,
            volume_from=volume_from,
            volume_to=volume_to,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
            selection_mode=selection_mode,
        )
    except ValueError as exc:
        return _error_page(str(exc), status_code=400)

    try:
        epub_bytes = service.build(title, metadata, variants, include_images=include_images)
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


def _book_metadata_from_form(
    title: RanobeLibTitleUrl,
    *,
    book_title: str | None,
    author: str | None,
    translator: str | None,
    team: str | None,
    language: str | None,
) -> BookMetadata:
    if book_title is None:
        normalized_title = title.slug
    else:
        normalized_title = _optional_text(book_title)
        if normalized_title is None:
            raise ValueError("Book title must not be blank")

    normalized_language = _optional_text(language) or "ru"
    if not _LANGUAGE_TAG.fullmatch(normalized_language):
        raise ValueError("Language must be a valid language tag")

    return BookMetadata(
        title=normalized_title,
        author=_optional_text(author),
        translator=_optional_text(translator),
        team=_optional_text(team),
        language=normalized_language.lower(),
        identifier=title.canonical_url,
    )


def _selected_variants(
    raw_variants: list[str],
    bulk_variants: list[str] | None = None,
    *,
    bulk_branch_id: str | None = None,
    volume_from: str | None = None,
    volume_to: str | None = None,
    chapter_from: str | None = None,
    chapter_to: str | None = None,
    selection_mode: str | None = None,
) -> tuple[ChapterBranchVariant, ...]:
    selected: tuple[ChapterBranchVariant, ...]
    mode = _optional_text(selection_mode)
    if mode not in {None, "checked", "range"}:
        raise ValueError("Selection mode is malformed")

    if mode == "checked":
        if not raw_variants:
            raise ValueError("Select at least one checked chapter variant")
        selected = _dedupe_variants(
            _parse_variant_values(raw_variants, source="Selected variant")
        )
    elif mode == "range":
        if not bulk_variants:
            raise ValueError("Select at least one buildable chapter variant")
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
        selected = _dedupe_variants(variants)
    elif raw_variants:
        selected = _dedupe_variants(_parse_variant_values(raw_variants, source="Selected variant"))
    elif bulk_variants:
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
        selected = _dedupe_variants(variants)
    else:
        raise ValueError("Select at least one buildable chapter variant")

    _enforce_sync_build_limit(selected)
    return selected


def _enforce_sync_build_limit(variants: tuple[ChapterBranchVariant, ...]) -> None:
    selected_count = len(variants)
    if selected_count > MAX_SYNC_BUILD_VARIANTS:
        raise ValueError(
            "Synchronous build selection contains "
            f"{selected_count} chapter variants, but the configured maximum is "
            f"{MAX_SYNC_BUILD_VARIANTS}. Use branch/range filters or split large titles "
            "into multiple EPUB builds."
        )


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
    branch_cards = _branch_cards(title, inventory)
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
  <style>
    :root {{ color-scheme: light; }}
    body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:1180px;margin:32px auto;padding:0 16px;line-height:1.45;background:#f7f7fb;color:#1f2937}}
    h1,h2,h3{{line-height:1.15}} .page-head,.card,.branch-card{{background:#fff;border:1px solid #d9deea;border-radius:18px;box-shadow:0 8px 24px rgba(15,23,42,.06)}}
    .page-head,.card{{padding:22px;margin-bottom:18px}} .summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:0}}
    .summary div{{background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:10px}} .summary dt{{font-size:.82rem;color:#64748b}} .summary dd{{margin:2px 0 0;font-weight:700}}
    .settings-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}} label{{display:block;font-weight:650}} input,select,button{{font:inherit;border-radius:10px;border:1px solid #bfc7d5;padding:9px 11px}} input[type="text"],input[type="url"],input:not([type]){{width:100%;box-sizing:border-box;margin-top:5px}} input[type="checkbox"]{{margin-right:8px}} button{{cursor:pointer;background:#243b63;color:#fff;border-color:#243b63;font-weight:700}} button.secondary{{background:#fff;color:#243b63}}
    .muted{{color:#64748b;font-size:.95rem}} .ok{{color:#176b32}} .bad{{color:#9f1d1d}} .branches{{display:grid;gap:18px}} .branch-card{{padding:0;overflow:hidden}} .branch-header{{padding:18px 20px;background:#eef4ff;border-bottom:1px solid #d9deea}} .branch-meta{{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}} .pill{{background:#fff;border:1px solid #cbd5e1;border-radius:999px;padding:4px 9px;font-size:.88rem}}
    .branch-body{{padding:18px 20px}} .range{{border:1px dashed #b6c2d6;border-radius:14px;padding:14px;margin-bottom:16px;background:#fbfdff}} .range-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}} .volume-group{{margin:16px 0}} .volume-title{{font-size:1rem;margin:0 0 8px}} table{{border-collapse:collapse;width:100%;background:#fff}} td,th{{border:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}} th{{background:#f8fafc}} .actions{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:14px}} .progress-note,.build-complete,.build-error{{display:none;margin-top:12px;padding:12px;border-radius:12px;border:1px solid #bfdbfe}} .progress-note{{background:#eff6ff}} .build-complete{{background:#ecfdf5;border-color:#bbf7d0}} .build-error{{background:#fef2f2;border-color:#fecaca}} .is-building .progress-note,.is-complete .build-complete,.has-build-error .build-error{{display:block}} .is-building button[type="submit"]{{opacity:.7;cursor:wait}} .bar{{height:8px;border-radius:999px;background:linear-gradient(90deg,#93c5fd,#dbeafe,#93c5fd);background-size:200% 100%;animation:indeterminate 1.2s linear infinite}} @keyframes indeterminate{{from{{background-position:200% 0}}to{{background-position:-200% 0}}}}
  </style>
</head>
<body>
  <main>
    <section class="page-head">
      <h1>Inventory preview</h1>
      <dl class="summary">
        <div><dt>Canonical URL</dt><dd><a href="{escape(title.canonical_url)}">{escape(title.canonical_url)}</a></dd></div>
        <div><dt>Slug</dt><dd>{escape(title.slug)}</dd></div>
        <div><dt>Logical chapters</dt><dd>{len(inventory.logical_chapters)}</dd></div>
        <div><dt>Variants</dt><dd>{len(inventory.variants)}</dd></div>
        <div><dt>Buildable variants</dt><dd>{len(inventory.buildable_variants)}</dd></div>
        <div><dt>Synchronous build limit</dt><dd>{MAX_SYNC_BUILD_VARIANTS} variants</dd></div>
      </dl>
    </section>

    <section class="card" aria-labelledby="settings-title">
      <h2 id="settings-title">Build settings</h2>
      <p class="muted">These EPUB metadata fields are copied into the branch build you submit. Current synchronous build limit: {MAX_SYNC_BUILD_VARIANTS} chapter variants per EPUB build; the server enforces this limit authoritatively.</p>
      <div class="settings-grid" id="build-settings">
        <label>Book title <input data-build-setting name="book_title" value="{escape(title.slug, quote=True)}" required></label>
        <label>Author <input data-build-setting name="author" placeholder="optional"></label>
        <label>Translator <input data-build-setting name="translator" placeholder="optional"></label>
        <label>Team <input data-build-setting name="team" placeholder="optional"></label>
        <label>Language <input data-build-setting name="language" value="ru" required></label>
        <label><input data-build-setting type="checkbox" name="include_images" value="true"> Include images</label>
      </div>
      <p class="muted">Images can make the build slower and the EPUB larger. They are fetched read-only during this build only, bounded by limits, not cached/stored.</p>
      <p class="muted">For larger titles, use branch/range filters or split the title into multiple EPUB files.</p>
    </section>

    <section class="branches" aria-labelledby="branches-title">
      <h2 id="branches-title">Branch cards</h2>
      {branch_cards}
    </section>

    <section class="card">
      <h2>Warnings</h2>
      <ul>{warning_items}</ul>
    </section>
  </main>
  <script>
  (() => {{
    const settings = [...document.querySelectorAll('[data-build-setting]')];
    const filenameFromDisposition = (header) => {{
      const fallback = 'ranobelib-title.epub';
      if (!header) return fallback;
      const utf8 = header.match(/filename\*=UTF-8''([^;]+)/i);
      if (utf8) return decodeURIComponent(utf8[1]).replace(/[\\/]/g, '_') || fallback;
      const ascii = header.match(/filename="?([^";]+)"?/i);
      return ascii ? ascii[1].replace(/[\\/]/g, '_') : fallback;
    }};
    const triggerDownload = (blob, filename) => {{
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = filename; link.style.display = 'none';
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }};
    document.querySelectorAll('form[data-branch-form]').forEach((form) => {{
      form.addEventListener('submit', async (event) => {{
        form.querySelectorAll('[data-mirrored-setting]').forEach((node) => node.remove());
        settings.forEach((source) => {{
          if (source.type === 'checkbox' && !source.checked) return;
          const hidden = document.createElement('input');
          hidden.type = 'hidden'; hidden.name = source.name; hidden.value = source.value;
          hidden.setAttribute('data-mirrored-setting', 'true'); form.appendChild(hidden);
        }});
        if (!window.fetch || !window.FormData || !window.URL) return;
        event.preventDefault();
        const submitter = event.submitter || form.querySelector('button[type="submit"]');
        const body = submitter ? new FormData(form, submitter) : new FormData(form);
        const originalText = submitter ? submitter.textContent : '';
        form.classList.remove('is-complete', 'has-build-error');
        if (submitter) {{ submitter.disabled = true; submitter.textContent = 'Building EPUB…'; }}
        form.classList.add('is-building');
        try {{
          const response = await fetch(form.action, {{ method: 'POST', body }});
          const contentType = response.headers.get('content-type') || '';
          if (!response.ok || !contentType.includes('application/epub+zip')) {{
            const message = response.ok ? 'Build failed: server did not return an EPUB.' : await response.text();
            throw new Error(message.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim() || 'Build failed.');
          }}
          const blob = await response.blob();
          triggerDownload(blob, filenameFromDisposition(response.headers.get('content-disposition')));
          form.classList.add('is-complete');
        }} catch (error) {{
          const target = form.querySelector('[data-build-error-message]');
          if (target) target.textContent = error.message || 'Build failed.';
          form.classList.add('has-build-error');
        }} finally {{
          form.classList.remove('is-building');
          if (submitter) {{ submitter.disabled = false; submitter.textContent = originalText; }}
        }}
      }});
      const update = () => {{
        const count = form.querySelectorAll('input[name="selected_variant"]:checked').length;
        form.querySelectorAll('[data-selected-count]').forEach((node) => node.textContent = String(count));
      }};
      form.addEventListener('change', update); update();
    }});
  }})();
  </script>
</body>
</html>
"""


def _branch_cards(title: RanobeLibTitleUrl, inventory: ChapterInventory) -> str:
    groups: dict[str, list[ChapterBranchVariant]] = {}
    for variant in inventory.buildable_variants:
        groups.setdefault(str(variant.branch_id), []).append(variant)
    if not groups:
        return '<article class="branch-card"><div class="branch-body"><p class="bad">No buildable variants available.</p></div></article>'
    cards = []
    for branch_id, variants in groups.items():
        cards.append(_branch_card(title, branch_id, tuple(variants), inventory.variants))
    return "\n".join(cards)


def _branch_card(
    title: RanobeLibTitleUrl,
    branch_id: str,
    variants: tuple[ChapterBranchVariant, ...],
    all_variants: tuple[ChapterBranchVariant, ...],
) -> str:
    label = _branch_label(variants[0])
    vol_min, vol_max = _number_bounds([variant.volume for variant in variants])
    ch_min, ch_max = _number_bounds([variant.number for variant in variants])
    hidden_bulk = "\n".join(
        f'<input type="hidden" name="bulk_variant" value="{escape(_variant_form_value(variant), quote=True)}">'
        for variant in variants
    )
    volumes = _volume_sections(variants)
    non_buildable = _non_buildable_for_branch(branch_id, all_variants)
    range_hint = f"Volume {vol_min or 'min'}–{vol_max or 'max'}, chapter {ch_min or 'min'}–{ch_max or 'max'}"
    return f"""
      <article class="branch-card">
        <form action="/build" method="post" data-branch-form data-branch-size="{len(variants)}">
          <input type="hidden" name="title_url" value="{escape(title.canonical_url, quote=True)}">
          <input type="hidden" name="book_title" value="{escape(title.slug, quote=True)}">
          <input type="hidden" name="language" value="ru">
          <input type="hidden" name="bulk_branch_id" value="{escape(branch_id, quote=True)}">
          {hidden_bulk}
          <header class="branch-header">
            <h3>{escape(label)}</h3>
            <div class="branch-meta">
              <span class="pill">Branch ID: {escape(branch_id)}</span>
              <span class="pill">Buildable chapters: {len(variants)}</span>
              <span class="pill">Volume range: {escape(str(vol_min or '—'))}–{escape(str(vol_max or '—'))}</span>
              <span class="pill">Chapter range: {escape(str(ch_min or '—'))}–{escape(str(ch_max or '—'))}</span>
            </div>
          </header>
          <div class="branch-body">
            <fieldset class="range">
              <legend>Apply range inside this branch</legend>
              <p class="muted">Range filters apply only to this branch card. Example context: {escape(range_hint)}.</p>
              <div class="range-grid">
                <label>Volume from <input name="volume_from" inputmode="decimal" placeholder="{escape(str(vol_min or 'from'), quote=True)}"></label>
                <label>Volume to <input name="volume_to" inputmode="decimal" placeholder="{escape(str(vol_max or 'to'), quote=True)}"></label>
                <label>Chapter from <input name="chapter_from" inputmode="decimal" placeholder="{escape(str(ch_min or 'from'), quote=True)}"></label>
                <label>Chapter to <input name="chapter_to" inputmode="decimal" placeholder="{escape(str(ch_max or 'to'), quote=True)}"></label>
              </div>
            </fieldset>
            {volumes}
            {non_buildable}
            <div class="actions">
              <button type="submit" name="selection_mode" value="range">Build this branch/range</button>
              <button class="secondary" type="submit" name="selection_mode" value="checked">Build checked chapters</button>
              <span class="muted"><span data-selected-count>0</span> checked; images on/off follows Build settings; sync limit {MAX_SYNC_BUILD_VARIANTS}.</span>
            </div>
            <div class="progress-note" role="status" aria-live="polite" data-build-active-state>
              <div class="bar" aria-hidden="true"></div>
              <p><strong>Building EPUB…</strong></p>
              <p>Fetching selected chapters and optional images, then packaging EPUB. Keep this tab open.</p>
              <p class="muted">Selected chapter count is shown above when JavaScript is available; this branch has {len(variants)} buildable chapters, images follow the toggle, sync limit {MAX_SYNC_BUILD_VARIANTS}.</p>
            </div>
            <div class="build-complete" role="status" aria-live="polite" data-build-complete-state>
              <p><strong>Download ready / Download started.</strong></p>
            </div>
            <div class="build-error" role="alert" data-build-error-state>
              <p><strong>Build failed.</strong> <span data-build-error-message>Please review the request and try again.</span></p>
            </div>
          </div>
        </form>
      </article>
    """


def _volume_sections(variants: tuple[ChapterBranchVariant, ...]) -> str:
    by_volume: dict[str, list[ChapterBranchVariant]] = {}
    for variant in variants:
        by_volume.setdefault(str(variant.volume), []).append(variant)
    sections = []
    for volume, volume_variants in by_volume.items():
        rows = "\n".join(_chapter_row(variant) for variant in volume_variants)
        sections.append(f'<section class="volume-group"><h4 class="volume-title">Volume {escape(volume)}</h4><table><thead><tr><th>Select</th><th>Volume</th><th>Chapter</th><th>Title</th></tr></thead><tbody>{rows}</tbody></table></section>')
    return "\n".join(sections)


def _chapter_row(variant: ChapterBranchVariant) -> str:
    value = escape(_variant_form_value(variant), quote=True)
    return f'<tr><td><label><input type="checkbox" name="selected_variant" value="{value}"> Build</label></td><td>{escape(str(variant.volume))}</td><td>{escape(str(variant.number))}</td><td>{escape(variant.chapter_title or "—")}</td></tr>'


def _non_buildable_for_branch(branch_id: str, variants: tuple[ChapterBranchVariant, ...]) -> str:
    rows = [variant for variant in variants if not variant.is_buildable and (variant.branch_id is None or str(variant.branch_id) == branch_id)]
    if not rows:
        return ""
    items = "\n".join(f'<li>{escape(variant.display_label)} <span class="bad">not selectable / non-buildable</span></li>' for variant in rows)
    return f'<details><summary>Non-buildable variants visible separately</summary><ul>{items}</ul></details>'


def _branch_label(variant: ChapterBranchVariant) -> str:
    return variant.branch_team or variant.branch_user or f"Branch {variant.branch_id}"


def _number_bounds(values: list[str | None]) -> tuple[str | None, str | None]:
    parsed: list[tuple[float, str]] = []
    for value in values:
        number = _parse_number(value)
        if value is not None and number is not None:
            parsed.append((number, value))
    if not parsed:
        return None, None
    return min(parsed)[1], max(parsed)[1]


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
