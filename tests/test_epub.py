from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from ranobelib_epub.content import (
    Blockquote,
    ChapterList,
    Heading,
    HorizontalRule,
    Image,
    ListItem,
    NormalizedChapter,
    Paragraph,
    TextMark,
    TextRun,
    normalize_chapter_payload,
)
from ranobelib_epub.epub import BookMetadata, build_epub, build_epub_bytes, write_epub


def test_build_epub_bytes_uses_deterministic_toc_and_filenames() -> None:
    first = _chapter(
        1,
        "Free form !? title",
        "Volume 1 Chapter 1",
        (Paragraph((_run("Hello"),)),),
    )
    second = _chapter(2, "Named TOC", "Volume 1 Chapter 2", (Paragraph((_run("World"),)),))

    payload = build_epub_bytes(BookMetadata(title="Книга", author="Автор"), [first, second])

    with ZipFile(BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert "EPUB/chapters/chapter-0001.xhtml" in names
        assert "EPUB/chapters/chapter-0002.xhtml" in names
        assert not any("Free form" in name for name in names)
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8")
        assert "Free form !? title" in nav
        assert "Named TOC" in nav


def test_build_epub_nav_fallback_hides_default_secondary_number() -> None:
    chapter = normalize_chapter_payload(
        {
            "data": {
                "volume": "1",
                "number": "3",
                "number_secondary": "1",
                "content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Text"}],
                        }
                    ],
                },
            }
        }
    )

    payload = build_epub_bytes(BookMetadata(title="Book"), [chapter])

    with ZipFile(BytesIO(payload)) as archive:
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8")
        assert "Volume 1 Chapter 3" in nav
        assert "Volume 1 Chapter 3.1" not in nav


def test_build_epub_renders_supported_blocks_and_marks() -> None:
    chapter = _chapter(
        1,
        "TOC",
        "Generated",
        (
            Heading(2, (_run("Heading"),)),
            Paragraph(
                (
                    _run("bold", TextMark("bold")),
                    _run(" italic", TextMark("italic")),
                    _run(" underline", TextMark("underline")),
                    _run(" strike", TextMark("strike")),
                )
            ),
            Paragraph(()),
            ChapterList("ordered", (ListItem((Paragraph((_run("First"),)),)),)),
            ChapterList("bullet", (ListItem((Paragraph((_run("Bullet"),)),)),)),
            Blockquote((Paragraph((_run("Quote"),)),)),
            HorizontalRule(),
        ),
    )

    payload = build_epub_bytes(BookMetadata(title="Book"), [chapter])

    with ZipFile(BytesIO(payload)) as archive:
        html = archive.read("EPUB/chapters/chapter-0001.xhtml").decode("utf-8")
        assert "<h1>TOC</h1>" in html
        assert "<h2>Heading</h2>" in html
        assert "<strong>bold</strong>" in html
        assert "<em> italic</em>" in html
        assert "<u> underline</u>" in html
        assert "<s> strike</s>" in html
        assert "<p><br" in html
        assert "<ol>" in html
        assert "<ul>" in html
        assert "<blockquote>" in html
        assert "<hr" in html


def test_build_epub_skips_images_with_warning() -> None:
    chapter = _chapter(1, "TOC", "Generated", (Image(name="cover.png"),))

    with pytest.warns(UserWarning, match="Image block 'cover.png' skipped"):
        payload = build_epub_bytes(BookMetadata(title="Book"), [chapter])

    with ZipFile(BytesIO(payload)) as archive:
        html = archive.read("EPUB/chapters/chapter-0001.xhtml").decode("utf-8")
        assert "cover.png" not in html
        assert "<img" not in html


def test_write_epub_writes_only_explicit_target(tmp_path) -> None:
    target = tmp_path / "book.epub"
    chapter = _chapter(1, "TOC", "Generated", (Paragraph((_run("Text"),)),))

    assert build_epub(BookMetadata(title="Book"), [chapter], output=target) is None

    assert target.exists()
    with ZipFile(target) as archive:
        assert "EPUB/chapters/chapter-0001.xhtml" in archive.namelist()


def test_write_epub_accepts_file_like_object() -> None:
    buffer = BytesIO()
    chapter = _chapter(1, "TOC", "Generated", (Paragraph((_run("Text"),)),))

    write_epub(BookMetadata(title="Book"), [chapter], buffer)

    buffer.seek(0)
    with ZipFile(buffer) as archive:
        assert "EPUB/chapters/chapter-0001.xhtml" in archive.namelist()


def _run(text: str, *marks: TextMark) -> TextRun:
    return TextRun(text=text, marks=marks)


def _chapter(
    chapter_id: int,
    toc_title: str,
    generated_title: str,
    blocks: tuple,
) -> NormalizedChapter:
    return NormalizedChapter(
        id=chapter_id,
        volume=None,
        number=None,
        number_secondary=None,
        source_title=None,
        source_name=None,
        slug=None,
        branch_id=None,
        manga_id=None,
        generated_title=generated_title,
        toc_title=toc_title,
        blocks=blocks,
        attachments={},
    )


