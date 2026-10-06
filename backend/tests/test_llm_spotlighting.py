"""Tests for article spotlighting — no API calls."""
from __future__ import annotations

import re

from app.llm.spotlighting import wrap_article


def test_wrapped_contains_original_text():
    result = wrap_article(42, "Some article content here.")
    assert "Some article content here." in result


def test_article_id_in_tag():
    result = wrap_article(99, "text")
    assert 'id="99"' in result


def test_nonce_in_open_and_close_tags():
    result = wrap_article(1, "text")
    nonce_match = re.search(r'nonce="([a-f0-9]+)"', result)
    assert nonce_match is not None
    nonce = nonce_match.group(1)
    assert f'nonce="{nonce}"' in result
    # Nonce appears in both open and close tags
    assert result.count(f'nonce="{nonce}"') == 2


def test_nonce_is_hex():
    result = wrap_article(1, "text")
    nonce_match = re.search(r'nonce="([a-f0-9]+)"', result)
    assert nonce_match is not None
    nonce = nonce_match.group(1)
    assert len(nonce) == 16
    assert all(c in "0123456789abcdef" for c in nonce)


def test_nonces_are_unique_across_calls():
    nonces = set()
    for i in range(50):
        result = wrap_article(i, "text")
        m = re.search(r'nonce="([a-f0-9]+)"', result)
        assert m is not None
        nonces.add(m.group(1))
    assert len(nonces) == 50


def test_article_tag_structure():
    result = wrap_article(7, "body text")
    assert result.startswith('<article id="7"')
    assert "</article" in result
