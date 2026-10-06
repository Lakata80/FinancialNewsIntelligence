"""Sprint 4: stories, story_facts, fact_evidence tables.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cluster_id", sa.Integer, sa.ForeignKey("story_clusters.id"), nullable=False),
        sa.Column("title_bg", sa.Text, nullable=False),
        sa.Column("summary_bg", sa.Text, nullable=False),
        sa.Column("tickers", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("event_type", sa.String, nullable=True),
        sa.Column("is_opinion", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("verification_status", sa.String, nullable=False, server_default="pending"),
        sa.Column("model_version", sa.String, nullable=False),
        sa.Column("prompt_version", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("cluster_id", name="uq_stories_cluster_id"),
    )

    op.create_table(
        "story_facts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("story_id", sa.Integer, sa.ForeignKey("stories.id"), nullable=False),
        sa.Column("fact_order", sa.Integer, nullable=False),
        sa.Column("text_bg", sa.Text, nullable=False),
    )

    op.create_table(
        "fact_evidence",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fact_id", sa.Integer, sa.ForeignKey("story_facts.id"), nullable=False),
        sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("quote_en", sa.Text, nullable=False),
        sa.Column("quote_start", sa.Integer, nullable=True),
        sa.Column("quote_end", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("fact_evidence")
    op.drop_table("story_facts")
    op.drop_table("stories")
