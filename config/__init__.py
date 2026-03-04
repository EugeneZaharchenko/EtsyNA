"""
Centralized configuration management.
Loads from .env file and provides typed access to all settings.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class EtsyConfig:
    api_key: str = field(default_factory=lambda: os.getenv("ETSY_API_KEY", ""))
    shared_secret: str = field(default_factory=lambda: os.getenv("ETSY_SHARED_SECRET", ""))
    shop_id: str = field(default_factory=lambda: os.getenv("ETSY_SHOP_ID", ""))
    access_token: str = field(default_factory=lambda: os.getenv("ETSY_ACCESS_TOKEN", ""))
    refresh_token: str = field(default_factory=lambda: os.getenv("ETSY_REFRESH_TOKEN", ""))
    base_url: str = "https://api.etsy.com/v3"
    oauth_url: str = "https://www.etsy.com/oauth/connect"
    token_url: str = "https://api.etsy.com/v3/public/oauth/token"
    # Scopes needed for full automation
    scopes: list = field(default_factory=lambda: [
        "listings_r", "listings_w", "listings_d",
        "shops_r", "shops_w",
        "transactions_r",
    ])

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.shared_secret)

    @property
    def has_tokens(self) -> bool:
        return bool(self.access_token and self.refresh_token)


@dataclass
class DatabaseConfig:
    path: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_PATH",
            str(PROJECT_ROOT / "data" / "etsy_automation.db")
        )
    )

    def ensure_directory(self):
        """Create the database directory if it doesn't exist."""
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)


@dataclass
class LogConfig:
    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    log_file: str = field(
        default_factory=lambda: os.getenv(
            "LOG_FILE",
            str(PROJECT_ROOT / "logs" / "pipeline.log")
        )
    )

    def ensure_directory(self):
        Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    """Main settings container — single source of truth."""
    etsy: EtsyConfig = field(default_factory=EtsyConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    logging: LogConfig = field(default_factory=LogConfig)

    def validate(self) -> list[str]:
        """Return list of configuration issues."""
        issues = []
        if not self.etsy.is_configured:
            issues.append("Etsy API key or shared secret not set in .env")
        if not self.etsy.shop_id:
            issues.append("ETSY_SHOP_ID not set in .env")
        return issues


# Singleton instance — import this everywhere
settings = Settings()
