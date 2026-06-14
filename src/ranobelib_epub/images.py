from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol
from urllib.parse import urljoin, urlparse

import httpx

from ranobelib_epub.content import (
    Blockquote,
    ChapterBlock,
    ChapterList,
    Image,
    NormalizedChapter,
)
from ranobelib_epub.inventory import RANOBELIB_API_BASE_URL, _public_headers

_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@dataclass(frozen=True, slots=True)
class ImageFetchLimits:
    """Bounded safety limits for optional read-only image embedding."""

    max_image_count: int = 50
    max_bytes_per_image: int = 5 * 1024 * 1024
    max_total_image_bytes: int = 25 * 1024 * 1024
    timeout: float = 10.0
    allowed_content_types: frozenset[str] = frozenset(_ALLOWED_IMAGE_TYPES)

    def __post_init__(self) -> None:
        if self.max_image_count < 0:
            raise ValueError("max_image_count must not be negative")
        if self.max_bytes_per_image < 1:
            raise ValueError("max_bytes_per_image must be positive")
        if self.max_total_image_bytes < 1:
            raise ValueError("max_total_image_bytes must be positive")
        if self.timeout <= 0:
            raise ValueError("timeout must be finite and positive")


@dataclass(frozen=True, slots=True)
class ImageAsset:
    """In-memory EPUB image asset fetched from a public source URL."""

    source_url: str
    content: bytes
    media_type: str
    file_name: str


class ImageAssetFetcher(Protocol):
    """Read-only image fetcher abstraction for opt-in EPUB embedding."""

    def fetch_image(self, url: str, limits: ImageFetchLimits) -> tuple[bytes, str]: ...


@dataclass(frozen=True, slots=True)
class HttpxImageAssetFetcher:
    """HTTP GET-only image fetcher without auth, cookies, or session headers."""

    headers: dict[str, str] | None = None

    def fetch_image(self, url: str, limits: ImageFetchLimits) -> tuple[bytes, str]:
        safe_headers = _public_headers(self.headers)
        with httpx.stream("GET", url, headers=safe_headers, timeout=limits.timeout) as response:
            response.raise_for_status()
            media_type = _clean_media_type(response.headers.get("content-type"))
            if media_type not in limits.allowed_content_types:
                raise ValueError(f"Unsupported image content type: {media_type or 'missing'}")
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > limits.max_bytes_per_image:
                raise ValueError("Image exceeds max bytes per image")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > limits.max_bytes_per_image:
                    raise ValueError("Image exceeds max bytes per image")
                chunks.append(chunk)
        return b"".join(chunks), media_type


def collect_image_assets(
    chapters: Iterable[NormalizedChapter],
    fetcher: ImageAssetFetcher,
    limits: ImageFetchLimits | None = None,
) -> tuple[dict[str, ImageAsset], tuple[str, ...]]:
    """Fetch bounded in-memory image assets referenced by normalized image blocks."""

    active_limits = limits or ImageFetchLimits()
    assets: dict[str, ImageAsset] = {}
    warnings: list[str] = []
    total_bytes = 0
    next_index = 1

    for image in _iter_images(chapters):
        source_url = image_source_url(image)
        image_name = image.name or image.alt or source_url or "unknown image"
        if not source_url:
            warnings.append(
                f"Image block {image_name!r} has no supported source URL; image skipped"
            )
            continue
        if source_url in assets:
            continue
        if len(assets) >= active_limits.max_image_count:
            warnings.append("Image limit reached; image skipped")
            continue
        try:
            content, media_type = fetcher.fetch_image(source_url, active_limits)
        except Exception as exc:  # noqa: BLE001 - preserve non-strict build behavior.
            warnings.append(f"Image block {image_name!r} skipped: {exc}")
            continue
        if media_type not in active_limits.allowed_content_types:
            warnings.append(f"Image block {image_name!r} skipped: unsupported content type")
            continue
        if len(content) > active_limits.max_bytes_per_image:
            warnings.append(f"Image block {image_name!r} skipped: image is too large")
            continue
        if total_bytes + len(content) > active_limits.max_total_image_bytes:
            warnings.append(f"Image block {image_name!r} skipped: total image byte limit exceeded")
            continue
        file_name = f"images/image-{next_index:04d}{_extension_for(media_type)}"
        assets[source_url] = ImageAsset(source_url, content, media_type, file_name)
        total_bytes += len(content)
        next_index += 1

    return assets, tuple(warnings)


def image_source_url(image: Image) -> str | None:
    url = image.attachment.url if image.attachment and image.attachment.url else image.src
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    if not parsed.scheme and not parsed.netloc and url.startswith("/") and not url.startswith("//"):
        return urljoin(f"{RANOBELIB_API_BASE_URL.rstrip('/')}/", url.lstrip("/"))
    return None


def _iter_images(chapters: Iterable[NormalizedChapter]) -> Iterable[Image]:
    for chapter in chapters:
        yield from _iter_block_images(chapter.blocks)


def _iter_block_images(blocks: tuple[ChapterBlock, ...]) -> Iterable[Image]:
    for block in blocks:
        if isinstance(block, Image):
            yield block
        elif isinstance(block, ChapterList):
            for item in block.items:
                yield from _iter_block_images(item.blocks)
        elif isinstance(block, Blockquote):
            yield from _iter_block_images(block.blocks)


def _clean_media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _extension_for(media_type: str) -> str:
    return _ALLOWED_IMAGE_TYPES.get(media_type, ".bin")
