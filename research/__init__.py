"""
Keyword research & trend analysis pipeline.

Data sources:
  - Google Trends (via pytrends) — demand signal & seasonality
  - Etsy API — supply signal (listing count, competition)
  - Etsy search autocomplete — long-tail keyword discovery

Combines these into a niche opportunity score.
"""

import time
import json
from datetime import datetime

import pandas as pd
from pytrends.request import TrendReq
from loguru import logger

from db import db
from etsy_api import etsy_client


class TrendAnalyzer:
    """
    Collects Google Trends data for tracked keywords.
    Handles pytrends rate limiting and batch processing.
    """

    def __init__(self):
        self.pytrends = TrendReq(hl="en-US", tz=360)

    def get_interest_over_time(
        self,
        keywords: list[str],
        timeframe: str = "today 12-m",
    ) -> pd.DataFrame:
        """
        Fetch Google Trends interest over time.

        Args:
            keywords: Up to 5 keywords per batch (Google limit).
            timeframe: e.g. 'today 12-m', 'today 3-m', '2024-01-01 2024-12-31'

        Returns:
            DataFrame with dates as index and keyword columns (0-100 scale).
        """
        # pytrends allows max 5 keywords per request
        batch_size = 5
        all_data = pd.DataFrame()

        for i in range(0, len(keywords), batch_size):
            batch = keywords[i:i + batch_size]
            logger.debug(f"Fetching trends for: {batch}")

            try:
                self.pytrends.build_payload(batch, timeframe=timeframe)
                data = self.pytrends.interest_over_time()

                if not data.empty:
                    data = data.drop(columns=["isPartial"], errors="ignore")
                    all_data = pd.concat([all_data, data], axis=1)

                # Respect rate limits
                time.sleep(2)

            except Exception as e:
                logger.warning(f"Trends API error for {batch}: {e}")
                time.sleep(10)  # Back off on error

        return all_data

    def get_related_queries(self, keyword: str) -> dict:
        """
        Get related queries for keyword discovery.
        Returns dict with 'rising' and 'top' DataFrames.
        """
        try:
            self.pytrends.build_payload([keyword])
            related = self.pytrends.related_queries()
            return related.get(keyword, {})
        except Exception as e:
            logger.warning(f"Related queries error for '{keyword}': {e}")
            return {}

    def detect_seasonality(self, keyword: str) -> dict:
        """
        Analyze 5 years of data to detect seasonal patterns.
        Returns dict with peak months and trough months.
        """
        try:
            self.pytrends.build_payload([keyword], timeframe="today 5-y")
            data = self.pytrends.interest_over_time()

            if data.empty:
                return {"peak_months": [], "trough_months": [], "is_seasonal": False}

            # Group by month and find averages
            monthly = data[keyword].groupby(data.index.month).mean()
            overall_mean = monthly.mean()
            threshold = overall_mean * 0.3  # 30% above/below mean

            peak_months = monthly[monthly > overall_mean + threshold].index.tolist()
            trough_months = monthly[monthly < overall_mean - threshold].index.tolist()

            return {
                "peak_months": peak_months,
                "trough_months": trough_months,
                "is_seasonal": len(peak_months) > 0,
                "monthly_averages": monthly.to_dict(),
            }

        except Exception as e:
            logger.warning(f"Seasonality analysis error for '{keyword}': {e}")
            return {"peak_months": [], "trough_months": [], "is_seasonal": False}


