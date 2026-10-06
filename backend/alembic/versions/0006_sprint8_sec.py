"""Sprint 8: SEC EDGAR fields on articles and story_clusters.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Article: SEC filing metadata
    op.add_column("articles", sa.Column("sec_form_type", sa.String, nullable=True))
    op.add_column("articles", sa.Column("sec_items", sa.JSON, nullable=True))

    # StoryCluster: primary source corroboration
    op.add_column(
        "story_clusters",
        sa.Column(
            "has_primary_source",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("story_clusters", sa.Column("sec_filing_url", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("story_clusters", "sec_filing_url")
    op.drop_column("story_clusters", "has_primary_source")
    op.drop_column("articles", "sec_items")
    op.drop_column("articles", "sec_form_type")
