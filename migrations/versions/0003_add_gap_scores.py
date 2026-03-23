"""add gap_scores table

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-23
"""

from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS gap_scores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword_id      INTEGER NOT NULL REFERENCES keywords(id),
            trend_growth_pct REAL,
            listing_count   INTEGER,
            gap_score       REAL,
            classification  TEXT,
            calculated_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_gap_scores_keyword ON gap_scores(keyword_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_gap_scores_score ON gap_scores(gap_score DESC)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS gap_scores")
