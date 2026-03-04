"""
Automated listing uploader.
Reads prepared listing data and pushes to Etsy via API.

Workflow:
  1. Read listing definitions from JSON/CSV
  2. Create draft listing
  3. Upload preview images
  4. Upload digital download files
  5. Activate listing
"""

import json
import time
from pathlib import Path
from dataclasses import dataclass, field

from loguru import logger

from etsy_api import etsy_client
from db import db


@dataclass
class ListingDraft:
    """
    Represents a listing ready to be uploaded.
    Prepare these from a JSON file or build programmatically.
    """
    title: str
    description: str
    price: float
    tags: list[str]
    taxonomy_id: int
    # Paths to local files
    preview_images: list[str] = field(default_factory=list)  # Mockups/previews
    digital_files: list[str] = field(default_factory=list)   # Actual download files (PNGs, ZIPs)
    # Etsy-required metadata
    quantity: int = 999          # Digital products: set high
    who_made: str = "i_did"
    when_made: str = "made_to_order"
    is_supply: bool = True       # Clipart = supply
    is_digital: bool = True
    shipping_profile_id: int | None = None  # Required — get from your shop

    def validate(self) -> list[str]:
        """Check for issues before uploading."""
        issues = []
        if len(self.title) > 140:
            issues.append(f"Title too long ({len(self.title)}/140 chars)")
        if len(self.tags) > 13:
            issues.append(f"Too many tags ({len(self.tags)}/13)")
        if any(len(t) > 20 for t in self.tags):
            long_tags = [t for t in self.tags if len(t) > 20]
            issues.append(f"Tags too long (>20 chars): {long_tags}")
        if not self.preview_images:
            issues.append("No preview images provided")
        if self.is_digital and not self.digital_files:
            issues.append("Digital listing but no download files provided")
        for path in self.preview_images + self.digital_files:
            if not Path(path).exists():
                issues.append(f"File not found: {path}")
        return issues


class ListingUploader:
    """Handles the full upload pipeline for a single listing."""

    def __init__(self):
        self.client = etsy_client

    def upload_listing(self, draft: ListingDraft, dry_run: bool = False) -> str | None:
        """
        Upload a complete listing to Etsy.
        Returns the Etsy listing_id on success, None on failure.

        Set dry_run=True to validate without actually uploading.
        """
        # Step 1: Validate
        issues = draft.validate()
        if issues:
            for issue in issues:
                logger.error(f"  ❌ {issue}")
            return None

        if dry_run:
            logger.info(f"[DRY RUN] Would upload: {draft.title}")
            logger.info(f"  Tags: {draft.tags}")
            logger.info(f"  Price: ${draft.price}")
            logger.info(f"  Images: {len(draft.preview_images)}")
            logger.info(f"  Files: {len(draft.digital_files)}")
            return "DRY_RUN"

        try:
            # Step 2: Create draft listing
            logger.info(f"Creating draft: {draft.title[:60]}...")
            listing_data = {
                "title": draft.title,
                "description": draft.description,
                "price": draft.price,
                "quantity": draft.quantity,
                "taxonomy_id": draft.taxonomy_id,
                "who_made": draft.who_made,
                "when_made": draft.when_made,
                "is_supply": draft.is_supply,
                "is_digital": draft.is_digital,
                "tags": draft.tags,
                "type": "download",  # Digital product
            }
            if draft.shipping_profile_id:
                listing_data["shipping_profile_id"] = draft.shipping_profile_id

            result = self.client.create_draft_listing(listing_data)
            listing_id = str(result["listing_id"])
            logger.info(f"  Draft created: listing_id={listing_id}")

            # Step 3: Upload preview images
            for rank, image_path in enumerate(draft.preview_images, start=1):
                logger.info(f"  Uploading image {rank}: {Path(image_path).name}")
                self.client.upload_listing_image(listing_id, image_path, rank=rank)
                time.sleep(1)  # Be nice to the API

            # Step 4: Upload digital files
            for file_path in draft.digital_files:
                logger.info(f"  Uploading file: {Path(file_path).name}")
                self.client.upload_listing_file(listing_id, file_path)
                time.sleep(1)

            # Step 5: Activate
            logger.info(f"  Activating listing {listing_id}...")
            self.client.activate_listing(listing_id)

            logger.info(f"✅ Published: https://www.etsy.com/listing/{listing_id}")
            return listing_id

        except Exception as e:
            logger.error(f"Upload failed for '{draft.title}': {e}")
            return None

    def upload_batch(
        self,
        drafts: list[ListingDraft],
        dry_run: bool = False,
        delay_between: int = 5,
    ) -> dict:
        """
        Upload multiple listings with delays between each.
        Returns summary dict with success/fail counts.
        """
        results = {"success": [], "failed": [], "total": len(drafts)}

        for i, draft in enumerate(drafts, 1):
            logger.info(f"\n[{i}/{len(drafts)}] Processing: {draft.title[:50]}...")
            listing_id = self.upload_listing(draft, dry_run=dry_run)

            if listing_id:
                results["success"].append({"title": draft.title, "listing_id": listing_id})
            else:
                results["failed"].append({"title": draft.title})

            if i < len(drafts):
                logger.info(f"  Waiting {delay_between}s before next upload...")
                time.sleep(delay_between)

        logger.info(
            f"\nBatch complete: {len(results['success'])} succeeded, "
            f"{len(results['failed'])} failed out of {results['total']}"
        )
        return results


def load_drafts_from_json(json_path: str) -> list[ListingDraft]:
    """
    Load listing drafts from a JSON file.

    Expected format:
    [
        {
            "title": "Watercolor Botanical Clipart...",
            "description": "Beautiful hand-painted...",
            "price": 4.99,
            "tags": ["watercolor clipart", "botanical", ...],
            "taxonomy_id": 123,
            "preview_images": ["./images/preview1.png"],
            "digital_files": ["./files/clipart_bundle.zip"]
        },
        ...
    ]
    """
    with open(json_path, "r") as f:
        raw = json.load(f)

    drafts = []
    for item in raw:
        draft = ListingDraft(
            title=item["title"],
            description=item["description"],
            price=item["price"],
            tags=item["tags"],
            taxonomy_id=item["taxonomy_id"],
            preview_images=item.get("preview_images", []),
            digital_files=item.get("digital_files", []),
            quantity=item.get("quantity", 999),
            shipping_profile_id=item.get("shipping_profile_id"),
        )
        drafts.append(draft)

    return drafts
