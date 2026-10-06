"""Sprint 5: verification_log table + story_facts.verification_status column.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "story_facts",
        sa.Column(
            "verification_status",
            sa.String,
            nullable=False,
            server_default="pending",
        ),
    )

    op.create_table(
        "verification_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("story_id", sa.Integer, sa.ForeignKey("stories.id"), nullable=False),
        sa.Column("fact_id", sa.Integer, sa.ForeignKey("story_facts.id"), nullable=True),
        sa.Column("check", sa.String, nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("verification_log")
    op.drop_column("story_facts", "verification_status")
