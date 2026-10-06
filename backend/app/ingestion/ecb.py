from __future__ import annotations

import logging

from app.ingestion.base import RawArticle, SourceConnector

logger = logging.getLogger(__name__)

# URL not yet confirmed — see QUESTIONS.md Q-001
_ECB_RSS_URL = ""


class ECBPressRSS(SourceConnector):
    source_name = "ecb_rss"
    source_kind = "rss"

    def fetch(self) -> list[RawArticle]:
        if not _ECB_RSS_URL:
            logger.info("ECB RSS URL not configured; skipping (see QUESTIONS.md Q-001)")
            return []
        raise NotImplementedError("ECB connector not yet implemented")
