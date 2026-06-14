from __future__ import annotations

_DEFAULT_SECONDARY_NUMBERS = {"0", "1"}


def display_chapter_number(number: str | None, number_secondary: str | None) -> str | None:
    """Return a user-facing chapter number with non-default secondary numbering.

    RanobeLib may send ``number_secondary=1`` for ordinary chapters. That value is an
    implementation detail and should not appear in generated labels or fallback TOC titles.
    """

    clean_number = _clean_number(number)
    if clean_number is None:
        return None

    clean_secondary = _clean_number(number_secondary)
    if clean_secondary is None or _is_default_secondary(clean_secondary):
        return clean_number
    return f"{clean_number}.{clean_secondary}"


def _clean_number(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_default_secondary(value: str) -> bool:
    try:
        numeric_value = float(value)
    except ValueError:
        return value in _DEFAULT_SECONDARY_NUMBERS
    return numeric_value in (0.0, 1.0)