def test_build_epub_embeds_opt_in_image_assets() -> None:
    from ranobelib_epub.content import Attachment
    from ranobelib_epub.images import ImageAsset

    source_url = "https://cdn.example.test/map.png"
    chapter = _chapter(
        1,
        "TOC",
        "Generated",
        (
            Image(
                name="untrusted free form name.png",
                attachment=Attachment("map.png", url=source_url),
                alt="Map",
                title="World map",
            ),
        ),
    )
    assets = {
        source_url: ImageAsset(source_url, b"fake-png", "image/png", "images/image-0001.png")
    }

    payload = build_epub_bytes(BookMetadata(title="Book"), [chapter], image_assets=assets)

    with ZipFile(BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert "EPUB/images/image-0001.png" in names
        assert not any("untrusted free form" in name for name in names)
        html = archive.read("EPUB/chapters/chapter-0001.xhtml").decode("utf-8")
        assert '<img src="../images/image-0001.png" alt="Map" title="World map"' in html


def test_collect_image_assets_warns_and_continues_on_fetch_failure() -> None:
    from ranobelib_epub.content import Attachment
    from ranobelib_epub.images import ImageFetchLimits, collect_image_assets

    class FailingFetcher:
        def fetch_image(self, url, limits):
            raise ValueError("offline failure")

    chapter = _chapter(
        1,
        "TOC",
        "Generated",
        (
            Image(
                name="cover.png",
                attachment=Attachment("cover.png", url="https://img.test/cover.png"),
            ),
        ),
    )

    assets, warnings = collect_image_assets([chapter], FailingFetcher(), ImageFetchLimits())

    assert assets == {}
    assert warnings == ("Image block 'cover.png' skipped: offline failure",)


def test_collect_image_assets_enforces_count_and_byte_limits() -> None:
    from ranobelib_epub.content import Attachment
    from ranobelib_epub.images import ImageFetchLimits, collect_image_assets

    class FakeFetcher:
        def fetch_image(self, url, limits):
            content = b"too-large" if url.endswith("large.png") else b"ok"
            return content, "image/png"

    chapter = _chapter(
        1,
        "TOC",
        "Generated",
        (
            Image(
                name="first.png",
                attachment=Attachment("first.png", url="https://img.test/first.png"),
            ),
            Image(
                name="second.png",
                attachment=Attachment("second.png", url="https://img.test/second.png"),
            ),
            Image(
                name="large.png",
                attachment=Attachment("large.png", url="https://img.test/large.png"),
            ),
        ),
    )

    assets, warnings = collect_image_assets(
        [chapter],
        FakeFetcher(),
        ImageFetchLimits(max_image_count=2, max_bytes_per_image=3, max_total_image_bytes=10),
    )

    assert tuple(asset.file_name for asset in assets.values()) == (
        "images/image-0001.png",
        "images/image-0002.png",
    )
    assert warnings == ("Image limit reached; image skipped",)


def test_httpx_image_fetcher_rejects_private_headers_before_request(monkeypatch) -> None:
    from ranobelib_epub.images import HttpxImageAssetFetcher, ImageFetchLimits

    def fail_request(*args, **kwargs):
        raise AssertionError("request should not be sent")

    monkeypatch.setattr("ranobelib_epub.images.httpx.stream", fail_request)

    fetcher = HttpxImageAssetFetcher(headers={"Cookie": "private=1"})
    with pytest.raises(ValueError, match="Forbidden private headers"):
        fetcher.fetch_image("https://img.test/cover.png", ImageFetchLimits())


def test_collect_image_assets_skips_too_large_image() -> None:
    from ranobelib_epub.content import Attachment
    from ranobelib_epub.images import ImageFetchLimits, collect_image_assets

    class FakeFetcher:
        def fetch_image(self, url, limits):
            return b"large", "image/png"

    chapter = _chapter(
        1,
        "TOC",
        "Generated",
        (
            Image(
                name="large.png",
                attachment=Attachment("large.png", url="https://img.test/large.png"),
            ),
        ),
    )

    assets, warnings = collect_image_assets(
        [chapter], FakeFetcher(), ImageFetchLimits(max_bytes_per_image=3)
    )

    assert assets == {}
    assert warnings == ("Image block 'large.png' skipped: image is too large",)


def test_image_source_url_uses_fixed_public_base_for_root_relative_paths() -> None:
    from ranobelib_epub.content import Attachment
    from ranobelib_epub.images import image_source_url

    image = Image(
        name="cover.jpg",
        attachment=Attachment("cover.jpg", url="/uploads/ranobe/cover.jpg"),
    )

    assert image_source_url(image) == "https://api.cdnlibs.org/uploads/ranobe/cover.jpg"


def test_collect_image_assets_skips_unsupported_image_url_schemes() -> None:
    from ranobelib_epub.images import ImageFetchLimits, collect_image_assets

    class FailingFetcher:
        def fetch_image(self, url, limits):
            raise AssertionError("unsupported scheme should not be fetched")

    chapter = _chapter(1, "TOC", "Generated", (Image(name="local", src="file:///tmp/a.jpg"),))

    assets, warnings = collect_image_assets([chapter], FailingFetcher(), ImageFetchLimits())

    assert assets == {}
    assert warnings == ("Image block 'local' has no supported source URL; image skipped",)
