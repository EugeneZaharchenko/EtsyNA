"""baseline — full initial schema

Revision ID: 0001
Revises: None
Create Date: 2026-03-04
"""
from alembic import op


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE keywords (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword         TEXT NOT NULL UNIQUE,
            category        TEXT,
            is_active       BOOLEAN DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE TABLE google_trends (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword_id      INTEGER NOT NULL REFERENCES keywords(id),
            date            TEXT NOT NULL,
            interest_score  INTEGER,
            collected_at    TEXT DEFAULT (datetime('now')),
            UNIQUE(keyword_id, date)
        )
    """)

    op.execute("""
        CREATE TABLE etsy_listings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id      TEXT NOT NULL UNIQUE,
            shop_name       TEXT,
            title           TEXT,
            description     TEXT,
            price           REAL,
            currency        TEXT DEFAULT 'USD',
            quantity        INTEGER,
            favorites       INTEGER DEFAULT 0,
            views           INTEGER DEFAULT 0,
            tags            TEXT,
            taxonomy_id     INTEGER,
            url             TEXT,
            first_seen      TEXT DEFAULT (datetime('now')),
            last_seen       TEXT DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE TABLE keyword_listings (
            keyword_id      INTEGER NOT NULL REFERENCES keywords(id),
            listing_id      INTEGER NOT NULL REFERENCES etsy_listings(id),
            search_rank     INTEGER,
            collected_at    TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (keyword_id, listing_id, collected_at)
        )
    """)

    op.execute("""
        CREATE TABLE competitor_shops (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id         TEXT NOT NULL UNIQUE,
            shop_name       TEXT NOT NULL,
            url             TEXT,
            notes           TEXT,
            is_active       BOOLEAN DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE TABLE competitor_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id         INTEGER NOT NULL REFERENCES competitor_shops(id),
            total_sales     INTEGER,
            total_listings  INTEGER,
            total_favorites INTEGER,
            avg_price       REAL,
            collected_at    TEXT DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE TABLE my_listings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id      TEXT UNIQUE,
            title           TEXT NOT NULL,
            description     TEXT,
            tags            TEXT,
            price           REAL,
            file_paths      TEXT,
            status          TEXT DEFAULT 'draft',
            uploaded_at     TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE TABLE niche_scores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword_id      INTEGER NOT NULL REFERENCES keywords(id),
            etsy_listing_count   INTEGER,
            avg_favorites        REAL,
            avg_price            REAL,
            google_trend_score   INTEGER,
            competition_ratio    REAL,
            opportunity_score    REAL,
            calculated_at        TEXT DEFAULT (datetime('now'))
        )
    """)

    # Indices
    op.execute("CREATE INDEX idx_google_trends_keyword ON google_trends(keyword_id)")
    op.execute("CREATE INDEX idx_google_trends_date ON google_trends(date)")
    op.execute("CREATE INDEX idx_etsy_listings_shop ON etsy_listings(shop_name)")
    op.execute("CREATE INDEX idx_niche_scores_keyword ON niche_scores(keyword_id)")
    op.execute("CREATE INDEX idx_niche_scores_opportunity ON niche_scores(opportunity_score DESC)")


def downgrade():
    # Drop in reverse dependency order
    op.execute("DROP TABLE IF EXISTS niche_scores")
    op.execute("DROP TABLE IF EXISTS my_listings")
    op.execute("DROP TABLE IF EXISTS competitor_snapshots")
    op.execute("DROP TABLE IF EXISTS competitor_shops")
    op.execute("DROP TABLE IF EXISTS keyword_listings")
    op.execute("DROP TABLE IF EXISTS etsy_listings")
    op.execute("DROP TABLE IF EXISTS google_trends")
    op.execute("DROP TABLE IF EXISTS keywords")
