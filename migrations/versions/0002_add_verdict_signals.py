"""add verdict and signals columns to niche_scores

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-23
"""

from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE niche_scores ADD COLUMN verdict TEXT")
    op.execute("ALTER TABLE niche_scores ADD COLUMN signals TEXT")  # JSON array as text


def downgrade():
    op.execute("ALTER TABLE niche_scores DROP COLUMN verdict")
    op.execute("ALTER TABLE niche_scores DROP COLUMN signals")
