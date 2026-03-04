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

import sys
import json

import click
from rich.console import Console
from rich.table import Table
from loguru import logger

from config import settings, PROJECT_ROOT
from db import db
from research import NicheFinder, TrendAnalyzer
from monitor import CompetitorTracker
from uploader import ListingUploader, load_drafts_from_json

console = Console()


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
    """🎨 Etsy Automation Pipeline for WatercolorAnn"""
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
        console.print(f'ETSY_ACCESS_TOKEN={tokens["access_token"]}')
        console.print(f'ETSY_REFRESH_TOKEN={tokens["refresh_token"]}')


@cli.command()
def init():
    """Initialize database and seed with your niche keywords."""
    db.init_schema()
    console.print("✅ Database initialized", style="green")

    # Seed keywords relevant to WatercolorAnn
    seed_keywords = [
        # Core products
        ("watercolor clipart", "clipart"),
        ("botanical clipart", "clipart"),
        ("floral clipart png", "clipart"),
        ("watercolor seamless pattern", "patterns"),
        ("botanical seamless pattern", "patterns"),
        ("floral digital paper", "patterns"),
        # Nature subjects
        ("watercolor birds clipart", "birds"),
        ("watercolor insects clipart", "insects"),
        ("watercolor animals clipart", "animals"),
        ("butterfly clipart png", "insects"),
        ("wildflower clipart", "clipart"),
        # Use-case keywords
        ("wedding invitation clipart", "use-case"),
        ("scrapbook digital elements", "use-case"),
        ("commercial use clipart", "use-case"),
        ("printable wall art botanical", "use-case"),
        # Food themes
        ("watercolor food clipart", "food"),
        ("artisan bread clipart", "food"),
        ("watercolor fruit illustration", "food"),
        # Competitor-style terms
        ("boho floral clipart", "style"),
        ("cottagecore clipart", "style"),
        ("whimsical botanical art", "style"),
        # Bundles
        ("clipart mega bundle", "bundles"),
        ("digital download bundle", "bundles"),
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

    console.print(f"Fetching Google Trends for {len(kw_list)} keywords...", style="cyan")
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
    seeds = [kw["keyword"] for kw in keywords[:10]]  # Use first 10 as seeds

    finder = NicheFinder()
    console.print(f"Discovering keywords from {len(seeds)} seeds...", style="cyan")
    new_keywords = finder.discover_keywords(seeds)

    console.print(f"\n🔍 Found {len(new_keywords)} new keyword ideas:\n", style="green")
    for kw in new_keywords[:30]:  # Show first 30
        console.print(f"  → {kw}")

    if click.confirm("\nAdd these to your tracked keywords?"):
        for kw in new_keywords:
            db.add_keyword(kw, category="discovered")
        console.print(f"✅ Added {len(new_keywords)} keywords", style="green")


@cli.command()
@click.argument("json_file", required=False)
@click.option("--dry", is_flag=True, help="Validate without uploading")
def upload(json_file: str | None, dry: bool):
    """Upload listings from a JSON file."""
    if not json_file:
        console.print("Usage: python main.py upload listings.json [--dry]", style="yellow")
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
def report():
    """Show top niche opportunities from latest analysis."""
    opportunities = db.get_top_opportunities(limit=20)
    if not opportunities:
        console.print("No data yet. Run 'research' first.", style="yellow")
        return

    _show_opportunity_table(
        [dict(o) for o in opportunities]
    )


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


if __name__ == "__main__":
    cli()
