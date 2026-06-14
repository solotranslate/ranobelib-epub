from ranobelib_epub.content import (
    Blockquote,
    ChapterList,
    Heading,
    HorizontalRule,
    Image,
    Paragraph,
    normalize_chapter_payload,
)


def test_normalize_chapter_payload_preserves_supported_read_content() -> None:
    payload = {
        "data": {
            "content": {
                "type": "doc",
                "content": [
                    {
                        "type": "heading",
                        "attrs": {"level": 2},
                        "content": [{"type": "text", "text": "Chapter 1"}],
                    },
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Bold ", "marks": [{"type": "bold"}]},
                            {
                                "type": "text",
                                "text": "link",
                                "marks": [{"type": "link", "attrs": {"href": "#note"}}],
                            },
                        ],
                    },
                    {"type": "paragraph"},
                    {
                        "type": "orderedList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "First"}],
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "type": "bulletList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "Bullet"}],
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "type": "blockquote",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Quote"}],
                            }
                        ],
                    },
                    {"type": "horizontalRule"},
                    {
                        "type": "image",
                        "attrs": {
                            "alt": "Map",
                            "title": "World map",
                            "images": [{"image": "map.png"}],
                        },
                    },
                ],
            },
            "attachments": [
                {
                    "name": "map.png",
                    "url": "https://static.example.invalid/map.png",
                    "width": 640,
                    "height": 480,
                    "mime_type": "image/png",
                }
            ],
        }
    }

    chapter = normalize_chapter_payload(payload)

    assert len(chapter.blocks) == 8
    assert chapter.attachments["map.png"].url == "https://static.example.invalid/map.png"

    heading = chapter.blocks[0]
    assert isinstance(heading, Heading)
    assert heading.level == 2
    assert heading.runs[0].text == "Chapter 1"

    paragraph = chapter.blocks[1]
    assert isinstance(paragraph, Paragraph)
    assert paragraph.runs[0].marks[0].type == "bold"
    assert paragraph.runs[1].marks[0].attrs == {"href": "#note"}

    empty_paragraph = chapter.blocks[2]
    assert isinstance(empty_paragraph, Paragraph)
    assert empty_paragraph.runs == ()

    ordered_list = chapter.blocks[3]
    assert isinstance(ordered_list, ChapterList)
    assert ordered_list.kind == "ordered"
    assert ordered_list.items[0].blocks[0].runs[0].text == "First"

    bullet_list = chapter.blocks[4]
    assert isinstance(bullet_list, ChapterList)
    assert bullet_list.kind == "bullet"
    assert bullet_list.items[0].blocks[0].runs[0].text == "Bullet"

    blockquote = chapter.blocks[5]
    assert isinstance(blockquote, Blockquote)
    assert blockquote.blocks[0].runs[0].text == "Quote"

    assert isinstance(chapter.blocks[6], HorizontalRule)

    image = chapter.blocks[7]
    assert isinstance(image, Image)
    assert image.name == "map.png"
    assert image.attachment == chapter.attachments["map.png"]
    assert image.alt == "Map"
    assert image.title == "World map"
    assert chapter.warnings == ()


def test_normalize_chapter_payload_warns_for_non_doc_content() -> None:
    chapter = normalize_chapter_payload({"data": {"content": {"type": "paragraph"}}})

    assert chapter.blocks == ()
    assert chapter.warnings == ('data.content type is not "doc"; chapter content skipped',)


def test_normalize_chapter_payload_warns_for_unsupported_nodes() -> None:
    chapter = normalize_chapter_payload(
        {"data": {"content": {"type": "doc", "content": [{"type": "table"}]}}}
    )

    assert chapter.blocks == ()
    assert chapter.warnings == ("Unsupported RanobeLib content node type 'table'; node skipped",)


def test_normalize_chapter_payload_generates_unnamed_chapter_titles() -> None:
    chapter = normalize_chapter_payload(
        {
            "data": {
                "id": 42,
                "volume": "2",
                "number": "7",
                "number_secondary": "5",
                "slug": "ignored-when-numbered",
                "content": {"type": "doc", "content": []},
            }
        }
    )

    assert chapter.id == 42
    assert chapter.volume == "2"
    assert chapter.number == "7"
    assert chapter.number_secondary == "5"
    assert chapter.source_title is None
    assert chapter.source_name is None
    assert chapter.generated_title == "Volume 2 Chapter 7.5"
    assert chapter.toc_title == "Volume 2 Chapter 7.5"


def test_normalize_chapter_payload_preserves_missing_image_attachment_with_warning() -> None:
    chapter = normalize_chapter_payload(
        {
            "data": {
                "content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "image",
                            "attrs": {"images": [{"image": "missing.png"}]},
                        }
                    ],
                },
                "attachments": [],
            }
        }
    )

    image = chapter.blocks[0]
    assert isinstance(image, Image)
    assert image.name == "missing.png"
    assert image.attachment is None
    assert chapter.warnings == ("Image attachment 'missing.png' is missing; image preserved",)
