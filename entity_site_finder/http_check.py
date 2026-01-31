"""
http_check.py

Handles website validation for Bardic Beacon.

This module:
- Sends HEAD or GET requests to candidate URLs
- Detects if a domain is reachable
- Follows redirects
- Returns a simple (live, status_code, final_url) tuple
"""

from __future__ import annotations

from typing import Optional, Tuple

import requests


# ----------------------------
# Browser-style user agent
# ----------------------------

USER_AGENT = (
    "Mozilla/5.0 (compatible; BardicBeacon/1.0; +internal-tool)"
)


# ----------------------------
# Core Website Check Function
# ----------------------------

def looks_like_valid_website(
    url: str,
    timeout: float = 8.0,
) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Checks whether a candidate URL appears to be a valid live website.

    Strategy:
    1. Try HEAD first (fast)
    2. If blocked or unsupported, fallback to GET
    3. Accept status codes 200–399 as valid
    4. Follow redirects (allow_redirects=True)

    Parameters:
        url      → candidate URL (https://example.com/)
        timeout  → request timeout in seconds

    Returns:
        (live, status_code, final_url)

        live        → True if reachable + non-error response
        status_code → HTTP response status (or None)
        final_url   → Redirect-resolved URL (or None)
    """

    headers = {"User-Agent": USER_AGENT}

    try:
        # -------------------------
        # Attempt HEAD request first
        # -------------------------
        response = requests.head(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers=headers,
        )

        # Some websites block HEAD or return 405
        if response.status_code in (403, 405) or response.status_code >= 400:
            response = requests.get(
                url,
                allow_redirects=True,
                timeout=timeout,
                headers=headers,
            )

        # -------------------------
        # Define what counts as "live"
        # -------------------------
        live = 200 <= response.status_code < 400

        return live, response.status_code, response.url

    except requests.RequestException:
        # Any connection failure counts as not live
        return False, None, None
