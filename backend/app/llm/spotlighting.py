from __future__ import annotations

import secrets
from datetime import datetime


def wrap_article(article_id: int, text: str) -> str:
    """Wrap article text in a tagged block with a random nonce.

    The nonce makes it impractical for injected instructions inside the article
    to forge the closing tag, mitigating prompt-injection attempts.
    """
    nonce = secrets.token_hex(8)
    return (
        f'<article id="{article_id}" nonce="{nonce}">\n'
        f"{text}\n"
        f'</article nonce="{nonce}">'
    )


def wrap_article_full(
    article_id: int,
    text: str,
    publisher: str | None,
    published_at: datetime,
) -> str:
    """Like wrap_article() but also includes publisher and date metadata.

    Used by the summarizer so the LLM can attribute quotes to a source.
    """
    nonce = secrets.token_hex(8)
    pub = publisher or "unknown"
    date = published_at.strftime("%Y-%m-%d")
    return (
        f'<article id="{article_id}" publisher="{pub}" published_at="{date}" nonce="{nonce}">\n'
        f"{text}\n"
        f'</article nonce="{nonce}">'
    )
