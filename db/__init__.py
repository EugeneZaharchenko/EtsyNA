"""
SQLite database layer.
All tables, queries, and data access methods in one place.

Why raw SQL instead of an ORM?
- SQLite + raw SQL is simple and transparent
- You see exactly what's happening (great for learning)
- No ORM overhead for a pipeline this size
- Easy to debug with `sqlite3` CLI tool
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager

from loguru import logger

from config import settings, PROJECT_ROOT


# ──────────────────────────────────────────────
#  Schema Definition
# ──────────────────────────────────────────────

SCHEMA_SQL = """
-- Keywords we're tracking (our niche terms)
CREATE TABLE IF NOT EXISTS keywords (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword         TEXT NOT NULL UNIQUE,
    category        TEXT,              -- e.g. 'botanical', 'birds', 'patterns'
    is_active       BOOLEAN DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Google Trends snapshots for our keywords
CREATE TABLE IF NOT EXISTS google_trends (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id      INTEGER NOT NULL REFERENCES keywords(id),
    date            TEXT NOT NULL,     -- YYYY-MM-DD
    interest_score  INTEGER,           -- 0-100 relative interest
    collected_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date)
);

-- Etsy search results / competitor listings
CREATE TABLE IF NOT EXISTS etsy_listings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id      TEXT NOT NULL UNIQUE,  -- Etsy's listing ID
    shop_name       TEXT,
    title           TEXT,
    description     TEXT,
    price           REAL,
    currency        TEXT DEFAULT 'USD',
    quantity        INTEGER,
    favorites       INTEGER DEFAULT 0,
    views           INTEGER DEFAULT 0,
    tags            TEXT,              -- JSON array stored as text
    taxonomy_id     INTEGER,
    url             TEXT,
    first_seen      TEXT DEFAULT (datetime('now')),
    last_seen       TEXT DEFAULT (datetime('now'))
);

-- Link table: which keywords returned which listings
CREATE TABLE IF NOT EXISTS keyword_listings (
    keyword_id      INTEGER NOT NULL REFERENCES keywords(id),
    listing_id      INTEGER NOT NULL REFERENCES etsy_listings(id),
    search_rank     INTEGER,           -- position in search results
    collected_at    TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (keyword_id, listing_id, collected_at)
);

-- Competitor shops we're monitoring
CREATE TABLE IF NOT EXISTS competitor_shops (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id         TEXT NOT NULL UNIQUE,  -- Etsy shop ID
    shop_name       TEXT NOT NULL,
    url             TEXT,
    notes           TEXT,              -- why we're tracking them
    is_active       BOOLEAN DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Daily snapshots of competitor metrics
CREATE TABLE IF NOT EXISTS competitor_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id         INTEGER NOT NULL REFERENCES competitor_shops(id),
    total_sales     INTEGER,
    total_listings  INTEGER,
    total_favorites INTEGER,
    avg_price       REAL,
    collected_at    TEXT DEFAULT (datetime('now'))
);

-- Our own listings (for tracking uploads & performance)
CREATE TABLE IF NOT EXISTS my_listings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id      TEXT UNIQUE,       -- NULL until uploaded to Etsy
    title           TEXT NOT NULL,
    description     TEXT,
    tags            TEXT,              -- JSON array
    price           REAL,
    file_paths      TEXT,              -- JSON array of local file paths
    status          TEXT DEFAULT 'draft',  -- draft | uploaded | active | deactivated
    uploaded_at     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Niche analysis results
CREATE TABLE IF NOT EXISTS niche_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id      INTEGER NOT NULL REFERENCES keywords(id),
    etsy_listing_count   INTEGER,      -- supply: how many listings exist
    avg_favorites        REAL,         -- engagement signal
    avg_price            REAL,
    google_trend_score   INTEGER,      -- latest Google Trends value
    competition_ratio    REAL,         -- calculated: supply / demand proxy
    opportunity_score    REAL,         -- our composite score (higher = better)
    calculated_at        TEXT DEFAULT (datetime('now'))
);

