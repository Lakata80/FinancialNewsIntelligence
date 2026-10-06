"""sprint2: sanitization fields, story_clusters, cluster_members

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("clean_text", sa.Text, nullable=True))
    op.add_column("articles", sa.Column("injection_score", sa.Float, nullable=True))
    op.add_column("articles", sa.Column("matched_rules", sa.JSON, nullable=True))
    op.add_column(
        "articles",
        sa.Column("status", sa.String, nullable=False, server_default="active"),
    )

    op.create_table(
        "story_clusters",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("primary_ticker", sa.String, nullable=True),
        sa.Column("first_seen_at", sa.DateTime, nullable=False),
        sa.Column("last_seen_at", sa.DateTime, nullable=False),
        sa.Column("article_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("publisher_count", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "cluster_members",
        sa.Column(
            "cluster_id",
            sa.Integer,
            sa.ForeignKey("story_clusters.id"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            sa.Integer,
            sa.ForeignKey("articles.id"),
            nullable=False,
        ),
        sa.Column("match_method", sa.String, nullable=False),
        sa.Column("similarity", sa.Float, nullable=False),
        sa.Column(
            "needs_llm_check", sa.Boolean, nullable=False, server_default="0"
        ),
        sa.PrimaryKeyConstraint("cluster_id", "article_id"),
    )
    op.create_index("ix_cluster_members_article_id", "cluster_members", ["article_id"])


def downgrade() -> None:
    op.drop_index("ix_cluster_members_article_id", "cluster_members")
    op.drop_table("cluster_members")
    op.drop_table("story_clusters")
    op.drop_column("articles", "status")
    op.drop_column("articles", "matched_rules")
    op.drop_column("articles", "injection_score")
    op.drop_column("articles", "clean_text")
