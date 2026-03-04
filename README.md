# 🎨 Etsy Automation Pipeline — WatercolorAnn

Automated toolkit for managing your Etsy shop: niche research, trend analysis, competitor monitoring, and listing uploads.

## Architecture

```
etsy-automation/
├── main.py                 # CLI entry point (all commands)
├── config/
│   └── __init__.py         # Settings from .env
├── db/
│   └── __init__.py         # SQLite database + models
├── etsy_api/
│   ├── __init__.py         # Etsy API client (HTTP + pagination)
│   └── auth.py             # OAuth 2.0 PKCE flow
├── research/
│   └── __init__.py         # Google Trends + Etsy niche analysis
├── monitor/
│   └── __init__.py         # Competitor shop tracker
├── uploader/
│   └── __init__.py         # Listing upload automation
├── sample_listings.json    # Example listing data
├── .env.example            # Environment template
└── requirements.txt
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your Etsy API credentials

# 3. Initialize database + seed keywords
python main.py init

# 4. Authenticate with Etsy (opens browser)
python main.py auth

# 5. Run research pipeline
python main.py research
```

## Commands

| Command | Description |
|---------|-------------|
| `python main.py auth` | Etsy OAuth2 login (opens browser) |
| `python main.py init` | Create DB + seed niche keywords |
| `python main.py research` | Analyze all keywords (Trends + Etsy) |
| `python main.py trends` | Fetch Google Trends data only |
| `python main.py competitors` | Snapshot competitor shops |
| `python main.py discover` | Find new keywords from seeds |
| `python main.py upload FILE [--dry]` | Upload listings from JSON |
| `python main.py report` | Show top opportunities table |
| `python main.py daily` | Run full pipeline (trends→research→competitors) |
| `python main.py add-competitor ID NAME` | Add shop to monitor |

## Getting Your Etsy API Key

1. Go to https://www.etsy.com/developers/register
2. Create a new app
3. Copy the **API Key** and **Shared Secret** to `.env`
4. Find your **Shop ID** in your shop URL or via the API
5. Run `python main.py auth` to complete OAuth

## Database

SQLite file at `data/etsy_automation.db`. Browse with:
```bash
sqlite3 data/etsy_automation.db
.tables
SELECT * FROM niche_scores ORDER BY opportunity_score DESC LIMIT 10;
```

## Phase 2 Ideas

- [ ] Streamlit dashboard for visual analytics
- [ ] Scheduled daily runs via cron/systemd
- [ ] Pinterest API integration for marketing
- [ ] SFTP uploaders for Adobe Stock / Shutterstock
- [ ] Alura API integration (when it launches)
- [ ] Automated mockup generation with Pillow
