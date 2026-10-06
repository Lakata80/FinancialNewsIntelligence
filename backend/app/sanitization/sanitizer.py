from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup, Comment

# Zero-width and invisible formatting characters
_ZERO_WIDTH = re.compile(
    "[​‌‍﻿⁠]"
)

# Unicode bidi control characters
_BIDI_CONTROLS = re.compile(
    "[‎‏‪‫‬‭‮⁦⁧⁨⁩]"
)

_WHITESPACE = re.compile(r"\s+")


def sanitize_html(raw: str) -> str:
    """Return clean plain text from raw HTML or plain text.

    Strips tags, hidden elements, HTML comments, alt/title attributes,
    normalises Unicode (NFKC), and removes zero-width / bidi control chars.
    The original string is never mutated.
    """
    if not raw:
        return ""

    soup = BeautifulSoup(raw, "html.parser")

    # Remove script and style blocks entirely
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # Remove elements hidden via aria-hidden or inline display:none
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()
    for tag in soup.find_all(style=True):
        style_val = tag.get("style", "")
        if "display" in style_val and "none" in style_val:
            tag.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Strip alt and title attributes (could carry injected content)
    for tag in soup.find_all(True):
        tag.attrs.pop("alt", None)
        tag.attrs.pop("title", None)

    text = soup.get_text(separator=" ")

    # Unicode normalisation
    text = unicodedata.normalize("NFKC", text)

    # Remove zero-width and bidi control characters
    text = _ZERO_WIDTH.sub("", text)
    text = _BIDI_CONTROLS.sub("", text)

    # Collapse whitespace
    return _WHITESPACE.sub(" ", text).strip()
