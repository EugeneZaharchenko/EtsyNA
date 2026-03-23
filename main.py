"""
Etsy Automation Pipeline — Main CLI

Usage:
    python main.py auth           # Run OAuth flow
    python main.py init           # Initialize database + seed keywords
    python main.py research       # Run niche research on all keywords
    python main.py trends         # Fetch Google Trends data
    python main.py competitors    # Snapshot competitor shops
    python main.py discover       # Discover new keywords from seeds
    python main.py upload FILE    # Upload listings from JSON file
    python main.py upload --dry   # Validate without uploading
    python main.py report         # Show top niche opportunities
    python main.py daily          # Run full daily pipeline
"""

import re
import sys

import click
from rich.console import Console
from rich.table import Table
from loguru import logger

from config import settings, PROJECT_ROOT
from db import db
from research import NicheFinder, TrendAnalyzer
from monitor import CompetitorTracker
from uploader import ListingUploader, load_drafts_from_json
from analyze import KeywordAnalyzer

console = Console()

# ──────────────────────────────────────────────
#  Discovery Relevance Filters
# ──────────────────────────────────────────────

_RELEVANCE_TERMS = {
    "clipart", "png", "watercolor", "botanical", "floral", "pattern",
    "seamless", "digital", "illustration", "art print", "printable",
    "hand painted", "bundle", "download", "commercial use", "scrapbook",
    "wreath", "border", "frame", "texture", "background", "overlay",
    "invitation", "stationery", "planner", "journal", "wall art",
    "svg", "vector", "graphic", "design element",
}

_IRRELEVANT_PATTERN = re.compile(
    r"\b("
    r"recipe|tutorial|course|class|salary|job|wiki|near me|"
    r"how to|what is|video|youtube|amazon|walmart|target|"
    r"painting class|lesson|canvas|acrylic|oil paint|supplies|"
    r"brush|easel|lego|tattoo|cake|nail"
    r")\b",
    re.IGNORECASE,
)

# "fabric" is irrelevant UNLESS paired with "pattern"
_FABRIC_PATTERN = re.compile(r"\bfabric\b", re.IGNORECASE)
_FABRIC_OK_PATTERN = re.compile(r"\bfabric\s+pattern\b", re.IGNORECASE)


# ──────────────────────────────────────────────
#  Logging Setup
# ──────────────────────────────────────────────


def setup_logging():
    settings.logging.ensure_directory()
    logger.remove()  # Remove default handler
    logger.add(sys.stderr, level=settings.logging.level, colorize=True)
    logger.add(
        settings.logging.log_file,
        rotation="10 MB",
        retention="30 days",
        level="DEBUG",
    )


# ──────────────────────────────────────────────
#  CLI Commands
# ──────────────────────────────────────────────


@click.group()
def cli():
    """Etsy Automation Pipeline for WatercolorAnn"""
    setup_logging()


@cli.command()
def auth():
    """Run Etsy OAuth 2.0 authentication flow."""
    issues = settings.validate()
    if issues:
        for issue in issues:
            console.print(f"  ❌ {issue}", style="red")
        console.print("\nFill in your .env file first (copy from .env.example)")
        return

    from etsy_api.auth import EtsyAuth

    auth_handler = EtsyAuth()
    tokens = auth_handler.run_auth_flow()
    if tokens:
        console.print("\n✅ Add these to your .env file:\n", style="green bold")
        console.print(f"ETSY_ACCESS_TOKEN={tokens['access_token']}")
        console.print(f"ETSY_REFRESH_TOKEN={tokens['refresh_token']}")


