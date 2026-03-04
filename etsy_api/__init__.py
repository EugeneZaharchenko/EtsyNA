"""
Etsy API v3 client.
Wraps common API operations with automatic token refresh and rate limiting.
"""

import time
import json
from pathlib import Path
from typing import Any

import requests
from loguru import logger

from config import settings
from etsy_api.auth import EtsyAuth


class EtsyClient:
    """
    HTTP client for Etsy API v3.

    Handles:
    - Authentication headers
    - Automatic token refresh on 401
    - Rate limit awareness
    - Pagination helpers
    """

    def __init__(self):
        self.config = settings.etsy
        self.auth = EtsyAuth()
        self.session = requests.Session()
        self._update_headers()

    def _update_headers(self):
        """Set auth headers on the session."""
        self.session.headers.update({
            "x-api-key": self.config.api_key,
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
        })

    # ──────────────────────────────────────────
    #  Core HTTP Methods
    # ──────────────────────────────────────────

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """
        Make an authenticated API request with auto-retry on 401.
        """
        url = f"{self.config.base_url}{endpoint}"

        response = self.session.request(method, url, **kwargs)

        # Handle token expiration
        if response.status_code == 401:
            logger.info("Token expired, refreshing...")
            self.auth.refresh_access_token()
            self._update_headers()
            response = self.session.request(method, url, **kwargs)

        # Handle rate limiting
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 5))
            logger.warning(f"Rate limited. Waiting {retry_after}s...")
            time.sleep(retry_after)
            return self._request(method, endpoint, **kwargs)

        response.raise_for_status()
        return response.json() if response.content else {}

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: dict | None = None, **kwargs) -> dict:
        return self._request("POST", endpoint, json=data, **kwargs)

    def put(self, endpoint: str, data: dict | None = None) -> dict:
        return self._request("PUT", endpoint, json=data)

    def delete(self, endpoint: str) -> dict:
        return self._request("DELETE", endpoint)

    # ──────────────────────────────────────────
    #  Pagination Helper
    # ──────────────────────────────────────────

    def get_all_pages(
        self, endpoint: str, params: dict | None = None, limit: int = 100
    ) -> list[dict]:
        """
        Fetch all pages of a paginated endpoint.
        Etsy uses offset-based pagination.
        """
        params = params or {}
        params["limit"] = min(limit, 100)  # Etsy max is 100
        offset = 0
        all_results = []

        while True:
            params["offset"] = offset
            data = self.get(endpoint, params=params)
            results = data.get("results", [])
            all_results.extend(results)

            count = data.get("count", 0)
            if offset + len(results) >= count:
                break

            offset += len(results)
            time.sleep(0.5)  # Be nice to Etsy's servers

        logger.debug(f"Fetched {len(all_results)} total results from {endpoint}")
        return all_results

    # ──────────────────────────────────────────
    #  Shop Operations
    # ──────────────────────────────────────────

    def get_my_shop(self) -> dict:
        """Get our own shop info."""
        return self.get(f"/application/shops/{self.config.shop_id}")

    def get_shop_info(self, shop_id: str) -> dict:
        """Get public info about any shop."""
        return self.get(f"/application/shops/{shop_id}")

    def get_shop_listings(self, shop_id: str, state: str = "active") -> list[dict]:
        """Get all listings for a shop."""
        return self.get_all_pages(
            f"/application/shops/{shop_id}/listings/{state}"
        )

    # ──────────────────────────────────────────
    #  Search Operations
    # ──────────────────────────────────────────

    def search_listings(self, keyword: str, limit: int = 100, **params) -> dict:
        """
        Search Etsy listings by keyword.
        Returns dict with 'count' (total matches) and 'results' (listings).
        """
        search_params = {
            "keywords": keyword,
            "limit": min(limit, 100),
            **params,
        }
        return self.get("/application/listings/active", params=search_params)

    def get_listing_details(self, listing_id: str, includes: list[str] | None = None) -> dict:
        """Get detailed info about a specific listing."""
        params = {}
        if includes:
            # e.g., includes=["images", "shop", "inventory"]
            params["includes"] = ",".join(includes)
        return self.get(f"/application/listings/{listing_id}", params=params)

    # ──────────────────────────────────────────
    #  Listing Management (Our Shop)
    # ──────────────────────────────────────────

    def create_draft_listing(self, listing_data: dict) -> dict:
        """
        Create a new draft listing in our shop.

        Required fields in listing_data:
        - title: str (max 140 chars)
        - description: str
        - price: float
        - quantity: int
        - taxonomy_id: int (Etsy category)
        - who_made: str ('i_did' | 'someone_else' | 'collective')
        - when_made: str ('made_to_order' | '2020_2024' | etc.)
        - is_supply: bool
        - shipping_profile_id: int
        - tags: list[str] (max 13 tags, each max 20 chars)
        """
        return self.post(
            f"/application/shops/{self.config.shop_id}/listings",
            data=listing_data,
        )

    def upload_listing_image(
        self, listing_id: str, image_path: str, rank: int = 1
    ) -> dict:
        """
        Upload an image to a listing.
        Note: This endpoint requires multipart/form-data, not JSON.
        """
        url = (
            f"{self.config.base_url}/application/shops/"
            f"{self.config.shop_id}/listings/{listing_id}/images"
        )

        # Override Content-Type for multipart upload
        headers = {
            "x-api-key": self.config.api_key,
            "Authorization": f"Bearer {self.config.access_token}",
        }

        with open(image_path, "rb") as f:
            files = {"image": (Path(image_path).name, f, "image/png")}
            data = {"rank": rank}
            response = requests.post(url, headers=headers, files=files, data=data)

        response.raise_for_status()
        return response.json()

    def upload_listing_file(self, listing_id: str, file_path: str) -> dict:
        """
        Upload a digital download file to a listing.
        """
        url = (
            f"{self.config.base_url}/application/shops/"
            f"{self.config.shop_id}/listings/{listing_id}/files"
        )

        headers = {
            "x-api-key": self.config.api_key,
            "Authorization": f"Bearer {self.config.access_token}",
        }

        with open(file_path, "rb") as f:
            files = {"file": (Path(file_path).name, f)}
            response = requests.post(url, headers=headers, files=files)

        response.raise_for_status()
        return response.json()

    def activate_listing(self, listing_id: str) -> dict:
        """Set a draft listing to active."""
        return self.put(
            f"/application/shops/{self.config.shop_id}/listings/{listing_id}",
            data={"state": "active"},
        )

    # ──────────────────────────────────────────
    #  Taxonomy
    # ──────────────────────────────────────────

    def get_seller_taxonomy(self) -> list[dict]:
        """
        Get Etsy's taxonomy (category tree).
        Useful for finding the correct taxonomy_id for your listings.
        """
        data = self.get("/application/seller-taxonomy/nodes")
        return data.get("results", [])


# Singleton
etsy_client = EtsyClient()
