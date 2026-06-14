from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from ranobelib_epub.chapter_client import (
    ChapterContentResult as ChapterContentResult,
    fetch_chapter_content as fetch_chapter_content,
)
from ranobelib_epub.content import (
    Attachment as Attachment,
    Blockquote as Blockquote,
    ChapterBlock as ChapterBlock,
    ChapterList as ChapterList,
    Heading as Heading,
    HorizontalRule as HorizontalRule,
    Image as Image,
    ListItem as ListItem,
    NormalizedChapter as NormalizedChapter,
    Paragraph as Paragraph,
    TextMark as TextMark,
    TextRun as TextRun,
    normalize_chapter_payload as normalize_chapter_payload,
)


_ALLOWED_HOSTS = {"ranobelib.me", "www.ranobelib.me"}
_ALLOWED_SCHEMES = {"http", "https"}


@dataclass(frozen=True, slots=True)
class RanobeLibTitleUrl:
    """Parsed public RanobeLib title URL."""

    title_id: int
    slug: str
    locale: str | None
    path_kind: str = "book"

    @property
    def canonical_url(self) -> str:
        locale_prefix = f"/{self.locale}" if self.locale else ""
        return (
            f"https://ranobelib.me{locale_prefix}/{self.path_kind}/"
            f"{self.title_id}--{self.slug}"
        )


def parse_title_url(raw_url: str) -> RanobeLibTitleUrl:
    """Parse a public RanobeLib title URL without performing network requests.

    Supported examples:
    - https://ranobelib.me/ru/book/12345--title-slug
    - https://ranobelib.me/ru/manga/12345--title-slug
    - https://ranobelib.me/book/12345--title-slug
    - https://ranobelib.me/manga/12345--title-slug

    Query strings and fragments are ignored. Chapter and branch URLs are intentionally
    rejected because the MVP accepts only title pages.
    """

    url = raw_url.strip()
    if not url:
        raise ValueError("RanobeLib URL is empty")

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError("RanobeLib URL must use http or https")

    host = parsed.hostname.lower() if parsed.hostname else ""
    if host not in _ALLOWED_HOSTS:
        raise ValueError("RanobeLib URL host must be ranobelib.me")

    parts = [part for part in parsed.path.split("/") if part]
    locale: str | None = None
    if len(parts) == 3:
        locale, title_path_kind, title_segment = parts
        if len(locale) != 2 or not locale.isalpha():
            raise ValueError("RanobeLib locale segment must be a two-letter code")
    elif len(parts) == 2:
        title_path_kind, title_segment = parts
    else:
        raise ValueError("RanobeLib URL must point to a title page")

    if title_path_kind not in {"book", "manga"}:
        raise ValueError("RanobeLib URL must contain /book/ or /manga/")

    title_id_text, separator, slug = title_segment.partition("--")
    if separator != "--" or not title_id_text.isdecimal() or not slug:
        raise ValueError("RanobeLib title segment must look like 12345--title-slug")

    return RanobeLibTitleUrl(
        title_id=int(title_id_text), slug=slug, locale=locale, path_kind=title_path_kind
    )