@cli.command()
def init():
    """Initialize database and seed with your niche keywords."""
    db.init_schema()
    console.print("✅ Database initialized", style="green")

    # Seed keywords relevant to WatercolorAnn
    seed_keywords = [
    # Core Products (Refined and Expanded)
    ("watercolor clipart", "clipart_main"),
    ("botanical watercolor clipart", "clipart_botanical"),
    ("floral watercolor clipart png", "clipart_floral"),
    ("watercolor seamless pattern", "patterns_main"),
    ("botanical seamless pattern", "patterns_botanical"),
    ("floral digital paper", "patterns_floral"),
    ("watercolor elements", "clipart_general"), # Broader term for individual art pieces
    ("digital watercolor art", "art_prints"), # If selling prints
    ("watercolor textures", "patterns_textures"), # For background or design elements

    # Nature Subjects (Enhanced with "Watercolor")
    ("watercolor birds clipart", "nature_birds"),
    ("watercolor insects clipart", "nature_insects"),
    ("watercolor animals clipart", "nature_animals"),
    ("watercolor butterfly png", "nature_insects"),
    ("watercolor wildflower clipart", "nature_flowers"),
    ("watercolor leaves clipart", "nature_foliage"), # Added for detail

    # Use-Case Keywords (More specific and varied)
    ("watercolor wedding invitation clipart", "usecase_wedding"),
    ("digital scrapbook elements watercolor", "usecase_scrapbooking"),
    ("commercial use watercolor clipart", "usecase_commercial"),
    ("printable botanical wall art watercolor", "usecase_decor"),
    ("greeting card design watercolor", "usecase_cards"), # Card making
    ("planner stickers watercolor", "usecase_planners"), # Planner specific

    # Food Themes (Keep as is, good niche)
    ("watercolor food clipart", "food_main"),
    ("artisan bread watercolor clipart", "food_baked_goods"),
    ("watercolor fruit illustration", "food_fruits"),
    ("watercolor vegetable clipart", "food_vegetables"), # Added for variety

    # Style Keywords (Good variety, consistent with watercolor)
    ("boho watercolor floral clipart", "style_boho"),
    ("cottagecore watercolor clipart", "style_cottagecore"),
    ("whimsical botanical watercolor art", "style_whimsical"),
    ("rustic watercolor clipart", "style_rustic"), # Often pairs with boho/cottagecore
    ("modern watercolor clipart", "style_modern"), # For contemporary designs
    ("vintage watercolor art", "style_vintage"), # Could cover specific aesthetics

    # Bundles (More descriptive)
    ("watercolor clipart mega bundle", "bundles_clipart"),
    ("watercolor digital download bundle", "bundles_general"),
    ("watercolor pattern bundle", "bundles_patterns"), # Specific pattern bundles

    # Additional General Terms (Broaden reach)
    ("digital download", "product_type"),
    ("png graphics", "file_format"),
    ("instant download", "delivery_method"),
    ("hand painted watercolor", "creation_method"),
    ("high resolution clipart", "quality_descriptor"),
    ("transparent background png", "file_feature"),
]

    count = 0
    for keyword, category in seed_keywords:
        db.add_keyword(keyword, category)
        count += 1

    console.print(f"✅ Seeded {count} keywords across categories", style="green")

    # Prompt to add competitors
    console.print("\n📝 Add competitor shops with:", style="yellow")
    console.print('   python main.py add-competitor SHOP_ID "Shop Name" "notes"')


@cli.command("db-upgrade")
@click.argument("revision", default="head")
def db_upgrade(revision):
    """Run pending database migrations (default: upgrade to latest)."""
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(alembic_cfg, revision)
    console.print(f"Database upgraded to {revision}", style="green")


@cli.command("db-downgrade")
@click.argument("revision", default="-1")
def db_downgrade(revision):
    """Roll back database migrations (default: one step back)."""
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.downgrade(alembic_cfg, revision)
    console.print(f"Database downgraded to {revision}", style="green")


@cli.command("add-competitor")
@click.argument("shop_id")
@click.argument("shop_name")
@click.argument("notes", default="")
def add_competitor(shop_id: str, shop_name: str, notes: str):
    """Add a competitor shop to monitor."""
    db_id = db.add_competitor(shop_id, shop_name, notes)
    console.print(f"✅ Added competitor: {shop_name} (db_id={db_id})", style="green")


@cli.command()
def research():
    """Run niche analysis on all tracked keywords."""
    keywords = db.get_active_keywords()
    if not keywords:
        console.print("No keywords found. Run 'init' first.", style="red")
        return

    console.print(f"Analyzing {len(keywords)} keywords...\n", style="cyan")
    finder = NicheFinder()
    results = finder.analyze_batch(keywords)

    # Display results table
    _show_opportunity_table(results)


