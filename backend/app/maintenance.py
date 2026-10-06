"""Maintenance commands: cleanup, backup, export-digest.

Usage:
    python -m app.maintenance cleanup [--dry-run]
    python -m app.maintenance backup [--out DIR]
    python -m app.maintenance export-digest [--date YYYY-MM-DD] [--output PATH]
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import func, select, text

from app.core.db import SessionLocal
from app.models.news import Article, FactEvidence, LlmCall, Story, StoryFact, StoryVersion

_CONFIG_PATH = Path("config.yaml")
_DB_PATH = Path("news.db")
_BACKUPS_DIR = Path("backups")
_EXPORTS_DIR = Path("exports")


def _load_retention() -> dict:
    try:
        cfg = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        cfg = {}
    return cfg.get("retention", {})


def cmd_cleanup(dry_run: bool = False) -> None:
    retention = _load_retention()
    raw_days = int(retention.get("raw_articles_days", 90))
    story_days = int(retention.get("stories_days", 365))

    now = datetime.now(UTC).replace(tzinfo=None)
    article_cutoff = now - timedelta(days=raw_days)
    story_cutoff = now - timedelta(days=story_days)

    mode = "DRY RUN — " if dry_run else ""
    print(f"\n{mode}Cleanup policy: articles >{raw_days}d, stories >{story_days}d")

    with SessionLocal() as session:
        # --- Stories older than story_days ---
        old_stories = session.scalars(
            select(Story).where(Story.created_at < story_cutoff)
        ).all()
        print(f"\nOld stories to delete: {len(old_stories)}")
        if not dry_run:
            for story in old_stories:
                print(f"  Deleting story {story.id}: {story.title_bg[:60]}")
                session.delete(story)
            session.flush()

        # --- Old LlmCall rows (same window as stories) ---
        old_llm_count: int = session.scalar(
            select(func.count(LlmCall.id)).where(LlmCall.created_at < story_cutoff)
        ) or 0
        print(f"Old LlmCall rows to delete: {old_llm_count}")
        if not dry_run and old_llm_count > 0:
            session.execute(
                text("DELETE FROM llm_calls WHERE created_at < :cutoff"),
                {"cutoff": story_cutoff.isoformat()},
            )

        # --- Articles: only delete those with no cluster_members AND no fact_evidence ---
        # (cited articles are kept until their story expires — see Q-007)
        old_uncited_articles = session.scalars(
            select(Article)
            .where(Article.fetched_at < article_cutoff)
            .where(Article.status != "quarantined")
            .where(
                ~select(func.count(FactEvidence.id))
                .where(FactEvidence.article_id == Article.id)
                .correlate(Article)
                .scalar_subquery()
                .bool_op(">")(0)
            )
            .where(
                ~select(func.count(text("1")))
                .select_from(text("cluster_members"))
                .where(text("cluster_members.article_id = articles.id"))
                .correlate(Article)
                .scalar_subquery()
                .bool_op(">")(0)
            )
        ).all()

        print(f"Old uncited articles to delete: {len(old_uncited_articles)}")
        if not dry_run:
            for article in old_uncited_articles:
                session.delete(article)

        if not dry_run:
            session.commit()
            print("\nCleanup complete.")
        else:
            print("\nDry run complete — no changes made.")


def cmd_backup(out_dir: Path = _BACKUPS_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    dest = out_dir / f"news_{timestamp}.db"

    if not _DB_PATH.exists():
        print(f"Database not found at {_DB_PATH} — nothing to back up.")
        sys.exit(1)

    # sqlite3.Connection.backup() is safe for online use (no exclusive lock needed)
    src_conn = sqlite3.connect(str(_DB_PATH))
    dst_conn = sqlite3.connect(str(dest))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    size_kb = dest.stat().st_size // 1024
    print(f"Backup written: {dest}  ({size_kb} KB)")


def cmd_export_digest(date_str: str | None = None, output: Path | None = None) -> None:
    _EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if date_str is None:
        target_date = datetime.now(UTC).date()
    else:
        from datetime import date
        target_date = date.fromisoformat(date_str)

    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
    day_end = day_start + timedelta(days=1)

    if output is None:
        output = _EXPORTS_DIR / f"digest_{target_date.isoformat()}.md"

    with SessionLocal() as session:
        stories = session.scalars(
            select(Story)
            .where(Story.created_at >= day_start)
            .where(Story.created_at < day_end)
            .where(Story.verification_status.in_(["verified", "partial"]))
            .order_by(Story.created_at.desc())
        ).all()

        if not stories:
            print(f"No verified stories found for {target_date.isoformat()}.")
            return

        lines: list[str] = [
            f"# Финансов дайджест — {target_date.isoformat()}",
            f"\n_Генериран: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}_",
            f"_Истории: {len(stories)}_",
            "",
        ]

        for story in stories:
            cluster = story.cluster
            ticker = cluster.primary_ticker or "—"
            lines.append(f"## {story.title_bg}  ({ticker})")
            lines.append("")
            lines.append(f"**Тип:** {story.event_type or '—'} | "
                         f"**Статус:** {story.verification_status} | "
                         f"**Публикации:** {cluster.article_count}")
            lines.append("")
            lines.append(story.summary_bg)
            lines.append("")

            facts = sorted(story.facts, key=lambda f: f.fact_order)
            active_facts = [f for f in facts if f.verification_status != "removed"]
            if active_facts:
                lines.append("**Факти:**")
                for fact in active_facts:
                    lines.append(f"- {fact.text_bg}")
                lines.append("")

            # Source URLs from cluster members
            source_urls: list[str] = []
            for member in cluster.members:
                art = member.article
                source_name = art.source.name if art.source else art.publisher or "—"
                source_urls.append(f"  - [{source_name}]({art.url})")
            if source_urls:
                lines.append("**Източници:**")
                lines.extend(source_urls)
                lines.append("")

            lines.append("---")
            lines.append("")

        output.write_text("\n".join(lines), encoding="utf-8")
        print(f"Digest written: {output}  ({len(stories)} stories)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Financial News Intelligence maintenance")
    sub = parser.add_subparsers(dest="command", required=True)

    p_cleanup = sub.add_parser("cleanup", help="Delete old articles and stories")
    p_cleanup.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")

    p_backup = sub.add_parser("backup", help="Create a SQLite backup")
    p_backup.add_argument("--out", default=str(_BACKUPS_DIR), help="Output directory (default: backups/)")

    p_export = sub.add_parser("export-digest", help="Export daily story digest as Markdown")
    p_export.add_argument("--date", default=None, help="Date in YYYY-MM-DD (default: today)")
    p_export.add_argument("--output", default=None, help="Output file path")

    args = parser.parse_args()

    if args.command == "cleanup":
        cmd_cleanup(dry_run=args.dry_run)
    elif args.command == "backup":
        cmd_backup(out_dir=Path(args.out))
    elif args.command == "export-digest":
        out = Path(args.output) if args.output else None
        cmd_export_digest(date_str=args.date, output=out)


if __name__ == "__main__":
    main()
