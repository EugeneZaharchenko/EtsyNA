# Etsy Niche Analytics Pipeline — Architecture Plan

## 1. Project Overview

**Goal:** A FastAPI-based backend service that collects, stores, and analyzes marketplace data to identify profitable niches, track competition, detect trends, and predict seasonal demand for creative products (clipart, patterns, digital art).

**Tech Stack:**
- **Runtime:** Python 3.11+
- **API Framework:** FastAPI + Uvicorn
- **Database:** SQLite (dev) → PostgreSQL (prod-ready migration via SQLAlchemy)
- **ORM:** SQLAlchemy 2.0 (async)
- **Task Scheduling:** APScheduler (lightweight) or Celery + Redis (if scaling)
- **Data Collection:** pytrends, httpx (async HTTP), Etsy API v3
- **Analysis:** pandas, numpy, scipy (seasonality detection), scikit-learn (trend prediction)
- **Visualization:** matplotlib (server-side chart generation for API responses)
- **Config:** pydantic-settings (.env-based configuration)

---

## 2. Project Structure

```
etsy_niche_analyzer/
│
├── alembic/                        # DB migrations
│   ├── versions/
│   └── env.py
│
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app entry point
│   ├── config.py                   # Settings (pydantic-settings, .env)
│   ├── database.py                 # SQLAlchemy engine, session factory
│   │
│   ├── models/                     # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── keyword.py              # Keyword + search volume snapshots
│   │   ├── listing.py              # Etsy listing snapshots
│   │   ├── trend.py                # Google Trends data points
│   │   ├── competitor.py           # Tracked shops & their metrics
│   │   └── analysis.py             # Computed analysis results (CDR, scores)
│   │
│   ├── schemas/                    # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── keyword.py
│   │   ├── listing.py
│   │   ├── trend.py
│   │   ├── competitor.py
│   │   └── analysis.py
│   │
│   ├── collectors/                 # Data collection layer
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract collector interface
│   │   ├── google_trends.py        # pytrends wrapper
│   │   ├── etsy_api.py             # Etsy API v3 client (OAuth 2.0)
│   │   ├── etsy_suggest.py         # Etsy autocomplete scraper
│   │   └── pinterest.py            # Pinterest trends (future)
│   │
│   ├── analysis/                   # Analysis & ML layer
│   │   ├── __init__.py
│   │   ├── competition.py          # Competition-to-Demand Ratio (CDR)
│   │   ├── seasonality.py          # Seasonal decomposition & prediction
│   │   ├── pricing.py              # Price distribution & sweet spots
│   │   ├── trending.py             # Rising/falling keyword detection
│   │   └── niche_scorer.py         # Composite niche opportunity score
│   │
│   ├── services/                   # Business logic layer
│   │   ├── __init__.py
│   │   ├── keyword_service.py      # Keyword CRUD + analysis orchestration
│   │   ├── collection_service.py   # Data collection orchestration
│   │   └── report_service.py       # Report generation
│   │
│   ├── api/                        # API routes
│   │   ├── __init__.py
│   │   ├── router.py               # Main router aggregator
│   │   ├── keywords.py             # /api/v1/keywords/...
│   │   ├── trends.py               # /api/v1/trends/...
│   │   ├── competitors.py          # /api/v1/competitors/...
│   │   ├── analysis.py             # /api/v1/analysis/...
│   │   └── collect.py              # /api/v1/collect/... (trigger collection)
│   │
│   └── tasks/                      # Scheduled background tasks
│       ├── __init__.py
│       └── scheduler.py            # APScheduler jobs
│
├── seed/                           # Seed data
│   └── keywords.json               # Initial keyword list
│
├── tests/
│   ├── conftest.py
│   ├── test_collectors/
│   ├── test_analysis/
│   └── test_api/
│
├── .env.example
├── alembic.ini
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 3. Database Schema

### 3.1 `keywords` — Tracked keywords/niches

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| keyword | VARCHAR(255) UNIQUE | Search term ("botanical clipart") |
| category | VARCHAR(100) | User-defined grouping ("clipart", "patterns") |
| is_active | BOOLEAN | Whether to include in scheduled collection |
| created_at | DATETIME | When keyword was added |
| updated_at | DATETIME | Last modification |

### 3.2 `etsy_snapshots` — Etsy listing counts & pricing over time

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| keyword_id | INTEGER FK | → keywords.id |
| collected_at | DATETIME | Snapshot timestamp |
| total_listings | INTEGER | Active listings count for this keyword |
| avg_price | FLOAT | Average listing price (USD) |
| median_price | FLOAT | Median listing price |
| min_price | FLOAT | Lowest price found |
| max_price | FLOAT | Highest price found |
| avg_favorites | FLOAT | Average favorites per listing (proxy for demand) |
| top_tags | JSON | Most common tags across results (list of strings) |
| sample_size | INTEGER | How many listings were sampled |

### 3.3 `google_trends_data` — Google Trends interest over time

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| keyword_id | INTEGER FK | → keywords.id |
| date | DATE | Week/month of the data point |
| interest | INTEGER | Google Trends interest (0-100) |
| geo | VARCHAR(10) | Region ("US", "worldwide") |
| collected_at | DATETIME | When this was fetched |

### 3.4 `etsy_suggestions` — Autocomplete data (what buyers type)

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| keyword_id | INTEGER FK | → keywords.id |
| suggestion | VARCHAR(255) | Autocomplete suggestion text |
| position | INTEGER | Rank position in autocomplete |
| collected_at | DATETIME | Snapshot timestamp |

### 3.5 `competitor_shops` — Tracked competitor shops

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| shop_name | VARCHAR(255) UNIQUE | Etsy shop name |
| etsy_shop_id | INTEGER | Etsy internal shop ID |
| total_sales | INTEGER | Total sales count (at last check) |
| total_listings | INTEGER | Active listings count |
| last_checked_at | DATETIME | Last data refresh |
| created_at | DATETIME | When tracking started |

### 3.6 `competitor_snapshots` — Shop metrics over time

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| shop_id | INTEGER FK | → competitor_shops.id |
| collected_at | DATETIME | Snapshot timestamp |
| total_sales | INTEGER | Cumulative sales at this point |
| total_listings | INTEGER | Active listings count |
| avg_price | FLOAT | Average price across their listings |
| new_listings_7d | INTEGER | Estimated new listings in past 7 days |

### 3.7 `analysis_results` — Computed niche scores (cached)

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| keyword_id | INTEGER FK | → keywords.id |
| computed_at | DATETIME | When analysis was run |
| cdr_score | FLOAT | Competition-to-Demand Ratio |
| trend_direction | VARCHAR(20) | "rising" / "stable" / "falling" |
| trend_slope | FLOAT | Linear regression slope |
| seasonality_peak_month | INTEGER | Month with highest demand (1-12) |
| price_sweet_spot | FLOAT | Optimal price point |
| niche_score | FLOAT | Composite opportunity score (0-100) |
| details | JSON | Full analysis breakdown |

### ER Diagram (simplified)

```
keywords ──1:N──> etsy_snapshots
keywords ──1:N──> google_trends_data
keywords ──1:N──> etsy_suggestions
keywords ──1:N──> analysis_results