@cli.command()
def trends():
    """Fetch and store Google Trends data for all keywords."""
    keywords = db.get_active_keywords()
    if not keywords:
        console.print("No keywords found. Run 'init' first.", style="red")
        return

    analyzer = TrendAnalyzer()
    kw_list = [kw["keyword"] for kw in keywords]
    kw_ids = {kw["keyword"]: kw["id"] for kw in keywords}

    console.print(
        f"Fetching Google Trends for {len(kw_list)} keywords...", style="cyan"
    )
    data = analyzer.get_interest_over_time(kw_list)

    if data.empty:
        console.print("No trend data returned.", style="yellow")
        return

    # Save to DB
    records = []
    for keyword in data.columns:
        if keyword in kw_ids:
            for date, value in data[keyword].items():
                records.append((kw_ids[keyword], str(date.date()), int(value)))

    db.save_trend_batch(records)
    console.print(f"✅ Saved {len(records)} trend data points", style="green")


@cli.command()
def competitors():
    """Snapshot all competitor shops."""
    tracker = CompetitorTracker()
    results = tracker.snapshot_all()

    if results:
        table = Table(title="Competitor Snapshots")
        table.add_column("Shop", style="cyan")
        table.add_column("Sales", justify="right")
        table.add_column("Listings", justify="right")
        table.add_column("Avg Price", justify="right")

        for r in results:
            table.add_row(
                r.get("shop_name", "?"),
                str(r.get("total_sales", "?")),
                str(r.get("total_listings", "?")),
                f"${r.get('avg_price', 0):.2f}",
            )
        console.print(table)


@cli.command()
def discover():
    """Discover new keywords from seed terms."""
    keywords = db.get_active_keywords()
    seeds = [kw["keyword"] for kw in keywords]

    finder = NicheFinder()
    console.print(f"Discovering keywords from {len(seeds)} seeds...", style="cyan")
    raw_keywords = finder.discover_keywords(seeds)

    # Filter: relevance + blocklist
    blocklist = db.get_blocklist()
    relevant = _filter_relevant_keywords(raw_keywords, blocklist)

    console.print(
        f"\nFound {len(relevant)} relevant keywords out of {len(raw_keywords)} discovered.",
        style="green",
    )

    if not relevant:
        console.print("Nothing relevant to add.", style="yellow")
        return

    # Block the rejected ones so they don't reappear
    rejected = set(raw_keywords) - set(relevant) - blocklist
    if rejected:
        db.add_to_blocklist_batch(rejected, reason="auto-filtered")
        logger.debug(f"Added {len(rejected)} auto-filtered keywords to blocklist")

    choice = click.prompt(
        "Add all, review first, or skip?",
        type=click.Choice(["all", "review", "skip"], case_sensitive=False),
        default="review",
    )

    if choice == "skip":
        console.print("Skipped.", style="yellow")
        return

    if choice == "all":
        for kw in relevant:
            db.add_keyword(kw, category="discovered")
        console.print(f"Added {len(relevant)} keywords", style="green")
        return

    # Paged review
    accepted, rejected_in_review = _review_keywords_paged(relevant)
    if accepted:
        for kw in accepted:
            db.add_keyword(kw, category="discovered")
        console.print(f"Added {len(accepted)} keywords", style="green")
    if rejected_in_review:
        db.add_to_blocklist_batch(rejected_in_review, reason="rejected")
        console.print(f"Blocked {len(rejected_in_review)} keywords from future discovery", style="dim")


@cli.command()
@click.argument("json_file", required=False)
@click.option("--dry", is_flag=True, help="Validate without uploading")
def upload(json_file: str | None, dry: bool):
    """Upload listings from a JSON file."""
    if not json_file:
        console.print(
            "Usage: python main.py upload listings.json [--dry]", style="yellow"
        )
        console.print("\nSee uploader/__init__.py for JSON format.", style="dim")
        return

    drafts = load_drafts_from_json(json_file)
    console.print(f"Loaded {len(drafts)} listings from {json_file}", style="cyan")

    uploader = ListingUploader()
    results = uploader.upload_batch(drafts, dry_run=dry)

    console.print(f"\n{'[DRY RUN] ' if dry else ''}Results:", style="bold")
    console.print(f"  ✅ Success: {len(results['success'])}")
    console.print(f"  ❌ Failed:  {len(results['failed'])}")


@cli.command()
@click.argument("keyword")
def analyze(keyword):
    """Deep analysis of a single keyword with verdict, signals, and HTML report."""
    analyzer = KeywordAnalyzer()
    analyzer.run(keyword)


