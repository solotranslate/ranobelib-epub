import pytest

from ranobelib_epub.ranobelib import RanobeLibTitleUrl, parse_title_url


def test_parse_title_url_with_locale() -> None:
    parsed = parse_title_url("https://ranobelib.me/ru/book/12345--title-slug?from=ignored#top")

    assert parsed == RanobeLibTitleUrl(title_id=12345, slug="title-slug", locale="ru")
    assert parsed.canonical_url == "https://ranobelib.me/ru/book/12345--title-slug"


def test_parse_title_url_without_locale() -> None:
    parsed = parse_title_url("https://www.ranobelib.me/book/987--another-title")

    assert parsed == RanobeLibTitleUrl(title_id=987, slug="another-title", locale=None)
    assert parsed.canonical_url == "https://ranobelib.me/book/987--another-title"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://ranobelib.me/ru/book/12345--title-slug",
        "https://example.com/ru/book/12345--title-slug",
        "https://ranobelib.me/ru/manga/12345--title-slug",
        "https://ranobelib.me/ru/book/12345--title-slug/v1/c1",
        "https://ranobelib.me/rus/book/12345--title-slug",
        "https://ranobelib.me/ru/book/not-a-number--title-slug",
        "https://ranobelib.me/ru/book/12345",
        "https://ranobelib.me/ru/book/12345--",
    ],
)
def test_parse_title_url_rejects_non_title_urls(url: str) -> None:
    with pytest.raises(ValueError):
        parse_title_url(url)
