"""sprint3: llm_calls table, story_clusters classification columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("purpose", sa.String, nullable=False),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("prompt_version", sa.String, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.add_column("story_clusters", sa.Column("event_type", sa.String, nullable=True))
    op.add_column(
        "story_clusters", sa.Column("is_main_subject", sa.Boolean, nullable=True)
    )
    op.add_column(
        "story_clusters", sa.Column("is_opinion", sa.Boolean, nullable=True)
    )
    op.add_column(
        "story_clusters", sa.Column("relevance_score", sa.Float, nullable=True)
    )
    op.add_column(
        "story_clusters",
        sa.Column("visible", sa.Boolean, nullable=False, server_default="1"),
    )
    op.add_column(
        "story_clusters",
        sa.Column("classification_model", sa.String, nullable=True),
    )
    op.add_column(
        "story_clusters",
        sa.Column("classification_prompt_version", sa.String, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("story_clusters", "classification_prompt_version")
    op.drop_column("story_clusters", "classification_model")
    op.drop_column("story_clusters", "visible")
    op.drop_column("story_clusters", "relevance_score")
    op.drop_column("story_clusters", "is_opinion")
    op.drop_column("story_clusters", "is_main_subject")
    op.drop_column("story_clusters", "event_type")
    op.drop_table("llm_calls")
