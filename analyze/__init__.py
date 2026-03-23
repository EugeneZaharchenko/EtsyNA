"""
Single-keyword deep analysis.

Fetches live data from Google Trends and Etsy, computes an opportunity score
with a hybrid verdict + contextual signals, saves to DB, and generates
a Plotly HTML report.
"""

import json
import math
import re
from datetime import date

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from loguru import logger
from rich.console import Console
from rich.table import Table

from config import PROJECT_ROOT
from db import db
from research import TrendAnalyzer, EtsyResearcher

console = Console()

MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


# ──────────────────────────────────────────────
#  Pure Functions
# ──────────────────────────────────────────────


def compute_opportunity_score(demand, engagement, competition):
    """Shared formula. demand/engagement floored at 1."""
    demand = max(demand, 1)
    engagement = max(engagement, 1)
    return round((demand * math.sqrt(engagement)) / (competition ** 0.3 + 1), 2)


def compute_verdict(score, trend_data, etsy_metrics, seasonality):
    """
    Returns (verdict_str, signals_list).

    Args:
        score: opportunity score (float)
        trend_data: DataFrame with keyword column (12-month weekly)
        etsy_metrics: dict with listing_count, avg_price, avg_favorites
        seasonality: dict with monthly_averages from detect_seasonality()
    """
    # Primary verdict
    if score >= 10:
        verdict = "🟢 Good niche"
    elif score >= 5:
        verdict = "🟡 Moderate — needs differentiation"
    else:
        verdict = "🔴 Tough market"

    signals = []

    # Trend direction: split 12-month data in half
    if trend_data is not None and not trend_data.empty:
        col = trend_data.columns[0] if len(trend_data.columns) > 0 else None
        if col is not None:
            values = trend_data[col].values
            midpoint = len(values) // 2
            if midpoint > 0:
                first_half_avg = values[:midpoint].mean()
                second_half_avg = values[midpoint:].mean()
                if first_half_avg > 0:
                    change = (second_half_avg - first_half_avg) / first_half_avg
                    if change >= 0.2:
                        signals.append("📈 Rising trend")
                    elif change <= -0.2:
                        signals.append("📉 Declining trend")

    # Seasonality: peak >= 3x trough from monthly averages
    monthly_avgs = seasonality.get("monthly_averages", {})
    if monthly_avgs:
        avg_values = list(monthly_avgs.values())
        peak = max(avg_values)
        trough = min(avg_values)
        if trough > 0 and peak >= 3 * trough:
            signals.append("🎄 Highly seasonal")

    # Price signals
    avg_price = etsy_metrics.get("avg_price", 0)
    if avg_price > 10:
        signals.append("💰 Premium pricing possible")
    elif avg_price < 3 and avg_price > 0:
        signals.append("⚠️ Price race to bottom")

    # Competition signals
    listing_count = etsy_metrics.get("listing_count", 0)
    if listing_count < 5000:
        signals.append("🏆 Low competition")
    elif listing_count > 100000:
        signals.append("🔥 Oversaturated")

    # Engagement signals
    avg_favorites = etsy_metrics.get("avg_favorites", 0)
    if avg_favorites > 150:
        signals.append("💎 High engagement")
    elif avg_favorites < 20:
        signals.append("👻 Low engagement")

    return verdict, signals


def _slugify(keyword):
    """Convert keyword to URL-safe slug."""
    slug = keyword.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    return slug


# ──────────────────────────────────────────────
#  KeywordAnalyzer
# ──────────────────────────────────────────────


