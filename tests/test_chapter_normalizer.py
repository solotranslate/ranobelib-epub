import pytest

from ranobelib_epub.ranobelib import (
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


def test_normalize_chapter_payload_rejects_non_doc_content() -> None:
    with pytest.raises(ValueError, match='type "doc"'):
        normalize_chapter_payload({"data": {"content": {"type": "paragraph"}}})


def test_normalize_chapter_payload_rejects_unsupported_nodes() -> None:
    with pytest.raises(ValueError, match="Unsupported RanobeLib content node type"):
        normalize_chapter_payload(
            {"data": {"content": {"type": "doc", "content": [{"type": "table"}]}}}
        )