-- Indices for common queries
CREATE INDEX IF NOT EXISTS idx_google_trends_keyword ON google_trends(keyword_id);
CREATE INDEX IF NOT EXISTS idx_google_trends_date ON google_trends(date);
CREATE INDEX IF NOT EXISTS idx_etsy_listings_shop ON etsy_listings(shop_name);
CREATE INDEX IF NOT EXISTS idx_niche_scores_keyword ON niche_scores(keyword_id);
CREATE INDEX IF NOT EXISTS idx_niche_scores_opportunity ON niche_scores(opportunity_score DESC);
"""


# ──────────────────────────────────────────────
#  Database Connection Manager
# ──────────────────────────────────────────────

class Database:
    """SQLite database manager with context-manager support."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or settings.database.path
        settings.database.ensure_directory()

    @contextmanager
    def connection(self):
        """
        Context manager for DB connections.
        Usage:
            with db.connection() as conn:
                conn.execute("SELECT ...")
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent reads
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self):
        """Apply all pending Alembic migrations to bring the schema up to date."""
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
        logger.info(f"Database initialized at {self.db_path}")

    # ──────────────────────────────────────────
    #  Keywords CRUD
    # ──────────────────────────────────────────

    def add_keyword(self, keyword: str, category: str | None = None) -> int:
        """Insert a keyword to track. Returns the keyword ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO keywords (keyword, category) VALUES (?, ?)",
                (keyword.lower().strip(), category),
            )
            if cursor.rowcount == 0:
                # Already exists, fetch ID
                row = conn.execute(
                    "SELECT id FROM keywords WHERE keyword = ?",
                    (keyword.lower().strip(),),
                ).fetchone()
                return row["id"]
            return cursor.lastrowid

    def get_active_keywords(self) -> list[dict]:
        """Get all active keywords."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM keywords WHERE is_active = 1 ORDER BY category, keyword"
            ).fetchall()
            return [dict(row) for row in rows]

    # ──────────────────────────────────────────
    #  Google Trends
    # ──────────────────────────────────────────

    def save_trend_data(self, keyword_id: int, date: str, interest_score: int):
        """Save a single Google Trends data point."""
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO google_trends
                   (keyword_id, date, interest_score)
                   VALUES (?, ?, ?)""",
                (keyword_id, date, interest_score),
            )

    def save_trend_batch(self, records: list[tuple]):
        """
        Bulk insert trend data.
        records: list of (keyword_id, date, interest_score)
        """
        with self.connection() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO google_trends
                   (keyword_id, date, interest_score)
                   VALUES (?, ?, ?)""",
                records,
            )
        logger.debug(f"Saved {len(records)} trend records")

    # ──────────────────────────────────────────
    #  Competitor Tracking
    # ──────────────────────────────────────────

    def add_competitor(self, shop_id: str, shop_name: str, notes: str = "") -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO competitor_shops
                   (shop_id, shop_name, notes)
                   VALUES (?, ?, ?)""",
                (shop_id, shop_name, notes),
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    "SELECT id FROM competitor_shops WHERE shop_id = ?",
                    (shop_id,),
                ).fetchone()
                return row["id"]
            return cursor.lastrowid

    def save_competitor_snapshot(
        self,
        shop_id: int,
        total_sales: int,
        total_listings: int,
        total_favorites: int,
        avg_price: float,
    ):
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO competitor_snapshots
                   (shop_id, total_sales, total_listings, total_favorites, avg_price)
                   VALUES (?, ?, ?, ?, ?)""",
                (shop_id, total_sales, total_listings, total_favorites, avg_price),
            )

    def get_active_competitors(self) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM competitor_shops WHERE is_active = 1"
            ).fetchall()
            return [dict(row) for row in rows]

    # ──────────────────────────────────────────
    #  Niche Scores
    # ──────────────────────────────────────────

    def save_niche_score(self, keyword_id: int, **metrics):
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO niche_scores
                   (keyword_id, etsy_listing_count, avg_favorites,
                    avg_price, google_trend_score, competition_ratio,
                    opportunity_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    keyword_id,
                    metrics.get("etsy_listing_count", 0),
                    metrics.get("avg_favorites", 0),
                    metrics.get("avg_price", 0),
                    metrics.get("google_trend_score", 0),
                    metrics.get("competition_ratio", 0),
                    metrics.get("opportunity_score", 0),
                ),
            )

    def get_top_opportunities(self, limit: int = 20) -> list[dict]:
        """Get keywords ranked by opportunity score."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT ns.*, k.keyword, k.category
                   FROM niche_scores ns
                   JOIN keywords k ON k.id = ns.keyword_id
                   ORDER BY ns.opportunity_score DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]


# Singleton
db = Database()
