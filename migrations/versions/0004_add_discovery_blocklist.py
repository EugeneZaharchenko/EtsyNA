"""add discovery_blocklist table

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-23
"""

from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS discovery_blocklist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword     TEXT NOT NULL UNIQUE,
            reason      TEXT DEFAULT 'rejected',
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_blocklist_keyword ON discovery_blocklist(keyword)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS discovery_blocklist")
