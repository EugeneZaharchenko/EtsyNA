"""
Competitor shop tracker.
Monitors competing Etsy shops over time to detect:
  - New listings (what are they launching?)
  - Price changes (are they adjusting strategy?)
  - Sales velocity (estimated from favorites growth)
  - Tag/keyword strategy shifts
"""

import json
import time
from datetime import datetime

from loguru import logger

from db import db
from etsy_api import etsy_client


class CompetitorTracker:
    """
    Tracks competitor shops and stores daily snapshots.
    """

    def __init__(self):
        self.client = etsy_client

    def snapshot_shop(self, shop_id: str, db_shop_id: int) -> dict:
        """
        Take a snapshot of a competitor's public metrics.
        """
        try:
            shop_info = self.client.get_shop_info(shop_id)
            listings = self.client.get_shop_listings(shop_id, state="active")

            prices = []
            total_favorites = 0
            for listing in listings:
                if "price" in listing:
                    price = float(listing["price"]["amount"]) / listing["price"]["divisor"]
                    prices.append(price)
                total_favorites += listing.get("num_favorers", 0)

            snapshot = {
                "total_sales": shop_info.get("transaction_sold_count", 0),
                "total_listings": len(listings),
                "total_favorites": total_favorites,
                "avg_price": round(sum(prices) / len(prices), 2) if prices else 0,
            }

            # Save to DB
            db.save_competitor_snapshot(db_shop_id, **snapshot)

            logger.info(
                f"  📊 {shop_info.get('shop_name', shop_id)}: "
                f"{snapshot['total_sales']} sales, "
                f"{snapshot['total_listings']} listings, "
                f"avg ${snapshot['avg_price']}"
            )

            return snapshot

        except Exception as e:
            logger.error(f"Failed to snapshot shop {shop_id}: {e}")
            return {}

    def snapshot_all(self) -> list[dict]:
        """Snapshot all active competitor shops."""
        competitors = db.get_active_competitors()
        if not competitors:
            logger.warning("No competitors configured. Add some first!")
            return []

        logger.info(f"Snapshotting {len(competitors)} competitor shops...")
        results = []
        for comp in competitors:
            result = self.snapshot_shop(comp["shop_id"], comp["id"])
            result["shop_name"] = comp["shop_name"]
            results.append(result)
            time.sleep(2)  # Rate limit courtesy

        return results

    def detect_new_listings(self, shop_id: str) -> list[dict]:
        """
        Compare current listings against what we've seen before.
        Returns list of new listings not in our database.
        """
        current_listings = self.client.get_shop_listings(shop_id)

        new_listings = []
        with db.connection() as conn:
            for listing in current_listings:
                lid = str(listing["listing_id"])
                exists = conn.execute(
                    "SELECT 1 FROM etsy_listings WHERE listing_id = ?", (lid,)
                ).fetchone()

                if not exists:
                    new_listings.append(listing)
                    # Store it
                    tags = json.dumps(listing.get("tags", []))
                    price = (
                        float(listing["price"]["amount"]) / listing["price"]["divisor"]
                        if "price" in listing
                        else 0
                    )
                    conn.execute(
                        """INSERT OR IGNORE INTO etsy_listings
                           (listing_id, shop_name, title, price, favorites, tags, url)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            lid,
                            listing.get("shop_id", ""),
                            listing.get("title", ""),
                            price,
                            listing.get("num_favorers", 0),
                            tags,
                            f"https://www.etsy.com/listing/{lid}",
                        ),
                    )

        if new_listings:
            logger.info(f"  🆕 {len(new_listings)} new listings detected!")
            for nl in new_listings[:5]:  # Show first 5
                logger.info(f"     → {nl.get('title', 'Untitled')[:60]}")
        else:
            logger.info("  No new listings since last check.")

        return new_listings

    def analyze_competitor_tags(self, shop_id: str) -> dict[str, int]:
        """
        Analyze which tags a competitor uses most.
        Useful for keyword strategy insights.
        """
        listings = self.client.get_shop_listings(shop_id)
        tag_counts: dict[str, int] = {}

        for listing in listings:
            for tag in listing.get("tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Sort by frequency
        sorted_tags = dict(
            sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        )
        return sorted_tags
