from __future__ import annotations

import json
import re
from html import escape
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ranobelib_epub.build import build_selected_chapter_epub
from ranobelib_epub.epub import BookMetadata
from ranobelib_epub.images import HttpxImageAssetFetcher, ImageFetchLimits
from ranobelib_epub.inventory import ChapterInventory, fetch_chapter_inventory
from ranobelib_epub.inventory import ChapterBranchVariant, HttpxInventoryTransport
from ranobelib_epub.jobs import BuildJobManager, BuildJobRequest
from ranobelib_epub.ranobelib import RanobeLibTitleUrl, parse_title_url
from ranobelib_epub.title_detail import (
    HttpxTitleDetailTransport,
    TitleDetailMetadata,
    fallback_title_detail,
    fetch_title_detail,
)

app = FastAPI(title="Сборщик EPUB для RanobeLib")
MAX_SYNC_BUILD_VARIANTS = 100
_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
BUILD_JOBS = BuildJobManager(max_active_jobs=1)


class InventoryService(Protocol):
    def fetch(self, title: RanobeLibTitleUrl) -> ChapterInventory: ...


class TitleDetailService(Protocol):
    def fetch(self, title: RanobeLibTitleUrl) -> TitleDetailMetadata: ...


class RanobeLibInventoryService:
    def __init__(self, transport: HttpxInventoryTransport | None = None) -> None:
        self._transport = transport or HttpxInventoryTransport()

    def fetch(self, title: RanobeLibTitleUrl) -> ChapterInventory:
        return fetch_chapter_inventory(title.slug, self._transport)


def get_inventory_service() -> InventoryService:
    return RanobeLibInventoryService()


class RanobeLibTitleDetailService:
    def __init__(self, transport: HttpxTitleDetailTransport | None = None) -> None:
        self._transport = transport or HttpxTitleDetailTransport()

    def fetch(self, title: RanobeLibTitleUrl) -> TitleDetailMetadata:
        return fetch_title_detail(title, self._transport)


def get_title_detail_service() -> TitleDetailService:
    return RanobeLibTitleDetailService()