competitor_shops ──1:N──> competitor_snapshots
```

---

## 4. Data Collection Layer

### 4.1 Google Trends Collector (`google_trends.py`)

**Library:** `pytrends` (unofficial Google Trends API)
**No auth required** — works immediately.

**Capabilities:**
- `interest_over_time()` — weekly interest for keyword (past 5 years or custom range)
- `related_queries()` — "rising" and "top" related searches
- `suggestions()` — Google's autocomplete for the keyword
- `interest_by_region()` — geographic breakdown

**Data points collected per keyword:**
- Weekly interest scores (0-100) for past 12 months
- Related rising queries (potential niche opportunities)
- Regional interest breakdown (US focus)

**Rate limiting:** pytrends has no official rate limit, but Google may throttle.
Strategy: 1-2 second delay between requests, batch max 5 keywords per call.

**Example flow:**
```python
from pytrends.request import TrendReq

pytrends = TrendReq(hl='en-US', tz=360)
pytrends.build_payload(["botanical clipart"], timeframe='today 12-m', geo='US')
interest_df = pytrends.interest_over_time()     # → DataFrame with weekly scores
related = pytrends.related_queries()            # → dict with 'rising' and 'top'
```

### 4.2 Etsy API Collector (`etsy_api.py`)

**Library:** `httpx` (async) + custom OAuth 2.0 flow
**Auth:** OAuth 2.0 — requires Etsy Developer App registration

**Key endpoints:**
| Endpoint | What it gives us |
|----------|-----------------|
| `GET /v3/application/listings/active` | Search listings by keyword → count, prices, favorites |
| `GET /v3/application/shops/{shop_id}` | Shop info → total sales, listings count |
| `GET /v3/application/shops/{shop_id}/listings` | All listings for a shop |
| `GET /v3/application/taxonomy/seller` | Category taxonomy |

**Data points collected per keyword:**
- Total active listings count (supply metric)
- Price distribution (min, max, avg, median)
- Favorites distribution (demand proxy)
- Most common tags across top results
- Top shops in this niche

**Rate limits:** Etsy enforces QPD (queries per day) limits.
Strategy: cache aggressively, collect once daily per keyword.

**OAuth 2.0 flow (implemented in the service):**
1. App redirects user to Etsy authorization URL
2. User grants access → redirect back with authorization code
3. Exchange code for access_token + refresh_token
4. Store tokens, refresh when expired

### 4.3 Etsy Autocomplete Collector (`etsy_suggest.py`)

**No auth required** — simple HTTP GET to Etsy's search suggest endpoint.

**Endpoint:** `https://www.etsy.com/search/suggest?q={query}`

