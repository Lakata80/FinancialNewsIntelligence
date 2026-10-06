"""Sprint 9: story_versions and llm_response_cache tables.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # story_versions: archive of superseded stories per cluster (ADR-025)
    op.create_table(
        "story_versions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("cluster_id", sa.Integer, sa.ForeignKey("story_clusters.id"), nullable=False),
        sa.Column("version_num", sa.Integer, nullable=False),
        sa.Column("replaced_at", sa.DateTime, nullable=False),
        sa.Column("reason", sa.String, nullable=False),
        sa.Column("snapshot_json", sa.Text, nullable=False),
        sa.Column("model_version", sa.String, nullable=False),
        sa.Column("prompt_version", sa.String, nullable=False),
        sa.UniqueConstraint("cluster_id", "version_num", name="uq_story_versions_cluster_version"),
    )

    # llm_response_cache: DB-backed cache keyed by sha256 of (prompt_version+model+user_msg) (ADR-026)
    op.create_table(
        "llm_response_cache",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("cache_key", sa.String(32), nullable=False, unique=True),
        sa.Column("purpose", sa.String, nullable=False),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("prompt_version", sa.String, nullable=False),
        sa.Column("response_text", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_hit_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("llm_response_cache")
    op.drop_table("story_versions")