class BuildService(Protocol):
    def build(
        self,
        title: RanobeLibTitleUrl,
        metadata: BookMetadata,
        variants: tuple[ChapterBranchVariant, ...],
        *,
        include_images: bool = False,
        progress_callback: Any | None = None,
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
        progress_callback: Any | None = None,
    ) -> bytes:
        result = build_selected_chapter_epub(
            title.slug,
            metadata,
            variants,
            self._transport,
            image_fetcher=HttpxImageAssetFetcher() if include_images else None,
            image_limits=ImageFetchLimits() if include_images else None,
            progress_callback=progress_callback,
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
  <title>Сборщик EPUB для RanobeLib</title>
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
    <h1>Сборщик EPUB для RanobeLib</h1>
    <p class="muted">
      Вставьте публичную ссылку на тайтл RanobeLib (/book/ или /manga/), чтобы посмотреть
      предпросмотр доступных глав и веток перед сборкой EPUB (без изменений на RanobeLib).
    </p>

    <form action="/inventory" method="get">
      <label for="title_url">Ссылка на тайтл RanobeLib</label>
      <input id="title_url" name="title_url" placeholder="https://ranobelib.me/ru/book/12345--title-slug" required>
      <button type="submit">Показать список глав</button>
    </form>
  </main>
</body>
</html>
"""


@app.get("/inventory", response_class=HTMLResponse, response_model=None)
def inventory_preview(
    title_url: str = Query(..., min_length=1),
    service: InventoryService = Depends(get_inventory_service),
    title_detail_service: TitleDetailService = Depends(get_title_detail_service),
) -> HTMLResponse:
    try:
        title = parse_title_url(title_url)
    except ValueError as exc:
        return _error_page(str(exc), status_code=400)

    try:
        inventory = service.fetch(title)
    except ValueError as exc:
        return _error_page(str(exc), status_code=400)

    try:
        title_detail = title_detail_service.fetch(title)
    except Exception:
        title_detail = fallback_title_detail(title.slug)

    return HTMLResponse(_inventory_page(title, inventory, title_detail))


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
        epub_bytes = service.build(
            title, metadata, variants, include_images=include_images
        )
    except ValueError as exc:
        return _error_page(str(exc), status_code=400)

    filename = _epub_filename(title)
    return Response(
        content=epub_bytes,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/build-jobs", response_class=JSONResponse, response_model=None)
def start_build_job(
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
) -> JSONResponse:
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
        job_id = BUILD_JOBS.start(
            BuildJobRequest(
                title=title,
                metadata=metadata,
                variants=variants,
                include_images=include_images,
                filename=_epub_filename(title),
            ),
            service,
        )
    except RuntimeError as exc:
        return JSONResponse({"message": str(exc)}, status_code=429)
    except ValueError as exc:
        return JSONResponse({"message": str(exc)}, status_code=400)
    return JSONResponse({"job_id": job_id}, status_code=202)


@app.get("/build-jobs/{job_id}", response_class=JSONResponse, response_model=None)
def build_job_status(job_id: str) -> JSONResponse:
    job = BUILD_JOBS.get(job_id)
    if job is None:
        return JSONResponse(
            {"message": "Задача сборки не найдена или устарела."}, status_code=404
        )
    return JSONResponse(job.public_dict())


@app.get("/build-jobs/{job_id}/download", response_class=Response, response_model=None)
def download_build_job(job_id: str) -> Response:
    job = BUILD_JOBS.get(job_id)
    if job is None:
        return JSONResponse(
            {"message": "Задача сборки не найдена или устарела."}, status_code=404
        )
    if job.status == "failed":
        return JSONResponse(
            {"message": job.error or "Сборка не удалась."}, status_code=409
        )
    if job.status != "ready" or job.epub_bytes is None:
        return JSONResponse({"message": "Файл сборки ещё не готов."}, status_code=409)
    return Response(
        content=job.epub_bytes,
        media_type="application/epub+zip",
        headers={
            "Content-Disposition": f'attachment; filename="{job.filename or "ranobelib-title.epub"}"'
        },
    )


def _error_page(message: str, *, status_code: int) -> HTMLResponse:
    html = f"""
<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><title>Ошибка предпросмотра</title></head>
<body>
  <main>
    <h1>Ошибка предпросмотра</h1>
    <p>{escape(message)}</p>
    <p><a href="/">Вернуться к форме</a></p>
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
            raise ValueError("Название книги не должно быть пустым")

    normalized_language = _optional_text(language) or "ru"
    if not _LANGUAGE_TAG.fullmatch(normalized_language):
        raise ValueError("Язык должен быть корректным языковым тегом")

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
        raise ValueError("Некорректный режим выбора глав")

    if mode == "checked":
        if not raw_variants:
            raise ValueError("Отметьте хотя бы одну главу для сборки")
        selected = _dedupe_variants(
            _parse_variant_values(raw_variants, source="Выбранная глава")
        )
    elif mode == "range":
        if not bulk_variants:
            raise ValueError("Выберите хотя бы одну доступную для сборки главу")
        candidates = _parse_variant_values(bulk_variants, source="Глава из диапазона")
        variants = _filter_bulk_variants(
            candidates,
            bulk_branch_id=bulk_branch_id,
            volume_from=volume_from,
            volume_to=volume_to,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
        )
        if not variants:
            raise ValueError("Выбранный диапазон не содержит доступных для сборки глав")
        selected = _dedupe_variants(variants)
    elif raw_variants:
        selected = _dedupe_variants(
            _parse_variant_values(raw_variants, source="Выбранная глава")
        )
    elif bulk_variants:
        candidates = _parse_variant_values(bulk_variants, source="Глава из диапазона")
        variants = _filter_bulk_variants(
            candidates,
            bulk_branch_id=bulk_branch_id,
            volume_from=volume_from,
            volume_to=volume_to,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
        )
        if not variants:
            raise ValueError("Выбранный диапазон не содержит доступных для сборки глав")
        selected = _dedupe_variants(variants)
    else:
        raise ValueError("Выберите хотя бы одну доступную для сборки главу")

    _enforce_sync_build_limit(selected)
    return selected


def _enforce_sync_build_limit(variants: tuple[ChapterBranchVariant, ...]) -> None:
    selected_count = len(variants)
    if selected_count > MAX_SYNC_BUILD_VARIANTS:
        raise ValueError(
            "В синхронную сборку выбрано "
            f"{selected_count} вариантов глав, но настроенный максимум — "
            f"{MAX_SYNC_BUILD_VARIANTS}. Используйте фильтры ветки/диапазона "
            "или разделите большой тайтл на несколько EPUB."
        )


def _parse_variant_values(
    raw_variants: list[str], *, source: str
) -> tuple[ChapterBranchVariant, ...]:
    variants: list[ChapterBranchVariant] = []
    for index, raw_variant in enumerate(raw_variants, start=1):
        try:
            payload = json.loads(raw_variant)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{source} на позиции {index} содержит некорректные данные"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"{source} на позиции {index} содержит некорректные данные"
            )

        variant = _variant_from_form_payload(payload, index, source=source)
        if not variant.is_buildable:
            raise ValueError(f"{source} на позиции {index} недоступна для сборки")
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
    vol_min = _optional_number(volume_from, "Том от")
    vol_max = _optional_number(volume_to, "Том до")
    ch_min = _optional_number(chapter_from, "Глава от")
    ch_max = _optional_number(chapter_to, "Глава до")
    if vol_min is not None and vol_max is not None and vol_min > vol_max:
        raise ValueError(
            "Начало диапазона томов должно быть меньше или равно концу диапазона"
        )
    if ch_min is not None and ch_max is not None and ch_min > ch_max:
        raise ValueError(
            "Начало диапазона глав должно быть меньше или равно концу диапазона"
        )

    selected: list[ChapterBranchVariant] = []
    for variant in variants:
        if branch and _branch_key(variant) != branch:
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
        raise ValueError(f"{label} должно быть числом")
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


