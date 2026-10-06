"""CLI entry point: python -m app.ingest --once"""
import argparse
import logging

from app.ingestion.ecb import ECBPressRSS
from app.ingestion.fed import FedPressRSS
from app.ingestion.finnhub import FinnhubCompanyNews
from app.ingestion.pipeline import run_all_connectors
from app.ingestion.yahoo import YahooTickerRSS

_CONNECTORS = [
    YahooTickerRSS(),
    FinnhubCompanyNews(),
    FedPressRSS(),
    ECBPressRSS(),
]

_COL_SRC = 20
_COL_SEEN = 8
_COL_NEW = 6
_COL_TITLE = 48
_COL_STATUS = 8


def _header() -> str:
    src = f"{'Източник':<{_COL_SRC}}"
    seen = f"{'Видяни':>{_COL_SEEN}}"
    new = f"{'Нови':>{_COL_NEW}}"
    title = f"{'Последна статия':<{_COL_TITLE}}"
    status = f"{'Статус':<{_COL_STATUS}}"
    return f"{src} {seen} {new}  {title} {status}"


def _row(
    source_name: str, items_seen: int, items_new: int, title: str, status: str
) -> str:
    if len(title) > _COL_TITLE:
        title = title[: _COL_TITLE - 3] + "..."
    src = f"{source_name:<{_COL_SRC}}"
    seen = f"{items_seen:>{_COL_SEEN}}"
    new = f"{items_new:>{_COL_NEW}}"
    t = f"{title:<{_COL_TITLE}}"
    st = f"{status:<{_COL_STATUS}}"
    return f"{src} {seen} {new}  {t} {st}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest financial news articles")
    parser.add_argument(
        "--once", action="store_true", required=True, help="Run ingestion once and exit"
    )
    parser.parse_args()

    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")

    results = run_all_connectors(_CONNECTORS)

    header = _header()
    print(header)
    print("-" * len(header))

    for r in results:
        newest = r.newest_article_title or "—"
        print(_row(r.source_name, r.items_seen, r.items_new, newest, r.status))


if __name__ == "__main__":
    main()