**What it gives us:**
- Real buyer search terms (long-tail keywords)
- Search intent signals
- Niche sub-categories buyers are looking for

**Example:**
```
Input: "botanical"
Output: ["botanical prints", "botanical clipart", "botanical wall art",
         "botanical garden", "botanical illustration", "botanical stickers"]
```

### 4.4 Collection Schedule

| Collector | Frequency | Reason |
|-----------|-----------|--------|
| Google Trends | Weekly (Sunday night) | Data updates weekly |
| Etsy Listings | Daily (2 AM) | Track listing count changes |
| Etsy Autocomplete | Weekly (Monday morning) | Suggestions change slowly |
| Competitor Shops | Daily (3 AM) | Track sales velocity |

---

## 5. Analysis Layer

### 5.1 Competition-to-Demand Ratio (CDR)

**The core metric.** This is what eRank/EverBee sell, and what we calculate ourselves.

**Formula:**
```
CDR = Supply_Score / Demand_Score

Where:
  Supply_Score = normalize(total_etsy_listings)      # More listings = more competition
  Demand_Score = normalize(google_interest) * 0.6    # Google search interest
               + normalize(avg_favorites) * 0.3      # Etsy favorites (engagement)
               + normalize(suggestion_count) * 0.1   # Autocomplete presence

Lower CDR = better opportunity (high demand, low competition)
```

**Normalization:** Min-max scaling across all tracked keywords so scores are comparable.

**Classification:**
| CDR Range | Label | Meaning |
|-----------|-------|---------|
| < 0.3 | 🟢 Hot Niche | High demand, low competition |
| 0.3 - 0.7 | 🟡 Moderate | Balanced — viable with good SEO |
| 0.7 - 1.0 | 🟠 Competitive | Saturated but still possible |
| > 1.0 | 🔴 Oversaturated | Too much competition for the demand |

### 5.2 Seasonality Detection

**Method:** Seasonal decomposition using `statsmodels.seasonal_decompose()` or `scipy.signal`

**From Google Trends data (12+ months):**
1. Decompose into: trend + seasonal + residual
2. Identify peak months (when to list new products)
3. Identify trough months (when to prepare/create)
4. Calculate seasonal strength index

**Connects to your DS studies:** This uses the same statistical decomposition methods from your coursework (time series analysis, trend extraction).

### 5.3 Trend Direction Detection

**Method:** Linear regression (slope) on recent 3-month Google Trends data.

```python
from scipy.stats import linregress

slope, intercept, r_value, p_value, std_err = linregress(x_weeks, y_interest)

if slope > threshold and p_value < 0.05:
    direction = "rising"
elif slope < -threshold and p_value < 0.05:
    direction = "falling"
else:
    direction = "stable"
```

**Rising keywords = biggest opportunities** — get in before the niche peaks.

### 5.4 Price Sweet Spot Analysis

**From Etsy listing data:**
1. Build price distribution histogram
2. Identify modal price range (where most sales cluster)
3. Find gap between average competitor price and buyer expectation
4. Recommend pricing: slightly below the mode for new sellers

