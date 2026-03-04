"""
Etsy OAuth 2.0 authentication flow.

Etsy API v3 uses PKCE (Proof Key for Code Exchange) OAuth 2.0.
This module handles the full flow:
  1. Generate auth URL → user visits in browser
  2. Receive callback with auth code
  3. Exchange code for access + refresh tokens
  4. Auto-refresh expired tokens

Run this module directly to perform initial auth:
    python -m etsy_api.auth
"""

import hashlib
import base64
import secrets
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

import requests
from loguru import logger

from config import settings


class EtsyAuth:
    """
    Manages Etsy OAuth 2.0 with PKCE.

    PKCE explained (since you're learning):
    - Normal OAuth sends a client_secret to prove identity
    - PKCE replaces this with a code_verifier / code_challenge pair
    - code_verifier: random string (kept secret, sent when exchanging)
    - code_challenge: SHA256 hash of verifier (sent in initial auth URL)
    - This prevents interception attacks without needing a secret in the URL
    """

    REDIRECT_URI = "http://localhost:3003/callback"

    def __init__(self):
        self.config = settings.etsy
        self._code_verifier: str | None = None
        self._state: str | None = None
        self._auth_code: str | None = None

    # ──────────────────────────────────────────
    #  PKCE Helpers
    # ──────────────────────────────────────────

    def _generate_pkce_pair(self) -> tuple[str, str]:
        """
        Generate PKCE code_verifier and code_challenge.
        Returns (verifier, challenge).
        """
        # code_verifier: 43-128 chars, URL-safe random
        verifier = secrets.token_urlsafe(32)

        # code_challenge: base64url(sha256(verifier))
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

        return verifier, challenge

    # ──────────────────────────────────────────
    #  Auth URL Generation
    # ──────────────────────────────────────────

    def get_auth_url(self) -> str:
        """
        Build the Etsy authorization URL.
        User visits this in their browser to grant access.
        """
        self._code_verifier, code_challenge = self._generate_pkce_pair()
        self._state = secrets.token_urlsafe(16)

        params = {
            "response_type": "code",
            "client_id": self.config.api_key,
            "redirect_uri": self.REDIRECT_URI,
            "scope": " ".join(self.config.scopes),
            "state": self._state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        url = f"{self.config.oauth_url}?{urlencode(params)}"
        logger.debug(f"Auth URL generated (state={self._state})")
        return url

    # ──────────────────────────────────────────
    #  Token Exchange
    # ──────────────────────────────────────────

    def exchange_code_for_tokens(self, auth_code: str) -> dict:
        """
        Exchange the authorization code for access + refresh tokens.
        Returns dict with: access_token, refresh_token, expires_in, token_type.
        """
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.config.api_key,
            "redirect_uri": self.REDIRECT_URI,
            "code": auth_code,
            "code_verifier": self._code_verifier,
        }

        response = requests.post(self.config.token_url, data=payload)
        response.raise_for_status()
        token_data = response.json()

        # Store tokens in config (runtime only — you'll want to persist these)
        self.config.access_token = token_data["access_token"]
        self.config.refresh_token = token_data["refresh_token"]

        logger.info("Successfully obtained Etsy access token")
        logger.info(f"  Token expires in: {token_data['expires_in']} seconds")
        logger.info(f"  ACCESS_TOKEN:  {token_data['access_token'][:20]}...")
        logger.info(f"  REFRESH_TOKEN: {token_data['refresh_token'][:20]}...")
        logger.warning(
            "⚠️  Copy these tokens to your .env file! "
            "They won't persist after this session."
        )

        return token_data

    def refresh_access_token(self) -> dict:
        """
        Use refresh_token to get a new access_token.
        Call this when you get a 401 response.
        """
        if not self.config.refresh_token:
            raise ValueError("No refresh token available. Run full auth flow first.")

        payload = {
            "grant_type": "refresh_token",
            "client_id": self.config.api_key,
            "refresh_token": self.config.refresh_token,
        }

        response = requests.post(self.config.token_url, data=payload)
        response.raise_for_status()
        token_data = response.json()

        self.config.access_token = token_data["access_token"]
        self.config.refresh_token = token_data["refresh_token"]

        logger.info("Access token refreshed successfully")
        return token_data

    # ──────────────────────────────────────────
    #  Local Callback Server
    # ──────────────────────────────────────────

    def run_auth_flow(self):
        """
        Run the complete interactive OAuth flow:
        1. Start local server to catch callback
        2. Open browser to Etsy auth page
        3. Wait for user to authorize
        4. Exchange code for tokens
        """
        auth_url = self.get_auth_url()
        captured = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlparse(self.path).query)
                captured["code"] = query.get("code", [None])[0]
                captured["state"] = query.get("state", [None])[0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<h2>Authorization successful!</h2>"
                    b"<p>You can close this tab and return to the terminal.</p>"
                )

            def log_message(self, format, *args):
                pass  # Suppress server logs

        server = HTTPServer(("localhost", 3003), CallbackHandler)
        thread = Thread(target=server.handle_request)
        thread.start()

        print(f"\n{'='*60}")
        print("Opening Etsy authorization page in your browser...")
        print(f"If it doesn't open, visit:\n{auth_url}")
        print(f"{'='*60}\n")
        webbrowser.open(auth_url)

        thread.join(timeout=120)  # Wait up to 2 minutes
        server.server_close()

        if not captured.get("code"):
            logger.error("No authorization code received. Auth flow failed.")
            return None

        if captured.get("state") != self._state:
            logger.error("State mismatch — possible CSRF attack!")
            return None

        return self.exchange_code_for_tokens(captured["code"])


# ──────────────────────────────────────────────
#  CLI Entry Point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    from config import settings

    issues = settings.validate()
    if issues:
        print("Configuration issues found:")
        for issue in issues:
            print(f"  ❌ {issue}")
        print("\nPlease fill in your .env file first.")
        exit(1)

    auth = EtsyAuth()
    tokens = auth.run_auth_flow()
    if tokens:
        print("\n✅ Auth successful! Add these to your .env file:\n")
        print(f'ETSY_ACCESS_TOKEN={tokens["access_token"]}')
        print(f'ETSY_REFRESH_TOKEN={tokens["refresh_token"]}')