class KeywordAnalyzer:
    """Deep analysis for a single keyword."""

    def __init__(self):
        self.trends = TrendAnalyzer()
        self.etsy = EtsyResearcher()

    def run(self, keyword):
        """
        Full analysis pipeline for a keyword.

        Returns dict with all metrics, verdict, signals, and report path.
        """
        logger.info(f"Starting deep analysis for: '{keyword}'")

        # 1. Ensure keyword exists in DB
        keyword_id = db.add_keyword(keyword)

        # 2. Google Trends (12-month)
        trend_data = None
        trend_score = 0
        try:
            trend_data = self.trends.get_interest_over_time([keyword], "today 12-m")
            if not trend_data.empty and keyword in trend_data.columns:
                trend_score = int(trend_data[keyword].iloc[-1])
        except Exception as e:
            logger.warning(f"Google Trends failed for '{keyword}': {e}")

        # 3. Seasonality (5-year)
        seasonality = self.trends.detect_seasonality(keyword)

        # 4. Etsy metrics
        etsy_metrics = self.etsy.get_keyword_metrics(keyword)

        # 5. Opportunity score
        demand = trend_score
        engagement = etsy_metrics.get("avg_favorites", 0)
        competition = etsy_metrics.get("listing_count", 0)
        score = compute_opportunity_score(demand, engagement, competition)

        # 6. Verdict + signals
        verdict, signals = compute_verdict(score, trend_data, etsy_metrics, seasonality)

        # 7. Save to DB
        db.save_niche_score(
            keyword_id,
            etsy_listing_count=competition,
            avg_favorites=engagement,
            avg_price=etsy_metrics.get("avg_price", 0),
            google_trend_score=trend_score,
            competition_ratio=round(competition / max(demand, 1), 2),
            opportunity_score=score,
            verdict=verdict,
            signals=json.dumps(signals),
        )

        # 8. Print Rich summary
        self._print_summary(keyword, verdict, signals, score, trend_score, etsy_metrics)

        # 9. Generate Plotly HTML report
        report_path = self._generate_report(
            keyword, verdict, signals, score, trend_score,
            trend_data, seasonality, etsy_metrics,
        )

        return {
            "keyword": keyword,
            "keyword_id": keyword_id,
            "opportunity_score": score,
            "verdict": verdict,
            "signals": signals,
            "google_trend_score": trend_score,
            "etsy_metrics": etsy_metrics,
            "seasonality": seasonality,
            "report_path": str(report_path) if report_path else None,
        }

    def _print_summary(self, keyword, verdict, signals, score, trend_score, etsy_metrics):
        """Rich terminal output."""
        console.print()
        console.rule(f"  Keyword: {keyword}  ", style="bold cyan")
        console.print()
        console.print(f"  Verdict: {verdict} (score: {score})", style="bold")

        if signals:
            console.print(f"  Signals: {', '.join(signals)}")

        console.print()

        table = Table(show_header=True, header_style="bold")
        table.add_column("Metric", min_width=16)
        table.add_column("Value", justify="right")

        table.add_row("Google Trend", str(trend_score))
        table.add_row("Listings", f"{etsy_metrics.get('listing_count', 0):,}")
        table.add_row("Avg Price", f"${etsy_metrics.get('avg_price', 0):.2f}")

        price_range = etsy_metrics.get("price_range", (0, 0))
        table.add_row("Price Range", f"${price_range[0]:.0f} – ${price_range[1]:.0f}")
        table.add_row("Avg Favorites", f"{etsy_metrics.get('avg_favorites', 0):.0f}")

        console.print(table)

        top_tags = etsy_metrics.get("top_tags", [])
        if top_tags:
            console.print(f"\n  Top 15 Tags:")
            console.print(f"  {', '.join(top_tags[:15])}", style="dim")

    def _generate_report(self, keyword, verdict, signals, score, trend_score,
                         trend_data, seasonality, etsy_metrics):
        """Generate self-contained Plotly HTML report."""
        try:
            reports_dir = PROJECT_ROOT / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            slug = _slugify(keyword)
            today = date.today().isoformat()
            filename = f"analyze-{slug}-{today}.html"
            report_path = reports_dir / filename

            # Build charts
            fig = make_subplots(
                rows=3, cols=1,
                subplot_titles=(
                    "Google Trends (12 months)",
                    "Seasonality (5-year monthly averages)",
                    "Price Distribution",
                ),
                vertical_spacing=0.12,
            )

            # 1. Trends line chart
            if trend_data is not None and not trend_data.empty and keyword in trend_data.columns:
                fig.add_trace(
                    go.Scatter(
                        x=trend_data.index,
                        y=trend_data[keyword],
                        mode="lines",
                        name="Interest",
                        line={"color": "#4A90D9", "width": 2},
                    ),
                    row=1, col=1,
                )
            fig.update_yaxes(title_text="Interest (0-100)", row=1, col=1)

            # 2. Seasonality bar chart
            monthly_avgs = seasonality.get("monthly_averages", {})
            if monthly_avgs:
                months = sorted(monthly_avgs.keys())
                values = [monthly_avgs[m] for m in months]
                peak_val = max(values) if values else 0
                colors = [
                    "#E74C3C" if v == peak_val else "#4A90D9"
                    for v in values
                ]
                labels = [MONTH_NAMES[m - 1] for m in months]

                fig.add_trace(
                    go.Bar(
                        x=labels,
                        y=values,
                        marker_color=colors,
                        name="Monthly Avg",
                    ),
                    row=2, col=1,
                )
            fig.update_yaxes(title_text="Avg Interest", row=2, col=1)

            # 3. Price distribution histogram
            prices = etsy_metrics.get("prices", [])
            if prices:
                fig.add_trace(
                    go.Histogram(
                        x=prices,
                        nbinsx=30,
                        marker_color="#2ECC71",
                        name="Prices",
                    ),
                    row=3, col=1,
                )
                # Annotate min/median/max
                sorted_prices = sorted(prices)
                median_price = sorted_prices[len(sorted_prices) // 2]
                for val, label, color in [
                    (sorted_prices[0], "Min", "#E74C3C"),
                    (median_price, "Median", "#F39C12"),
                    (sorted_prices[-1], "Max", "#E74C3C"),
                ]:
                    fig.add_vline(
                        x=val, row=3, col=1,
                        line_dash="dash", line_color=color,
                        annotation_text=f"{label}: ${val:.2f}",
                    )
            fig.update_xaxes(title_text="Price ($)", row=3, col=1)
            fig.update_yaxes(title_text="Count", row=3, col=1)

            # Layout
            signals_str = ", ".join(signals) if signals else "None"
            tags = etsy_metrics.get("top_tags", [])[:15]
            tags_str = ", ".join(tags) if tags else "—"

            summary_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
                <h1 style="color: #2C3E50;">Analysis: {keyword}</h1>
                <h2>{verdict} (score: {score})</h2>
                <p><strong>Signals:</strong> {signals_str}</p>
                <table style="border-collapse: collapse; margin: 15px 0;">
                    <tr><td style="padding: 6px 16px; border: 1px solid #ddd;"><strong>Google Trend</strong></td>
                        <td style="padding: 6px 16px; border: 1px solid #ddd;">{trend_score}</td></tr>
                    <tr><td style="padding: 6px 16px; border: 1px solid #ddd;"><strong>Listings</strong></td>
                        <td style="padding: 6px 16px; border: 1px solid #ddd;">{etsy_metrics.get('listing_count', 0):,}</td></tr>
                    <tr><td style="padding: 6px 16px; border: 1px solid #ddd;"><strong>Avg Price</strong></td>
                        <td style="padding: 6px 16px; border: 1px solid #ddd;">${etsy_metrics.get('avg_price', 0):.2f}</td></tr>
                    <tr><td style="padding: 6px 16px; border: 1px solid #ddd;"><strong>Avg Favorites</strong></td>
                        <td style="padding: 6px 16px; border: 1px solid #ddd;">{etsy_metrics.get('avg_favorites', 0):.0f}</td></tr>
                </table>
                <p><strong>Top Tags:</strong> {tags_str}</p>
                <hr>
            </div>
            """

            fig.update_layout(
                height=1100,
                showlegend=False,
                title_text=f"Keyword Analysis: {keyword}",
                template="plotly_white",
            )

            # Write self-contained HTML
            chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
            full_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Analysis: {keyword}</title></head>
<body>
{summary_html}
{chart_html}
</body>
</html>"""

            report_path.write_text(full_html, encoding="utf-8")
            console.print(f"\n  📊 Report saved: {report_path}", style="green")
            return report_path

        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            console.print(f"\n  ⚠️ Report generation failed: {e}", style="yellow")
            return None