### 5.5 Composite Niche Score

**The final "opportunity score" (0-100) combining all signals:**

```python
niche_score = (
    (1 - cdr_normalized) * 35        # Low competition/high demand
    + trend_score * 25                # Rising trend bonus
    + seasonality_score * 15          # Near peak season bonus
    + price_margin_score * 15         # Healthy price margins
    + suggestion_diversity * 10       # Rich long-tail keyword ecosystem
)
```

---

## 6. API Design

### 6.1 Endpoints

```
Base URL: /api/v1

# ─── Keywords Management ───
POST   /keywords                     # Add keyword(s) to track
GET    /keywords                     # List all tracked keywords
GET    /keywords/{id}                # Get keyword details + latest metrics
DELETE /keywords/{id}                # Stop tracking a keyword
PATCH  /keywords/{id}                # Update keyword (category, active status)

# ─── Data Collection (manual trigger) ───
POST   /collect/trends               # Trigger Google Trends collection for all active keywords
POST   /collect/etsy                  # Trigger Etsy listings collection
POST   /collect/suggestions           # Trigger Etsy autocomplete collection
POST   /collect/all                   # Run full collection pipeline
GET    /collect/status                # Check last collection run status

# ─── Trends & History ───
GET    /trends/{keyword_id}           # Google Trends history for keyword
GET    /trends/{keyword_id}/chart     # PNG chart of trend over time
GET    /trends/compare                # Compare multiple keywords (query params)

# ─── Competition Analysis ───
GET    /analysis/cdr                  # CDR scores for all keywords (ranked)
GET    /analysis/cdr/{keyword_id}     # Detailed CDR breakdown for one keyword
GET    /analysis/seasonality/{keyword_id}  # Seasonal decomposition
GET    /analysis/pricing/{keyword_id}      # Price analysis
GET    /analysis/niche-score               # Full niche opportunity ranking
GET    /analysis/opportunities             # Top opportunities (rising + low CDR)

# ─── Competitor Tracking ───
POST   /competitors                   # Add shop to track
GET    /competitors                   # List tracked shops
GET    /competitors/{id}              # Shop details + sales velocity
GET    /competitors/{id}/history      # Sales/listings over time

# ─── Reports ───
GET    /reports/weekly                # Weekly summary report (JSON)
GET    /reports/weekly/chart          # Visual weekly report (PNG)
```

### 6.2 Example Response: Niche Score Ranking

```json
GET /api/v1/analysis/niche-score

{
  "computed_at": "2026-02-27T12:00:00Z",
  "keywords_analyzed": 15,
  "rankings": [
    {
      "rank": 1,
      "keyword": "watercolor herb illustrations",
      "category": "clipart",
      "niche_score": 82.4,
      "cdr": 0.23,
      "cdr_label": "hot_niche",
      "trend_direction": "rising",
      "trend_slope": 2.8,
      "etsy_listings": 1240,
      "google_interest_avg": 67,
      "avg_price": 4.50,
      "seasonality_peak": "March",
      "recommendation": "Strong opportunity. Rising demand with relatively low competition. Optimal listing time: 2-3 weeks before March peak."
    },
    {
      "rank": 2,
      "keyword": "seamless floral pattern",
      "category": "patterns",
      "niche_score": 71.8,
      "cdr": 0.41,
      "cdr_label": "moderate",
      "trend_direction": "stable",
      "trend_slope": 0.3,
      "etsy_listings": 8900,
      "google_interest_avg": 54,
      "avg_price": 3.20,
      "seasonality_peak": "May",
      "recommendation": "Viable niche with stable demand. Differentiation needed — focus on unique styles not well-represented."
    }
  ]
}
```

### 6.3 Example Response: CDR Breakdown

