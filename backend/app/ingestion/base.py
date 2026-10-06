from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawArticle:
    source_name: str
    title: str
    url: str
    published_at: datetime  # UTC naive
    summary_raw: str | None = None
    publisher: str | None = None
    tickers_raw: list[str] = field(default_factory=list)
    raw_payload: dict = field(default_factory=dict)


class SourceConnector(ABC):
    source_name: str  # e.g. "yahoo_rss"
    source_kind: str  # "rss" | "api"

    @abstractmethod
    def fetch(self) -> list[RawArticle]:
        """Fetch articles. Should log errors and return [] rather than raise."""
        ...