@cli.command()
@click.option("--html", is_flag=True, help="Generate HTML report with Plotly chart")
def report(html):
    """Show top niche opportunities from latest analysis."""
    opportunities = db.get_top_opportunities(limit=20)
    if not opportunities:
        console.print("No data yet. Run 'research' first.", style="yellow")
        return

    rows = [dict(o) for o in opportunities]

    if html:
        _generate_report_html(rows)
    else:
        _show_opportunity_table(rows)


@cli.command()
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def cleanup(yes):
    """Delete niche_scores rows from failed API calls (zero listings and zero price)."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM niche_scores WHERE etsy_listing_count = 0 AND avg_price = 0"
        ).fetchone()
        count = row["cnt"] if row else 0

    if count == 0:
        console.print("No failed rows to clean up.", style="yellow")
        return

    console.print(f"Found {count} rows with zero listings and zero price.", style="cyan")
    if not yes and not click.confirm("Delete these rows?"):
        console.print("Aborted.", style="yellow")
        return

    with db.connection() as conn:
        conn.execute(
            "DELETE FROM niche_scores WHERE etsy_listing_count = 0 AND avg_price = 0"
        )
    console.print(f"Deleted {count} rows from niche_scores", style="green")


@cli.command()
@click.option("--html", is_flag=True, help="Generate HTML scatter plot report")
@click.option("--discover", is_flag=True, help="Run keyword discovery on top 5 gap keywords")
def gaps(html, discover):
    """Find gap keywords: rising demand + low Etsy supply."""
    from math import log10
    from datetime import datetime, timedelta

    keywords = db.get_active_keywords()
    if not keywords:
        console.print("No keywords found. Run 'init' first.", style="red")
        return

    # 3-month boundary
    now = datetime.utcnow()
    three_months_ago = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    six_months_ago = (now - timedelta(days=180)).strftime("%Y-%m-%d")

    results = []
    for kw in keywords:
        keyword_id = kw["id"]

        # Pull trend data from DB
        trend_rows = db.get_trend_data_for_keyword(keyword_id)
        if not trend_rows:
            continue

        # Split into previous 3 months and last 3 months
        prev_scores = [
            r["interest_score"] for r in trend_rows
            if six_months_ago <= r["date"] < three_months_ago and r["interest_score"] is not None
        ]
        recent_scores = [
            r["interest_score"] for r in trend_rows
            if r["date"] >= three_months_ago and r["interest_score"] is not None
        ]

        if not prev_scores or not recent_scores:
            continue

        prev_avg = sum(prev_scores) / len(prev_scores)
        recent_avg = sum(recent_scores) / len(recent_scores)

        if prev_avg == 0:
            trend_growth_pct = 100.0 if recent_avg > 0 else 0.0
        else:
            trend_growth_pct = round(((recent_avg - prev_avg) / prev_avg) * 100, 1)

        # Listing count from latest niche_scores
        niche = db.get_latest_niche_score(keyword_id)
        listing_count = niche["etsy_listing_count"] if niche else 0

        # Gap score
        denominator = log10(listing_count + 1) if listing_count > 0 else 1
        gap_score = round(trend_growth_pct / denominator, 2) if denominator > 0 else 0

        # Classification
        if trend_growth_pct < 0:
            classification = "Declining interest"
        elif trend_growth_pct > 0 and listing_count > 100000:
            classification = "Already saturated"
        elif trend_growth_pct > 30 and listing_count < 10000:
            classification = "Emerging gap"
        elif trend_growth_pct > 15 and listing_count < 50000:
            classification = "Growing demand"
        else:
            classification = "Balanced"

        row = {
            "keyword": kw["keyword"],
            "keyword_id": keyword_id,
            "gap_score": gap_score,
            "trend_growth_pct": trend_growth_pct,
            "listing_count": listing_count,
            "classification": classification,
        }
        results.append(row)

        # Save to DB
        db.save_gap_score(keyword_id, trend_growth_pct, listing_count, gap_score, classification)

    if not results:
        console.print("No gap data. Run 'trends' and 'research' first.", style="yellow")
        return

    results.sort(key=lambda r: r["gap_score"], reverse=True)

    if html:
        _generate_gaps_html(results)
    else:
        _show_gaps_table(results)

    if discover:
        _discover_from_gaps(results[:5])


@cli.command()
def daily():
    """
    Run the full daily pipeline:
    1. Fetch Google Trends
    2. Analyze niche scores
    3. Snapshot competitors
    """
    console.print("🚀 Running daily pipeline...\n", style="bold cyan")

    # Step 1: Trends
    console.print("[1/3] Fetching Google Trends...", style="cyan")
    from click.testing import CliRunner

    runner = CliRunner()
    runner.invoke(trends)

    # Step 2: Niche research
    console.print("\n[2/3] Running niche analysis...", style="cyan")
    runner.invoke(research)

    # Step 3: Competitors
    console.print("\n[3/3] Snapshotting competitors...", style="cyan")
    runner.invoke(competitors)

    console.print("\n✅ Daily pipeline complete!", style="green bold")


# ──────────────────────────────────────────────
#  Discovery Filtering Helpers
# ──────────────────────────────────────────────


def _filter_relevant_keywords(keywords, blocklist):
    """Keep only keywords relevant to digital art products."""
    filtered = []
    for kw in keywords:
        kw_lower = kw.lower()

        # Skip blocklisted
        if kw_lower in blocklist:
            continue

        # Skip irrelevant terms
        if _IRRELEVANT_PATTERN.search(kw_lower):
            continue

        # Skip "fabric" unless "fabric pattern"
        if _FABRIC_PATTERN.search(kw_lower) and not _FABRIC_OK_PATTERN.search(kw_lower):
            continue

        # Must contain at least one relevance term
        if not any(term in kw_lower for term in _RELEVANCE_TERMS):
            continue

        filtered.append(kw)

    return filtered


def _review_keywords_paged(keywords, page_size=20):
    """Review keywords in pages of 20. Returns (accepted, rejected) lists."""
    accepted = []
    rejected = []

    for page_start in range(0, len(keywords), page_size):
        page = keywords[page_start : page_start + page_size]
        page_num = page_start // page_size + 1
        total_pages = (len(keywords) + page_size - 1) // page_size

        console.print(f"\n--- Page {page_num}/{total_pages} ---", style="bold")
        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=4)
        table.add_column("Keyword", style="cyan")

        for i, kw in enumerate(page, page_start + 1):
            table.add_row(str(i), kw)
        console.print(table)

        choice = click.prompt(
            "Accept this page, reject, or done?",
            type=click.Choice(["accept", "reject", "done"], case_sensitive=False),
            default="accept",
        )

        if choice == "accept":
            accepted.extend(page)
        elif choice == "reject":
            rejected.extend(page)
        else:
            # "done" — accept nothing more, reject remaining unseen
            remaining = keywords[page_start + page_size :]
            rejected.extend(remaining)
            break

    return accepted, rejected


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────


def _show_opportunity_table(results: list[dict]):
    """Display a rich table of niche opportunities."""
    table = Table(title="🎯 Niche Opportunity Scores")
    table.add_column("#", style="dim", width=3)
    table.add_column("Keyword", style="cyan", min_width=30)
    table.add_column("Score", justify="right", style="green bold")
    table.add_column("Trend", justify="right")
    table.add_column("Listings", justify="right")
    table.add_column("Avg Fav", justify="right")
    table.add_column("Avg Price", justify="right")

    for i, r in enumerate(results[:20], 1):
        score = r.get("opportunity_score", 0)
        style = "green" if score > 10 else ("yellow" if score > 5 else "red")
        table.add_row(
            str(i),
            r.get("keyword", "?"),
            f"[{style}]{score:.1f}[/{style}]",
            str(r.get("google_trend_score", "?")),
            str(r.get("etsy_listing_count", "?")),
            f"{r.get('avg_favorites', 0):.0f}",
            f"${r.get('avg_price', 0):.2f}",
        )

    console.print(table)


def _generate_report_html(rows: list[dict]):
    """Generate an HTML report with a Plotly bar chart and styled data table."""
    import webbrowser
    import plotly.graph_objects as go

    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "niche_report.html"

    # Sort ascending so highest score is at the top of horizontal bar chart
    sorted_rows = sorted(rows, key=lambda r: r.get("opportunity_score", 0))

    keywords = [r.get("keyword", "?") for r in sorted_rows]
    scores = [r.get("opportunity_score", 0) for r in sorted_rows]
    colors = [
        "#2ECC71" if s >= 10 else "#F39C12" if s >= 5 else "#E74C3C"
        for s in scores
    ]

    fig = go.Figure(go.Bar(
        x=scores,
        y=keywords,
        orientation="h",
        marker_color=colors,
        text=[f"{s:.1f}" for s in scores],
        textposition="outside",
    ))
    fig.update_layout(
        title="Top 20 Keywords by Opportunity Score",
        xaxis_title="Opportunity Score",
        height=max(500, len(rows) * 32),
        margin={"l": 250},
        template="plotly_white",
    )
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    # Build HTML table (use original descending order)
    table_rows = ""
    for i, r in enumerate(rows, 1):
        score = r.get("opportunity_score", 0)
        color = "#2ECC71" if score >= 10 else "#F39C12" if score >= 5 else "#E74C3C"
        table_rows += f"""<tr>
            <td>{i}</td>
            <td>{r.get('keyword', '?')}</td>
            <td style="color:{color};font-weight:bold">{score:.1f}</td>
            <td>{r.get('google_trend_score', '?')}</td>
            <td>{r.get('etsy_listing_count', '?'):,}</td>
            <td>{r.get('avg_favorites', 0):.0f}</td>
            <td>${r.get('avg_price', 0):.2f}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Niche Opportunity Report</title>