```json
GET /api/v1/analysis/cdr/42

{
  "keyword": "botanical clipart",
  "computed_at": "2026-02-27T12:00:00Z",
  "cdr_score": 0.35,
  "cdr_label": "moderate",
  "supply": {
    "etsy_active_listings": 15420,
    "normalized_score": 0.68,
    "note": "Above average listing count"
  },
  "demand": {
    "google_interest_avg_12m": 58,
    "google_interest_current": 72,
    "etsy_avg_favorites": 145,
    "autocomplete_suggestions": 8,
    "normalized_score": 0.74,
    "note": "Strong demand signals across all sources"
  },
  "trend": {
    "direction": "rising",
    "slope_3m": 3.2,
    "p_value": 0.008,
    "note": "Statistically significant upward trend"
  },
  "pricing": {
    "avg_price": 4.20,
    "median_price": 3.50,
    "price_range": [1.00, 24.99],
    "sweet_spot": [2.50, 5.00],
    "note": "Most sales in $2.50-$5.00 range"
  },
  "history": [
    {"date": "2026-01-27", "cdr": 0.39},
    {"date": "2026-02-03", "cdr": 0.37},
    {"date": "2026-02-10", "cdr": 0.36},
    {"date": "2026-02-17", "cdr": 0.35},
    {"date": "2026-02-24", "cdr": 0.35}
  ]
}
```

---

## 7. Implementation Phases

### Phase 1: Foundation (MVP — ~2-3 days)
- [x] Project scaffolding (FastAPI, SQLAlchemy, Alembic)
- [x] Database models & migrations
- [x] Config management (.env, pydantic-settings)
- [x] Google Trends collector (pytrends)
- [x] Keywords CRUD API
- [x] Basic trends endpoint
- [x] Seed data with generic keywords

**Deliverable:** Working API that collects and serves Google Trends data for tracked keywords.

### Phase 2: Etsy Integration (~2-3 days)
- [ ] Etsy OAuth 2.0 flow (auth endpoints)
- [ ] Etsy listings collector (search, count, prices)
- [ ] Etsy autocomplete collector
- [ ] Etsy data endpoints

**Deliverable:** API enriched with real Etsy marketplace data alongside Google Trends.

### Phase 3: Analysis Engine (~2-3 days)
- [ ] CDR calculation
- [ ] Trend direction detection (linear regression)
- [ ] Seasonality decomposition
- [ ] Price sweet spot analysis
- [ ] Composite niche score
- [ ] Analysis endpoints

**Deliverable:** Full analytical capabilities — the core value of the pipeline.

### Phase 4: Competitor Tracking (~1-2 days)
- [ ] Competitor shop CRUD
- [ ] Shop data collector
- [ ] Sales velocity calculation
- [ ] Competitor endpoints

### Phase 5: Scheduling & Automation (~1 day)
- [ ] APScheduler integration
- [ ] Automated daily/weekly collection jobs
- [ ] Collection status tracking

### Phase 6: Polish & Reports (~1-2 days)
- [ ] Chart generation (matplotlib → PNG via API)
- [ ] Weekly summary report endpoint
- [ ] Docker + docker-compose setup
- [ ] README with setup instructions

---

## 8. Seed Keywords (Generic Examples)

```json
{
  "keywords": [
    {"keyword": "botanical clipart", "category": "clipart"},
    {"keyword": "watercolor flowers png", "category": "clipart"},
    {"keyword": "seamless floral pattern", "category": "patterns"},
    {"keyword": "digital planner stickers", "category": "stickers"},
    {"keyword": "vintage botanical illustration", "category": "clipart"},
    {"keyword": "boho wedding invitation template", "category": "templates"},
    {"keyword": "watercolor herb illustration", "category": "clipart"},
    {"keyword": "tropical leaves clipart", "category": "clipart"},
    {"keyword": "minimalist line art svg", "category": "svg"},
    {"keyword": "cottagecore aesthetic png", "category": "clipart"},
    {"keyword": "wildflower seamless pattern", "category": "patterns"},
    {"keyword": "mushroom clipart png", "category": "clipart"},
    {"keyword": "celestial svg bundle", "category": "svg"},
    {"keyword": "abstract geometric pattern", "category": "patterns"},
    {"keyword": "hand drawn border clipart", "category": "clipart"}
  ]
}
```

---

## 9. Key Dependencies

