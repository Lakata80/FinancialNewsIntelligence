"""create sources, articles, fetch_runs tables

Revision ID: 0001
Revises:
Create Date: 2026-10-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("url_template", sa.Text, nullable=True),
        sa.Column("is_official", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="1"),
    )

    op.create_table(
        "articles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("publisher", sa.String, nullable=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("summary_raw", sa.Text, nullable=True),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("canonical_url", sa.String, nullable=False),
        sa.Column("published_at", sa.DateTime, nullable=False),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.Column("tickers_raw", sa.JSON, nullable=False),
        sa.Column("content_hash", sa.String, nullable=True),
        sa.Column("raw_payload", sa.JSON, nullable=False),
        sa.UniqueConstraint("canonical_url", name="uq_articles_canonical_url"),
    )
    op.create_index("ix_articles_canonical_url", "articles", ["canonical_url"])
    op.create_index("ix_articles_published_at", "articles", ["published_at"])

    op.create_table(
        "fetch_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="running"),
        sa.Column("items_seen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_new", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("newest_item_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("fetch_runs")
    op.drop_index("ix_articles_published_at", "articles")
    op.drop_index("ix_articles_canonical_url", "articles")
    op.drop_table("articles")
    op.drop_table("sources")