class EtsyResearcher:
    """
    Analyzes Etsy marketplace data for niche research.
    Uses the Etsy API to gauge supply and competition.
    """

    def __init__(self):
        self.client = etsy_client

    def get_keyword_metrics(self, keyword: str) -> dict:
        """
        Get supply-side metrics for a keyword from Etsy.

        Returns:
            dict with listing_count, avg_price, avg_favorites, price_range, top_tags
        """
        try:
            data = self.client.search_listings(keyword, limit=100)
            results = data.get("results", [])
            total_count = data.get("count", 0)

            if not results:
                return {
                    "listing_count": 0,
                    "avg_price": 0,
                    "avg_favorites": 0,
                    "price_range": (0, 0),
                    "top_tags": [],
                }

            prices = [
                float(r["price"]["amount"]) / r["price"]["divisor"]
                for r in results
                if "price" in r
            ]
            favorites = [r.get("num_favorers", 0) for r in results]

            # Collect all tags to find most common
            all_tags = []
            for r in results:
                all_tags.extend(r.get("tags", []))
            tag_counts = {}
            for tag in all_tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            top_tags = sorted(tag_counts, key=tag_counts.get, reverse=True)[:20]

            return {
                "listing_count": total_count,
                "avg_price": sum(prices) / len(prices) if prices else 0,
                "avg_favorites": sum(favorites) / len(favorites) if favorites else 0,
                "price_range": (min(prices), max(prices)) if prices else (0, 0),
                "top_tags": top_tags,
            }

        except Exception as e:
            logger.error(f"Etsy research error for '{keyword}': {e}")
            return {"listing_count": 0, "avg_price": 0, "avg_favorites": 0}

    def get_autocomplete_suggestions(self, prefix: str) -> list[str]:
        """
        Get Etsy search autocomplete suggestions.
        This reveals what real buyers are typing.

        Note: This uses a public endpoint, not the official API.
        Use responsibly with delays between requests.
        """
        import requests as req

        try:
            url = "https://www.etsy.com/api/v3/ajax/search/suggest"
            params = {"q": prefix, "type": "all"}
            headers = {"User-Agent": "Mozilla/5.0"}
            response = req.get(url, params=params, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                return [s.get("query", "") for s in data.get("queries", [])]
        except Exception as e:
            logger.debug(f"Autocomplete error for '{prefix}': {e}")

        return []


class NicheFinder:
    """
    Combines trend data + Etsy metrics to score niche opportunities.

    Opportunity Score formula:
        score = (demand_signal * engagement_signal) / (competition_signal + 1)

    Where:
        demand_signal   = Google Trends interest (0-100)
        engagement_signal = average favorites per listing
        competition_signal = number of existing Etsy listings
    """

    def __init__(self):
        self.trends = TrendAnalyzer()
        self.etsy = EtsyResearcher()

    def analyze_keyword(self, keyword: str, keyword_id: int | None = None) -> dict:
        """
        Full niche analysis for a single keyword.
        Returns comprehensive metrics dict.
        """
        logger.info(f"Analyzing niche: '{keyword}'")

        # 1. Google Trends (demand signal)
        trend_data = self.trends.get_interest_over_time([keyword])
        trend_score = 0
        if not trend_data.empty and keyword in trend_data.columns:
            trend_score = int(trend_data[keyword].iloc[-1])  # Latest value

        # 2. Etsy metrics (supply signal)
        etsy_metrics = self.etsy.get_keyword_metrics(keyword)
        time.sleep(1)  # Rate limit courtesy

        # 3. Calculate opportunity score
        demand = max(trend_score, 1)
        engagement = max(etsy_metrics.get("avg_favorites", 0), 1)
        competition = etsy_metrics.get("listing_count", 0)

        # Higher score = better opportunity
        # Formula balances demand, engagement, and competition
        opportunity_score = round(
            (demand * (engagement ** 0.5)) / (competition ** 0.3 + 1),
            2,
        )

        result = {
            "keyword": keyword,
            "google_trend_score": trend_score,
            "etsy_listing_count": competition,
            "avg_favorites": etsy_metrics.get("avg_favorites", 0),
            "avg_price": etsy_metrics.get("avg_price", 0),
            "price_range": etsy_metrics.get("price_range", (0, 0)),
            "top_tags": etsy_metrics.get("top_tags", []),
            "competition_ratio": round(competition / max(demand, 1), 2),
            "opportunity_score": opportunity_score,
        }

        # 4. Save to database if keyword_id provided
        if keyword_id:
            db.save_niche_score(keyword_id, **result)

        logger.info(
            f"  → Score: {opportunity_score:.1f} | "
            f"Trend: {trend_score} | "
            f"Listings: {competition} | "
            f"Avg price: ${etsy_metrics.get('avg_price', 0):.2f}"
        )

        return result

    def analyze_batch(self, keywords: list[dict]) -> list[dict]:
        """
        Analyze multiple keywords.
        keywords: list of {'id': int, 'keyword': str} dicts.
        """
        results = []
        for kw in keywords:
            result = self.analyze_keyword(kw["keyword"], keyword_id=kw.get("id"))
            results.append(result)
            time.sleep(2)  # Be gentle with APIs

        # Sort by opportunity score
        results.sort(key=lambda x: x["opportunity_score"], reverse=True)
        return results

    def discover_keywords(self, seed_keywords: list[str]) -> list[str]:
        """
        Expand seed keywords using Etsy autocomplete + Google related queries.
        Great for finding long-tail niche terms.
        """
        discovered = set()

        for seed in seed_keywords:
            # Etsy autocomplete
            suggestions = self.etsy.get_autocomplete_suggestions(seed)
            discovered.update(suggestions)
            time.sleep(1)

            # Google related queries
            related = self.trends.get_related_queries(seed)
            if "rising" in related and related["rising"] is not None:
                rising = related["rising"]["query"].tolist()
                discovered.update(rising)
            if "top" in related and related["top"] is not None:
                top = related["top"]["query"].tolist()
                discovered.update(top)
            time.sleep(2)

        # Remove seeds from discovered
        discovered -= set(seed_keywords)
        logger.info(f"Discovered {len(discovered)} new keywords from {len(seed_keywords)} seeds")
        return sorted(discovered)
