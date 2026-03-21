# Design: `python main.py analyze <keyword>` Command

**Date:** 2026-03-21
**Status:** Approved

## Purpose

Single-keyword deep analysis command that fetches live data from Google Trends and Etsy, computes an opportunity score with a hybrid verdict + contextual signals, saves results to the database, and generates a Plotly HTML report.

## CLI Interface

```bash
python main.py analyze "watercolor clipart"
```

**Arguments:**
- `keyword` (required) — the search term to analyze

**Output:**
1. Rich terminal summary (verdict, signals, metrics, tags)
2. Static HTML report at `reports/analyze-{keyword-slug}-{YYYY-MM-DD}.html`
3. Data persisted to `google_trends` and `niche_scores` tables

## Architecture

### New Module: `analyze/__init__.py`

Class `KeywordAnalyzer` composes existing `TrendAnalyzer` and `EtsyResearcher` — no subclassing, no modifications to `research/`.

```
KeywordAnalyzer.run(keyword)
    ├── 1. db.add_keyword() — ensure keyword exists, get keyword_id
    ├── 2. TrendAnalyzer.get_interest_over_time([keyword], "today 12-m")
    ├── 3. TrendAnalyzer.detect_seasonality(keyword)
    ├── 4. EtsyResearcher.get_keyword_metrics(keyword) — returns raw prices list
    ├── 5. compute_opportunity_score(demand, engagement, competition)
    ├── 6. compute_verdict(score, trend_data, etsy_metrics, seasonality)
    ├── 7. Save to DB: google_trends batch + niche_scores (with verdict/signals)
    ├── 8. Print Rich summary to terminal
    └── 9. Generate Plotly HTML → PROJECT_ROOT / reports/
```

### Shared Function: `compute_opportunity_score`

Extracted to `analyze/__init__.py` as a standalone pure function to avoid duplicating the formula from `NicheFinder`. `KeywordAnalyzer` calls this directly rather than delegating to `NicheFinder` — it composes the same building blocks (`TrendAnalyzer`, `EtsyResearcher`) but produces richer output.

```python
def compute_opportunity_score(demand, engagement, competition):
    """Shared formula. demand/engagement floored at 1."""
    demand = max(demand, 1)
    engagement = max(engagement, 1)
    return round((demand * (engagement ** 0.5)) / (competition ** 0.3 + 1), 2)
```

### Standalone Function: `compute_verdict`

```python
def compute_verdict(score, trend_data, etsy_metrics, seasonality):
    """Returns (verdict_str, signals_list)"""
```

Separated from the class for testability. Takes computed values, returns pure data.

## Verdict Logic (Hybrid)

### Primary Verdict (based on opportunity score)

| Score Range | Verdict |
|-------------|---------|
| >= 10 | "🟢 Good niche" |
| 5 – 9.99 | "🟡 Moderate — needs differentiation" |
| < 5 | "🔴 Tough market" |

### Contextual Signals

Each signal is a conditional check on the raw metrics:

| Signal | Condition |
|--------|-----------|
| 📈 Rising trend | Last ~13 weeks avg > previous ~13 weeks avg by 20%+ |
| 📉 Declining trend | Last ~13 weeks avg < previous ~13 weeks avg by 20%+ |
| 🎄 Highly seasonal | Peak month interest >= 3x trough month interest |
| 💰 Premium pricing possible | avg_price > $10 |
| ⚠️ Price race to bottom | avg_price < $3 |
| 🏆 Low competition | listing_count < 5,000 |
| 🔥 Oversaturated | listing_count > 100,000 |
| 💎 High engagement | avg_favorites > 150 |
| 👻 Low engagement | avg_favorites < 20 |

**Trend direction:** The 12-month trend DataFrame from `get_interest_over_time()` contains ~52 weekly data points. Split the DataFrame in half: average of the last ~13 rows vs the previous ~13 rows. Compare: if last > previous by 20%+, rising; if last < previous by 20%+, declining.

**Seasonality:** Uses the `monthly_averages` dict from `TrendAnalyzer.detect_seasonality()` (5 years of data). The "highly seasonal" flag compares `max(monthly_averages.values())` vs `min(monthly_averages.values())` — if max >= 3x min, the flag fires. Note: the existing `is_seasonal` boolean from `detect_seasonality()` uses a different heuristic (30% above/below mean) and is ignored for our purposes.

## Terminal Output

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Keyword: watercolor clipart
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Verdict: 🟢 Good niche (score: 14.2)
  Signals: 📈 Rising trend, 🏆 Low competition, 💰 Premium pricing

  ┌─────────────────┬──────────┐
  │ Metric          │ Value    │
  ├─────────────────┼──────────┤
  │ Google Trend    │ 72       │
  │ Listings        │ 3,241    │
  │ Avg Price       │ $12.50   │
  │ Price Range     │ $2 – $45 │
  │ Avg Favorites   │ 187      │
  └─────────────────┴──────────┘

  Top 15 Tags:
  watercolor, clipart, floral, botanical, png, ...

  📊 Report saved: reports/analyze-watercolor-clipart-2026-03-21.html