def _dedupe_variants(
    variants: tuple[ChapterBranchVariant, ...],
) -> tuple[ChapterBranchVariant, ...]:
    deduped: list[ChapterBranchVariant] = []
    seen: set[tuple[str, str, str, str]] = set()
    for variant in variants:
        key = (
            str(variant.external_chapter_id),
            _branch_key(variant),
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
        "is_default_branch",
    }
    if any(key not in allowed for key in payload):
        raise ValueError(f"{source} на позиции {index} содержит некорректные данные")
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
        is_default_branch=bool(payload.get("is_default_branch")),
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
        "is_default_branch": variant.is_default_branch,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _epub_filename(title: RanobeLibTitleUrl) -> str:
    stem = _SAFE_FILENAME_CHARS.sub("-", title.slug).strip(".-")
    return f"{stem or 'ranobelib-title'}.epub"


def _inventory_page(
    title: RanobeLibTitleUrl,
    inventory: ChapterInventory,
    title_detail: TitleDetailMetadata,
) -> str:
    branch_cards = _branch_cards(title, inventory, title_detail)
    warnings_card = _warnings_card(inventory)
    cover_html = _title_cover_html(title_detail)
    title_pills = _title_pills(title_detail, inventory)
    return f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Собрать EPUB</title>
  <style>
    :root {{ color-scheme: light; }}
    body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:1180px;margin:32px auto;padding:0 16px;line-height:1.45;background:#f7f7fb;color:#1f2937}}
    h1,h2,h3{{line-height:1.15}} .title-card,.card,.branch-card{{background:#fff;border:1px solid #d9deea;border-radius:18px;box-shadow:0 8px 24px rgba(15,23,42,.06)}}
    .title-card,.card{{padding:22px;margin-bottom:18px}} .title-card{{display:flex;gap:18px;align-items:flex-start}} .title-cover{{width:112px;max-width:30vw;border-radius:12px;border:1px solid #d9deea;object-fit:cover;background:#f8fafc}} .title-meta{{min-width:0}} .title-meta h1{{margin:.1rem 0 .4rem}} .title-meta p{{margin:.25rem 0}}
    .settings-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}} label{{display:block;font-weight:650}} input,select,button{{font:inherit;border-radius:10px;border:1px solid #bfc7d5;padding:9px 11px}} input[type="text"],input[type="url"],input:not([type]){{width:100%;box-sizing:border-box;margin-top:5px}} input[type="checkbox"]{{margin-right:8px}} button{{cursor:pointer;background:#243b63;color:#fff;border-color:#243b63;font-weight:700}} button.secondary{{background:#fff;color:#243b63}}
    .muted{{color:#64748b;font-size:.95rem}} .ok{{color:#176b32}} .bad{{color:#9f1d1d}} .branches{{display:grid;gap:18px}} .branch-card{{padding:0;overflow:hidden}} .branch-header{{padding:18px 20px;background:#eef4ff;border-bottom:1px solid #d9deea}} .branch-meta,.title-pills{{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}} .pill{{background:#fff;border:1px solid #cbd5e1;border-radius:999px;padding:4px 9px;font-size:.88rem}}
    .branch-body{{padding:18px 20px}} .range,.quick-actions,.manual-selection{{border:1px dashed #b6c2d6;border-radius:14px;padding:14px;margin-bottom:16px;background:#fbfdff}} .quick-actions{{background:#f8fbff}} .manual-selection{{background:#fff}} .range-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}} .range-message{{margin:.75rem 0 0;font-weight:650}} .range-message.bad{{color:#9f1d1d}} .range-message.ok{{color:#176b32}} button:disabled{{opacity:.55;cursor:not-allowed}} .volume-group{{margin:16px 0}} .volume-title{{font-size:1rem;margin:0 0 8px}} table{{border-collapse:collapse;width:100%;background:#fff}} td,th{{border:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}} th{{background:#f8fafc}} .actions{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:14px}} .progress-note,.build-complete,.build-error{{display:none;margin-top:12px;padding:12px;border-radius:12px;border:1px solid #bfdbfe}} .progress-note{{background:#eff6ff}} .build-complete{{background:#ecfdf5;border-color:#bbf7d0}} .build-error{{background:#fef2f2;border-color:#fecaca}} .is-building .progress-note,.is-complete .build-complete,.has-build-error .build-error{{display:block}} .is-building button[type="submit"]{{opacity:.7;cursor:wait}} .bar{{height:8px;border-radius:999px;background:linear-gradient(90deg,#93c5fd,#dbeafe,#93c5fd);background-size:200% 100%;animation:indeterminate 1.2s linear infinite}} @keyframes indeterminate{{from{{background-position:200% 0}}to{{background-position:-200% 0}}}}
  </style>
</head>
<body>
  <main>
    <section class="title-card" aria-labelledby="title-name">
      {cover_html}
      <div class="title-meta">
        <h1 id="title-name">{escape(title_detail.display_title)}</h1>
        {_author_line(title_detail)}
        <p class="muted"><a href="{escape(title.canonical_url, quote=True)}">{escape(title.canonical_url)}</a></p>
        {title_pills}
      </div>
    </section>

    <section class="card" aria-labelledby="settings-title">
      <h2 id="settings-title">Настройки сборки</h2>
      <p class="muted">Эти поля метаданных EPUB будут добавлены в выбранную сборку. Текущий лимит синхронной сборки: {MAX_SYNC_BUILD_VARIANTS} вариантов глав на один EPUB; сервер проверяет этот лимит.</p>
      <div class="settings-grid" id="build-settings">
        <label>Название книги <input data-build-setting name="book_title" value="{escape(title_detail.display_title, quote=True)}" required></label>
        <label>Автор <input data-build-setting name="author" value="{escape(title_detail.author, quote=True)}"></label>
        <input data-build-setting type="hidden" name="language" value="ru">
        <input data-build-setting type="hidden" name="translator" value="">
        <input data-build-setting type="hidden" name="team" value="">
        <label><input data-build-setting type="checkbox" name="include_images" value="true" checked> Включить иллюстрации</label>
      </div>
      <p class="muted">Иллюстрации могут замедлить сборку и увеличить размер EPUB. Они загружаются только для этой сборки в read-only режиме, с лимитами, без кеширования и хранения.</p>
      <p class="muted">Для больших тайтлов используйте фильтры ветки/диапазона или разделите тайтл на несколько EPUB-файлов.</p>
    </section>

    <section class="branches" aria-labelledby="branches-title">
      <h2 id="branches-title">Ветки перевода</h2>
      {branch_cards}
    </section>

    {warnings_card}
  </main>
  <script>
  (() => {{
    const settings = [...document.querySelectorAll('[data-build-setting]')];
    const busyMessage = 'Сервис сейчас занят. Попробуйте чуть позже.';
    const filenameFromDisposition = (header) => {{
      const fallback = 'ranobelib-title.epub';
      if (!header) return fallback;
      const utf8 = header.match(/filename\\*=UTF-8''([^;]+)/i);
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
    const pollJob = async (jobId, form) => {{
      const statusText = form.querySelector('[data-build-status-message]');
      const statusCounts = form.querySelector('[data-build-status-counts]');
      while (true) {{
        const response = await fetch(`/build-jobs/${{encodeURIComponent(jobId)}}`, {{headers: {{'Accept': 'application/json'}}}});
        const payload = await response.json().catch(() => ({{message: 'Не удалось прочитать статус сборки.'}}));
        if (!response.ok) throw new Error(payload.message || 'Не удалось получить статус сборки.');
        if (statusText) statusText.textContent = payload.message || payload.status || 'Собираю EPUB…';
        const bits = [];
        if (payload.chapter_current !== undefined && payload.chapter_total !== undefined) bits.push(`Глава ${{payload.chapter_current}} / ${{payload.chapter_total}}`);
        if (payload.image_current !== undefined && payload.image_total !== undefined) bits.push(`Иллюстрация ${{payload.image_current}} / ${{payload.image_total}}`);
        else if (payload.image_current !== undefined) bits.push(`Иллюстраций загружено: ${{payload.image_current}}`);
        if (statusCounts) statusCounts.textContent = bits.join(' · ');
        if (payload.status === 'ready') return payload.download_url || `/build-jobs/${{encodeURIComponent(jobId)}}/download`;
        if (payload.status === 'failed') throw new Error(payload.error || payload.message || 'Сборка не удалась.');
        await new Promise((resolve) => setTimeout(resolve, 1200));
      }}
    }};
    document.querySelectorAll('form[data-branch-form]').forEach((form) => {{
      const maxBuild = Number(form.dataset.maxBuild || '100');
      const parseNumber = (value) => {{
        if (value === undefined || value === null || String(value).trim() === '') return null;
        const parsed = Number(String(value).trim().replace(',', '.'));
        return Number.isFinite(parsed) ? parsed : null;
      }};
      const inRange = (value, min, max) => {{
        if (min === null && max === null) return true;
        const parsed = parseNumber(value);
        if (parsed === null) return false;
        if (min !== null && parsed < min) return false;
        if (max !== null && parsed > max) return false;
        return true;
      }};
      const customFrom = form.querySelector('[data-custom-chapter-from]');
      const customTo = form.querySelector('[data-custom-chapter-to]');
      const customButton = form.querySelector('[data-custom-range-submit]');
      const rangeMessage = form.querySelector('[data-range-message]');
      const countRange = () => {{
        const from = parseNumber(customFrom && customFrom.value);
        const to = parseNumber(customTo && customTo.value);
        if (from !== null && to !== null && from > to) return 0;
        return [...form.querySelectorAll('input[name="bulk_variant"][data-bulk-variant]')]
          .filter((node) => inRange(node.dataset.chapterNumber, from, to))
          .filter((node) => inRange(node.dataset.volumeNumber, parseNumber(form.querySelector('[name="volume_from"]')?.value), parseNumber(form.querySelector('[name="volume_to"]')?.value)))
          .length;
      }};
      const updateRange = () => {{
        if (!rangeMessage || !customButton) return;
        const count = countRange();
        rangeMessage.classList.remove('ok', 'bad');
        if (count === 0) {{
          rangeMessage.textContent = 'В этом диапазоне нет доступных глав.';
          rangeMessage.classList.add('bad');
          customButton.disabled = true;
        }} else if (count > maxBuild) {{
          rangeMessage.textContent = `Выбрано ${{count}} глав — максимум ${{maxBuild}}. Разбейте диапазон на несколько EPUB.`;
          rangeMessage.classList.add('bad');
          customButton.disabled = true;
        }} else {{
          rangeMessage.textContent = `Будет собрано: ${{count}} глав`;
          rangeMessage.classList.add('ok');
          customButton.disabled = false;
        }}
      }};
      [customFrom, customTo, form.querySelector('[name="volume_from"]'), form.querySelector('[name="volume_to"]')].forEach((node) => {{ if (node) node.addEventListener('input', updateRange); }});
      updateRange();
      form.addEventListener('submit', async (event) => {{
        form.querySelectorAll('[data-mirrored-setting],[data-quick-range-field]').forEach((node) => node.remove());
        const quick = event.submitter && event.submitter.matches('[data-quick-range-submit]') ? event.submitter : null;
        if (quick) {{
          [['selection_mode', 'range'], ['chapter_from', quick.dataset.chapterFrom], ['chapter_to', quick.dataset.chapterTo], ['volume_from', quick.dataset.volumeFrom], ['volume_to', quick.dataset.volumeTo]].forEach(([name, value]) => {{
            if (value === undefined || value === null || value === '') return;
            const hidden = document.createElement('input');
            hidden.type = 'hidden'; hidden.name = name; hidden.value = value; hidden.setAttribute('data-quick-range-field', 'true'); form.appendChild(hidden);
          }});
        }}
        form.querySelectorAll('[data-mirrored-setting]').forEach((node) => node.remove());
        const includeImages = document.querySelector('[data-build-setting][name="include_images"]');
        form.querySelectorAll('[data-default-include-images]').forEach((node) => {{
          node.disabled = includeImages && !includeImages.checked;
        }});
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
        const readyLink = form.querySelector('[data-build-download-link]');
        if (readyLink) {{ readyLink.hidden = true; readyLink.removeAttribute('href'); }}
        if (submitter) {{ submitter.disabled = true; submitter.textContent = 'Собираю EPUB…'; }}
        form.classList.add('is-building');
        try {{
          const start = await fetch('/build-jobs', {{ method: 'POST', body, headers: {{'Accept': 'application/json'}} }});
          const payload = await start.json().catch(() => ({{message: 'Не удалось запустить сборку.'}}));
          if (start.status === 429 || start.status === 409) throw new Error(payload.message || busyMessage);
          if (!start.ok || !payload.job_id) throw new Error(payload.message || 'Не удалось запустить сборку.');
          const downloadUrl = await pollJob(payload.job_id, form);
          if (readyLink) {{ readyLink.href = downloadUrl; readyLink.hidden = false; }}
          const response = await fetch(downloadUrl, {{headers: {{'Accept': 'application/epub+zip'}}}});
          if (!response.ok) {{
            const errorPayload = await response.json().catch(() => ({{message: 'Не удалось скачать EPUB.'}}));
            throw new Error(errorPayload.message || 'Не удалось скачать EPUB.');
          }}
          triggerDownload(await response.blob(), filenameFromDisposition(response.headers.get('content-disposition')));
          form.classList.add('is-complete');
        }} catch (error) {{
          const target = form.querySelector('[data-build-error-message]');
          if (target) target.textContent = error.message || 'Сборка не удалась.';
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


def _warnings_card(inventory: ChapterInventory) -> str:
    if not inventory.warnings:
        return ""
    warning_items = "\n".join(
        f"<li>{escape(warning.message)}"
        f" (логическая глава: {escape(str(warning.logical_id))}, "
        f"вариант: {escape(str(warning.variant_id))})</li>"
        for warning in inventory.warnings
    )
    return f'<section class="card"><h2>Предупреждения</h2><ul>{warning_items}</ul></section>'


def _title_cover_html(title_detail: TitleDetailMetadata) -> str:
    if not title_detail.cover_url:
        return ""
    return (
        f'<img class="title-cover" src="{escape(title_detail.cover_url, quote=True)}" '
        f'alt="Обложка: {escape(title_detail.display_title, quote=True)}">'
    )


def _author_line(title_detail: TitleDetailMetadata) -> str:
    if not title_detail.author:
        return ""
    return f"<p><strong>Автор:</strong> {escape(title_detail.author)}</p>"


def _title_pills(title_detail: TitleDetailMetadata, inventory: ChapterInventory) -> str:
    pills = [f"Глав доступно: {len(inventory.buildable_variants)}"]
    if title_detail.uploaded_count is not None:
        pills.append(f"Загружено: {title_detail.uploaded_count}")
    if title_detail.status_label:
        pills.append(f"Статус: {title_detail.status_label}")
    if title_detail.type_label:
        pills.append(f"Тип: {title_detail.type_label}")
    return (
        '<div class="title-pills">'
        + "".join(f'<span class="pill">{escape(str(pill))}</span>' for pill in pills)
        + "</div>"
    )


def _branch_cards(
    title: RanobeLibTitleUrl,
    inventory: ChapterInventory,
    title_detail: TitleDetailMetadata,
) -> str:
    groups: dict[str, list[ChapterBranchVariant]] = {}
    for variant in inventory.buildable_variants:
        groups.setdefault(_branch_key(variant), []).append(variant)
    if not groups:
        return '<article class="branch-card"><div class="branch-body"><p class="bad">Нет доступных для сборки вариантов.</p></div></article>'
    cards = []
    for branch_id, variants in groups.items():
        cards.append(
            _branch_card(
                title, branch_id, tuple(variants), inventory.variants, title_detail
            )
        )
    return "\n".join(cards)


def _branch_card(
    title: RanobeLibTitleUrl,
    branch_id: str,
    variants: tuple[ChapterBranchVariant, ...],
    all_variants: tuple[ChapterBranchVariant, ...],
    title_detail: TitleDetailMetadata,
) -> str:
    label = _branch_label(variants[0])
    vol_min, vol_max = _number_bounds([variant.volume for variant in variants])
    ch_min, ch_max = _number_bounds([variant.number for variant in variants])
    volume_values = {
        _normalize_number_text(variant.volume)
        for variant in variants
        if variant.volume is not None
    }
    single_volume = len(volume_values) <= 1
    duplicate_chapters = _chapter_numbers_repeat_across_volumes(variants)
    show_volume_fields = (not single_volume) or duplicate_chapters
    default_volume = vol_min if single_volume else None
    chapter_from_default = ch_min or ""
    chapter_to_default = ch_max or ""
    hidden_bulk = "\n".join(
        '<input type="hidden" name="bulk_variant" data-bulk-variant '
        f'data-volume-number="{escape(str(variant.volume or ""), quote=True)}" '
        f'data-chapter-number="{escape(str(variant.number or ""), quote=True)}" '
        f'value="{escape(_variant_form_value(variant), quote=True)}">'
        for variant in variants
    )
    volume_inputs = _custom_volume_inputs(
        show_volume_fields, vol_min, vol_max, default_volume
    )
    quick_actions = _quick_actions(
        variants, vol_min, vol_max, default_volume, single_volume
    )
    volumes = _volume_sections(variants)
    non_buildable = _non_buildable_for_branch(branch_id, all_variants)
    return f"""
      <article class="branch-card">
        <form action="/build" method="post" data-branch-form data-branch-size="{len(variants)}" data-max-build="{MAX_SYNC_BUILD_VARIANTS}">
          <input type="hidden" name="title_url" value="{escape(title.canonical_url, quote=True)}">
          <input type="hidden" name="book_title" value="{escape(title_detail.display_title, quote=True)}">
          <input type="hidden" name="author" value="{escape(title_detail.author, quote=True)}">
          <input type="hidden" name="translator" value="">
          <input type="hidden" name="team" value="">
          <input type="hidden" name="language" value="ru">
          <input type="hidden" name="include_images" value="true" data-default-include-images>
          <input type="hidden" name="bulk_branch_id" value="{escape(branch_id, quote=True)}">
          {hidden_bulk}
          <header class="branch-header">
            <h3>{escape(label)}</h3>
            <div class="branch-meta">
              <span class="pill">ID ветки: {escape(branch_id)}</span>
              <span class="pill">Главы: {escape(_range_label(ch_min, ch_max))}</span>
              <span class="pill">{escape(_volume_summary(vol_min, vol_max))}</span>
              <span class="pill">Доступно для сборки: {len(variants)} глав</span>
            </div>
          </header>
          <div class="branch-body">
            {quick_actions}
            <fieldset class="range">
              <legend>Свой диапазон</legend>
              <div class="range-grid">
                {volume_inputs}
                <label>С главы <input name="chapter_from" data-custom-chapter-from inputmode="decimal" value="{escape(chapter_from_default, quote=True)}" placeholder="{escape(str(ch_min or '1'), quote=True)}"></label>
                <label>по главу <input name="chapter_to" data-custom-chapter-to inputmode="decimal" value="{escape(chapter_to_default, quote=True)}" placeholder="{escape(str(ch_max or MAX_SYNC_BUILD_VARIANTS), quote=True)}"></label>
              </div>
              <p class="range-message" data-range-message aria-live="polite">Будет собрано: {min(len(variants), MAX_SYNC_BUILD_VARIANTS)} глав</p>
              <div class="actions"><button type="submit" name="selection_mode" value="range" data-custom-range-submit>Собрать выбранный диапазон</button></div>
            </fieldset>
            <details class="manual-selection">
              <summary><strong>Ручной выбор глав</strong> · Показать список глав</summary>
              {volumes}
              {non_buildable}
              <div class="actions">
                <button class="secondary" type="submit" name="selection_mode" value="checked">Собрать отмеченные главы</button>
                <span class="muted"><span data-selected-count>0</span> отмечено; иллюстрации берутся из настроек сборки; лимит синхронной сборки {MAX_SYNC_BUILD_VARIANTS}.</span>
              </div>
            </details>
            <div class="progress-note" role="status" aria-live="polite" data-build-active-state>
              <div class="bar" aria-hidden="true"></div>
              <p><strong>Собираю EPUB…</strong> <span data-build-status-message>Задача поставлена в очередь; ожидаю начала сборки EPUB.</span></p>
              <p data-build-status-counts class="muted"></p>
              <p>Загружаю выбранные главы и иллюстрации, затем упаковываю EPUB. Не закрывайте эту вкладку.</p>
              <p class="muted">Количество выбранных глав показано выше, если доступен JavaScript; в этой ветке {len(variants)} глав доступно, иллюстрации зависят от переключателя, лимит синхронной сборки {MAX_SYNC_BUILD_VARIANTS}.</p>
            </div>
            <div class="build-complete" role="status" aria-live="polite" data-build-complete-state>
              <p><strong>Файл готов / скачивание началось.</strong> Если браузер заблокировал автоматическое скачивание, повторите сборку и сохраните файл через стандартный диалог загрузки.</p>
              <p><a data-build-download-link hidden>Скачать EPUB</a></p>
            </div>
            <div class="build-error" role="alert" data-build-error-state>
              <p><strong>Сборка не удалась.</strong> <span data-build-error-message>Проверьте параметры и попробуйте снова.</span></p>
            </div>
          </div>
        </form>
      </article>
    """


def _custom_volume_inputs(
    show_volume_fields: bool,
    vol_min: str | None,
    vol_max: str | None,
    default_volume: str | None,
) -> str:
    if show_volume_fields:
        return (
            f'<label>Том от <input name="volume_from" inputmode="decimal" value="{escape(str(vol_min or ""), quote=True)}" placeholder="{escape(str(vol_min or "от"), quote=True)}"></label>'
            f'<label>Том до <input name="volume_to" inputmode="decimal" value="{escape(str(vol_max or ""), quote=True)}" placeholder="{escape(str(vol_max or "до"), quote=True)}"></label>'
        )
    value = escape(str(default_volume or vol_min or ""), quote=True)
    return f'<input type="hidden" name="volume_from" value="{value}"><input type="hidden" name="volume_to" value="{value}">'


def _quick_actions(
    variants: tuple[ChapterBranchVariant, ...],
    vol_min: str | None,
    vol_max: str | None,
    default_volume: str | None,
    single_volume: bool,
) -> str:
    chunks = (
        [variants]
        if len(variants) <= MAX_SYNC_BUILD_VARIANTS
        else [
            variants[index : index + MAX_SYNC_BUILD_VARIANTS]
            for index in range(0, len(variants), MAX_SYNC_BUILD_VARIANTS)
        ]
    )
    buttons = []
    for chunk in chunks:
        first, last = chunk[0], chunk[-1]
        from_ch, to_ch = first.number or "", last.number or ""
        if len(variants) <= MAX_SYNC_BUILD_VARIANTS:
            label = "Собрать всю ветку"
        else:
            label = f"Собрать главы {_range_label(from_ch, to_ch)}"
        from_vol = default_volume if single_volume else (first.volume or vol_min or "")
        to_vol = default_volume if single_volume else (last.volume or vol_max or "")
        buttons.append(
            '<button type="submit" data-quick-range-submit name="selection_mode" value="range" '
            f'data-chapter-from="{escape(from_ch, quote=True)}" data-chapter-to="{escape(to_ch, quote=True)}" '
            f'data-volume-from="{escape(str(from_vol), quote=True)}" data-volume-to="{escape(str(to_vol), quote=True)}">'
            f"{escape(label)}</button>"
        )
    return (
        '<section class="quick-actions"><h4>Быстрые действия</h4><div class="actions">'
        + "".join(buttons)
        + "</div></section>"
    )


def _range_label(start: str | None, end: str | None) -> str:
    if start and end and start != end:
        return f"{start}–{end}"
    return start or end or "—"


def _volume_summary(start: str | None, end: str | None) -> str:
    label = _range_label(start, end)
    return f"Том: {label}" if start == end else f"Тома: {label}"


def _normalize_number_text(value: str | None) -> str:
    parsed = _parse_number(value)
    return f"{parsed:g}" if parsed is not None else str(value)


def _chapter_numbers_repeat_across_volumes(
    variants: tuple[ChapterBranchVariant, ...],
) -> bool:
    seen: dict[str, str] = {}
    for variant in variants:
        chapter = _normalize_number_text(variant.number)
        volume = _normalize_number_text(variant.volume)
        if chapter in seen and seen[chapter] != volume:
            return True
        seen[chapter] = volume
    return False


def _volume_sections(variants: tuple[ChapterBranchVariant, ...]) -> str:
    by_volume: dict[str, list[ChapterBranchVariant]] = {}
    for variant in variants:
        by_volume.setdefault(str(variant.volume), []).append(variant)
    sections = []
    for volume, volume_variants in by_volume.items():
        rows = "\n".join(_chapter_row(variant) for variant in volume_variants)
        sections.append(
            f'<section class="volume-group"><h4 class="volume-title">Том {escape(volume)}</h4><table><thead><tr><th>Выбор</th><th>Том</th><th>Глава</th><th>Название</th></tr></thead><tbody>{rows}</tbody></table></section>'
        )
    return "\n".join(sections)


def _chapter_row(variant: ChapterBranchVariant) -> str:
    value = escape(_variant_form_value(variant), quote=True)
    return f'<tr><td><label><input type="checkbox" name="selected_variant" value="{value}"> Собрать</label></td><td>{escape(str(variant.volume))}</td><td>{escape(str(variant.number))}</td><td>{escape(variant.chapter_title or "—")}</td></tr>'


def _non_buildable_for_branch(
    branch_id: str, variants: tuple[ChapterBranchVariant, ...]
) -> str:
    rows = [
        variant
        for variant in variants
        if not variant.is_buildable
        and (variant.branch_id is None or str(variant.branch_id) == branch_id)
    ]
    if not rows:
        return ""
    items = "\n".join(
        f'<li>{escape(variant.display_label)} <span class="bad">нельзя выбрать / недоступно для сборки</span></li>'
        for variant in rows
    )
    return f"<details><summary>Недоступные для сборки варианты показаны отдельно</summary><ul>{items}</ul></details>"


def _branch_label(variant: ChapterBranchVariant) -> str:
    if variant.branch_team or variant.branch_user:
        return variant.branch_team or variant.branch_user or ""
    return (
        "Основная ветка" if variant.is_default_branch else f"Ветка {variant.branch_id}"
    )


def _branch_key(variant: ChapterBranchVariant) -> str:
    return "default" if variant.is_default_branch else str(variant.branch_id)


def _number_bounds(values: list[str | None]) -> tuple[str | None, str | None]:
    parsed: list[tuple[float, str]] = []
    for value in values:
        number = _parse_number(value)
        if value is not None and number is not None:
            parsed.append((number, value))
    if not parsed:
        return None, None
    return min(parsed)[1], max(parsed)[1]


def _branch_options(
    variants: tuple[ChapterBranchVariant, ...],
) -> tuple[tuple[str, str], ...]:
    options: list[tuple[str, str]] = []
    seen: set[str] = set()
    for variant in variants:
        branch_id = _branch_key(variant)
        if branch_id in seen:
            continue
        seen.add(branch_id)
        name = variant.branch_team or variant.branch_user or f"Ветка {branch_id}"
        options.append((branch_id, f"{name} ({branch_id})"))
    return tuple(options)


def _variant_selector(variant: ChapterBranchVariant) -> str:
    label = escape(variant.display_label)
    if not variant.is_buildable:
        return f'{label} <span class="bad" aria-label="нельзя выбрать">нельзя выбрать</span>'
    value = escape(_variant_form_value(variant), quote=True)
    return (
        "<label>"
        f'<input type="checkbox" name="selected_variant" value="{value}"> '
        f"Собрать {label}"
        "</label>"
    )