<style>
    body {{ font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; }}
    h1 {{ color: #2C3E50; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
    th {{ background: #2C3E50; color: white; padding: 10px 14px; text-align: left; }}
    td {{ padding: 8px 14px; border-bottom: 1px solid #ddd; }}
    tr:hover {{ background: #f5f5f5; }}
</style>
</head>
<body>
<h1>Niche Opportunity Report</h1>
{chart_html}
<h2>Detailed Metrics</h2>
<table>
<tr><th>#</th><th>Keyword</th><th>Score</th><th>Trend</th><th>Listings</th><th>Avg Fav</th><th>Avg Price</th></tr>
{table_rows}
</table>
</body>
</html>"""

    report_path.write_text(html, encoding="utf-8")
    console.print(f"Report saved: {report_path}", style="green")
    webbrowser.open(report_path.as_uri())


def _show_gaps_table(results):
    """Display gap analysis as a Rich table."""
    classification_icons = {
        "Emerging gap": "\U0001f680 Emerging gap",
        "Growing demand": "\U0001f4c8 Growing demand",
        "Balanced": "\u2696\ufe0f Balanced",
        "Declining interest": "\U0001f4c9 Declining interest",
        "Already saturated": "\U0001f525 Already saturated",
    }

    table = Table(title="Gap Analysis: Rising Demand + Low Supply")
    table.add_column("#", style="dim", width=3)
    table.add_column("Keyword", style="cyan", min_width=30)
    table.add_column("Gap Score", justify="right", style="bold")
    table.add_column("Trend Growth", justify="right")
    table.add_column("Listings", justify="right")
    table.add_column("Classification")

    for i, r in enumerate(results[:30], 1):
        growth = r["trend_growth_pct"]
        growth_style = "green" if growth > 15 else ("yellow" if growth >= 0 else "red")
        cls_label = classification_icons.get(r["classification"], r["classification"])

        gap = r["gap_score"]
        gap_style = "green" if gap > 10 else ("yellow" if gap > 3 else "dim")

        table.add_row(
            str(i),
            r["keyword"],
            f"[{gap_style}]{gap:.1f}[/{gap_style}]",
            f"[{growth_style}]{growth:+.1f}%[/{growth_style}]",
            f"{r['listing_count']:,}",
            cls_label,
        )

    console.print(table)


def _generate_gaps_html(results):
    """Generate HTML scatter plot for gap analysis."""
    import webbrowser
    import plotly.graph_objects as go

    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "gap_analysis.html"

    color_map = {
        "Emerging gap": "#2ECC71",
        "Growing demand": "#3498DB",
        "Balanced": "#95A5A6",
        "Declining interest": "#E74C3C",
        "Already saturated": "#E67E22",
    }

    fig = go.Figure()

    for cls_name, color in color_map.items():
        group = [r for r in results if r["classification"] == cls_name]
        if not group:
            continue

        listings = [max(r["listing_count"], 1) for r in group]
        growths = [r["trend_growth_pct"] for r in group]
        gaps = [max(abs(r["gap_score"]), 2) for r in group]
        labels = [r["keyword"] for r in group]

        fig.add_trace(go.Scatter(
            x=listings,
            y=growths,
            mode="markers+text",
            marker={"size": gaps, "color": color, "sizemode": "area", "sizeref": max(max(gaps), 1) / 600, "opacity": 0.7},
            text=labels,
            textposition="top center",
            textfont={"size": 9},
            name=cls_name,
            hovertemplate="%{text}<br>Listings: %{x:,}<br>Growth: %{y:.1f}%<extra></extra>",
        ))

    # Golden opportunity quadrant highlight
    fig.add_shape(
        type="rect", x0=1, x1=10000, y0=15, y1=200,
        fillcolor="rgba(46,204,113,0.08)", line={"width": 0},
        layer="below",
    )
    fig.add_annotation(
        x=1.5, y=180, text="Golden Opportunity Zone",
        showarrow=False, font={"size": 12, "color": "#2ECC71"},
        xref="x", yref="y",
    )

    fig.update_layout(
        title="Gap Analysis: Trend Growth vs Etsy Supply",
        xaxis_title="Listing Count (log scale)",
        yaxis_title="Trend Growth %",
        xaxis_type="log",
        height=700,
        template="plotly_white",
        legend={"title": "Classification"},
    )

    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    # Data table
    table_rows = ""
    for i, r in enumerate(results, 1):
        color = color_map.get(r["classification"], "#333")
        table_rows += f"""<tr>
            <td>{i}</td>
            <td>{r['keyword']}</td>
            <td style="font-weight:bold">{r['gap_score']:.1f}</td>
            <td>{r['trend_growth_pct']:+.1f}%</td>
            <td>{r['listing_count']:,}</td>
            <td style="color:{color}">{r['classification']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Gap Analysis Report</title>
<style>
    body {{ font-family: Arial, sans-serif; max-width: 1100px; margin: 0 auto; padding: 20px; }}
    h1 {{ color: #2C3E50; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
    th {{ background: #2C3E50; color: white; padding: 10px 14px; text-align: left; }}
    td {{ padding: 8px 14px; border-bottom: 1px solid #ddd; }}
    tr:hover {{ background: #f5f5f5; }}
</style>
</head>
<body>
<h1>Gap Analysis: Rising Demand + Low Supply</h1>
{chart_html}
<h2>Detailed Data</h2>
<table>
<tr><th>#</th><th>Keyword</th><th>Gap Score</th><th>Trend Growth</th><th>Listings</th><th>Classification</th></tr>
{table_rows}
</table>
</body>
</html>"""

    report_path.write_text(html, encoding="utf-8")
    console.print(f"Report saved: {report_path}", style="green")
    webbrowser.open(report_path.as_uri())


def _discover_from_gaps(top_gaps):
    """Run keyword discovery on top gap keywords and save results."""
    seeds = [r["keyword"] for r in top_gaps]
    console.print(f"\nDiscovering long-tail variations for top {len(seeds)} gap keywords...", style="cyan")

    existing = {kw["keyword"] for kw in db.get_active_keywords()}
    finder = NicheFinder()
    all_discovered = finder.discover_keywords(seeds, existing_keywords=existing)
    raw_new = sorted(set(all_discovered) - existing)

    if not raw_new:
        console.print("No new keywords discovered.", style="yellow")
        return

    # Apply relevance filter + blocklist
    blocklist = db.get_blocklist()
    relevant = _filter_relevant_keywords(raw_new, blocklist)

    # Auto-block the irrelevant ones
    rejected = set(raw_new) - set(relevant) - blocklist
    if rejected:
        db.add_to_blocklist_batch(rejected, reason="auto-filtered")

    console.print(
        f"\nFound {len(relevant)} relevant keywords out of {len(raw_new)} discovered.",
        style="green",
    )

    if not relevant:
        console.print("Nothing relevant to add.", style="yellow")
        return

    if click.confirm(f"Add {len(relevant)} keywords with category 'gap-discovered'?"):
        for kw in relevant:
            db.add_keyword(kw, category="gap-discovered")
        console.print(f"Added {len(relevant)} keywords", style="green")


if __name__ == "__main__":
    cli()