```

## Plotly HTML Report

Self-contained HTML file with Plotly JS bundled inline. Contains:

1. **Trends line chart** — 12-month weekly Google Trends interest. X-axis: dates, Y-axis: interest (0-100).
2. **Seasonality bar chart** — 12 bars (Jan–Dec) from 5-year monthly averages. Peak months highlighted in a distinct color.
3. **Price distribution** — histogram of individual prices from the sampled Etsy listings (up to 100), with min/median/max annotated as vertical lines.
4. **Summary panel** — verdict, signals, key metrics table, top 15 tags. Rendered as HTML/CSS above the charts.

Layout: single-page vertical scroll. Summary at top, charts below.

**File path:** `PROJECT_ROOT / reports / analyze-{keyword-slug}-{YYYY-MM-DD}.html`
- Keyword slug: lowercase, spaces replaced with hyphens, special chars stripped
- The `reports/` directory is created if it doesn't exist
- Uses `PROJECT_ROOT` (from `config`) for consistent path resolution regardless of CWD

## Database Changes

### New Migration: `0002_add_verdict_signals.py`

- `revision = "0002"`, `down_revision = "0001"`

**Upgrade:**
```sql
ALTER TABLE niche_scores ADD COLUMN verdict TEXT;
ALTER TABLE niche_scores ADD COLUMN signals TEXT;  -- JSON array stored as text
```

**Downgrade:** SQLite 3.35.0+ supports DROP COLUMN. Python 3.12 ships with SQLite 3.37+, so this is safe:
```sql
ALTER TABLE niche_scores DROP COLUMN verdict;
ALTER TABLE niche_scores DROP COLUMN signals;
```

### Modified: `db.save_niche_score()`

Updated SQL to include the two new columns. The `signals` list is serialized to JSON text via `json.dumps()` before storage.

```python
def save_niche_score(self, keyword_id, **metrics):
    with self.connection() as conn:
        conn.execute(
            """INSERT INTO niche_scores
               (keyword_id, etsy_listing_count, avg_favorites,
                avg_price, google_trend_score, competition_ratio,
                opportunity_score, verdict, signals)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                keyword_id,
                metrics.get("etsy_listing_count", 0),
                metrics.get("avg_favorites", 0),
                metrics.get("avg_price", 0),
                metrics.get("google_trend_score", 0),
                metrics.get("competition_ratio", 0),
                metrics.get("opportunity_score", 0),
                metrics.get("verdict"),          # NULL if not provided
                metrics.get("signals"),          # NULL if not provided (pre-serialized JSON or None)
            ),
        )
```

Backwards compatible: existing callers (`NicheFinder.analyze_keyword`) don't pass `verdict` or `signals`, so those columns store NULL. The `analyze` command passes both. Each call appends a new row (INSERT, not UPSERT) — the `report` command already handles multiple scores per keyword by selecting the latest `calculated_at`.

### Modified: `EtsyResearcher.get_keyword_metrics()`

Add `prices` key to the returned dict containing the raw list of individual prices extracted from search results (up to 100 values). This is needed for the price distribution histogram in the Plotly report:

```python
return {
    "listing_count": total_count,
    "avg_price": ...,
    "avg_favorites": ...,
    "price_range": ...,
    "top_tags": top_tags,
    "prices": prices,  # NEW: raw list for histogram
}
```

This is a backwards-compatible addition — existing callers access dict keys they need and ignore extras. The `prices` list is already computed internally (line 148-153 of `research/__init__.py`); we just expose it in the return value.

## Files Changed

| File | Change |
|------|--------|
| `analyze/__init__.py` | **New.** `KeywordAnalyzer` class, `compute_opportunity_score()`, `compute_verdict()`, Plotly report generation |
| `main.py` | Add `analyze` Click command with `keyword` argument |
| `db/__init__.py` | Update `save_niche_score()` INSERT to include `verdict` and `signals` columns |
| `research/__init__.py` | Add `prices` key to `get_keyword_metrics()` return dict |
| `migrations/versions/0002_add_verdict_signals.py` | New Alembic migration with upgrade + downgrade |

Note: `plotly` is already in `pyproject.toml` — no dependency change needed.

## Error Handling

Follows existing graceful degradation pattern:
- Google Trends API failure → trend chart omitted from report, score uses demand=0, logged as warning
- Etsy API failure → Etsy metrics section shows zeros, logged as warning
- Both fail → still generates report with available data and a "limited data" notice
- File write failure (reports/) → terminal output still displayed, error logged

## Opportunity Score Formula (unchanged)

```
score = (demand * sqrt(engagement)) / (competition^0.3 + 1)
```

Where:
- demand = latest Google Trends value (0-100), floored at 1
- engagement = avg favorites per listing, floored at 1
- competition = Etsy listing count

## Design Decisions

- **Tags: display 15, fetch 20.** `EtsyResearcher` returns top 20 tags. The `analyze` command displays 15 in terminal and report (truncated from the 20 available).
- **Score formula extracted, not delegated.** `KeywordAnalyzer` does not call `NicheFinder.analyze_keyword()`. It composes `TrendAnalyzer` + `EtsyResearcher` directly and uses the shared `compute_opportunity_score()` function. This avoids coupling to `NicheFinder`'s save-to-DB side effects and its less detailed return value.
- **No `--json` or `--no-report` flags in v1.** Can be added later if pipeline scripting is needed.
