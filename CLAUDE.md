# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EtsyNA is a CLI-based Etsy shop automation pipeline for niche research, competitor tracking, and listing management. Built with Python 3.12+, Click CLI, raw SQLite, and Etsy API v3 with OAuth 2.0 PKCE.

## Commands

```bash
# Setup
uv pip install -e .              # Install (uv preferred)
cp .env.example .env             # Configure credentials

# Core CLI commands (all via python main.py <command>)
python main.py init              # Create DB + seed keywords
python main.py auth              # OAuth 2.0 PKCE flow (opens browser, callback on port 3003)
python main.py trends            # Fetch Google Trends data
python main.py research          # Analyze all active keywords
python main.py competitors       # Snapshot all competitor shops
python main.py discover          # Find new keywords via Etsy autocomplete
python main.py report            # Show top 20 opportunities by niche score
python main.py upload FILE [--dry]  # Upload listings from JSON (--dry for validation only)
python main.py daily             # Full pipeline: trends → research → competitors
python main.py add-competitor SHOP_ID "Name" "notes"  # Add competitor shop
python main.py db-upgrade [REV]   # Apply migrations (default: head)
python main.py db-downgrade [REV] # Roll back migrations (default: -1)

# Alembic CLI (for creating new migrations)
uv run alembic revision -m "description"  # Create new migration
uv run alembic current                    # Show current DB revision
uv run alembic history                    # Show migration history
uv run alembic stamp head                 # Mark existing DB as up-to-date

# Lint
ruff check .
ruff format .
```

No test framework is configured yet.

## Architecture

**Entry point**: `main.py` — Click CLI with subcommands. Sets up logging, validates config before execution.

**Module structure** (each module exposes a singleton instance):

- `config/` — Dataclass-based settings (`EtsyConfig`, `DatabaseConfig`, `LogConfig`). Loads from `.env` via python-dotenv. Singleton: `settings`.
- `db/` — Raw SQLite3 with WAL mode, context manager connections, no ORM. Schema managed by Alembic migrations (`migrations/versions/`). Singleton: `db`.
- `etsy_api/` — Etsy API v3 client with auto-retry on 401, rate limiting, offset-based pagination. Singleton: `etsy_client`.
- `etsy_api/auth.py` — OAuth 2.0 PKCE flow with local HTTP callback server.
- `research/` — Three classes: `TrendAnalyzer` (Google Trends via pytrends), `EtsyResearcher` (marketplace metrics + autocomplete), `NicheFinder` (combines both, computes opportunity score).
- `monitor/` — `CompetitorTracker`: daily shop snapshots, new listing detection, tag frequency analysis.
- `uploader/` — `ListingUploader`: validates → creates draft → uploads images → uploads files → activates. `ListingDraft` dataclass. Supports dry-run.

**Niche opportunity score formula**:
```
score = (demand * sqrt(engagement)) / (competition^0.3 + 1)
```
Where demand = Google Trends interest, engagement = avg favorites, competition = listing count.

## Conventions

- No type hints (unless Pydantic is introduced)
- Raw SQL preferred over ORM for transparency — Alembic migrations use `op.execute()` with raw SQL, not SQLAlchemy models
- Singleton pattern for config, db, and API client instances
- Rate limiting built into all API-calling code (0.5s–2s delays)
- Graceful degradation: API failures return empty results with logged warnings
- Section headers use `# ──────` dashed lines
- Rich library for terminal output (tables, colors)
- Loguru for structured logging

## Key Dependencies

click, loguru, pandas, pytrends, requests, requests-oauthlib, rich, schedule, ruff. Optional: alembic (migrations), paramiko (SFTP uploads).