```toml
[project]
name = "etsy-niche-analyzer"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    # API
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",

    # Database
    "sqlalchemy[asyncio]>=2.0.0",
    "aiosqlite>=0.20.0",         # Async SQLite driver
    "alembic>=1.14.0",

    # Data Collection
    "pytrends>=4.9.0",           # Google Trends
    "httpx>=0.27.0",             # Async HTTP (Etsy API)

    # Analysis
    "pandas>=2.2.0",
    "numpy>=1.26.0",
    "scipy>=1.14.0",             # Seasonality, regression
    "scikit-learn>=1.5.0",       # Normalization, future ML

    # Visualization
    "matplotlib>=3.9.0",

    # Config
    "pydantic-settings>=2.5.0",
    "python-dotenv>=1.0.0",

    # Scheduling
    "apscheduler>=3.10.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx",                     # For TestClient
    "ruff>=0.8.0",               # Linting
]
```

---

## 10. Configuration (.env.example)

```env
# ─── App ───
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
APP_DEBUG=true

# ─── Database ───
DATABASE_URL=sqlite+aiosqlite:///./data/niche_analyzer.db

# ─── Etsy API (Phase 2) ───
ETSY_API_KEY=
ETSY_SHARED_SECRET=
ETSY_REDIRECT_URI=http://localhost:8000/api/v1/auth/etsy/callback
ETSY_ACCESS_TOKEN=
ETSY_REFRESH_TOKEN=

# ─── Collection Settings ───
COLLECTION_DELAY_SECONDS=2       # Delay between API calls
PYTRENDS_GEO=US                  # Google Trends region
PYTRENDS_TIMEFRAME=today 12-m    # Default timeframe

# ─── Analysis Settings ───
CDR_WEIGHTS_GOOGLE=0.6
CDR_WEIGHTS_FAVORITES=0.3
CDR_WEIGHTS_SUGGESTIONS=0.1
TREND_SIGNIFICANCE_THRESHOLD=0.05
TREND_SLOPE_THRESHOLD=0.5
```

---

## 11. Data Flow Diagram

```
                    ┌──────────────────────────────────────────────────────────┐
                    │                    TRIGGERS                              │
                    │  Manual (POST /collect/all)  │  Scheduled (APScheduler)  │
                    └──────────────┬───────────────┴───────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         COLLECTION SERVICE                                   │
│                                                                              │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────────┐   ┌───────────┐  │
│  │ Google      │   │ Etsy API v3  │   │ Etsy Autocomplete│   │ Competitor│  │
│  │ Trends      │   │ (Listings)   │   │ (Suggestions)    │   │ Shops     │  │
│  │ Collector   │   │ Collector    │   │ Collector         │   │ Collector │  │
│  └──────┬──────┘   └──────┬───────┘   └────────┬──────────┘   └─────┬─────┘  │
│         │                 │                     │                    │        │
└─────────┼─────────────────┼─────────────────────┼────────────────────┼────────┘
          │                 │                     │                    │
          ▼                 ▼                     ▼                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           SQLite DATABASE                                    │
│                                                                              │
│  google_trends_data │ etsy_snapshots │ etsy_suggestions │ competitor_snapshots│
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         ANALYSIS ENGINE                                      │
│                                                                              │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────┐   ┌───────────────────┐  │
│  │ CDR         │   │ Seasonality  │   │ Pricing  │   │ Niche Score       │  │
│  │ Calculator  │   │ Detector     │   │ Analyzer │   │ (composite)       │  │
│  └─────────────┘   └──────────────┘   └──────────┘   └───────────────────┘  │
│                                                                              │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          FastAPI ENDPOINTS                                    │
│                                                                              │
│  /keywords  │  /trends  │  /analysis/cdr  │  /analysis/niche-score  │ etc.  │
│                                                                              │
│  JSON responses  │  PNG charts  │  Weekly reports                            │
└──────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │      Future: Vue.js Web UI    │
                    │      (your frontend skills)   │
                    └──────────────────────────────┘
```

---

## 12. Future Enhancements (Beyond Phase 6)

- **Vue.js Dashboard** — interactive frontend using your VueJS + Tailwind skills
- **PostgreSQL migration** — swap SQLite for production (already abstracted via SQLAlchemy)
- **Celery + Redis** — if collection jobs need to scale
- **Alura API integration** — when their API launches (you're on the waitlist)
- **Pinterest API** — additional demand signal source
- **ML-based prediction** — use scikit-learn / TensorFlow to predict niche trends 2-3 months ahead
- **Etsy upload integration** — connect with the Etsy upload pipeline (from your other project) to auto-list products in detected hot niches
- **Notification system** — Telegram bot alerts when a niche score spikes
