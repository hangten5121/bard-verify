"""
google_search.py

Handles Google Custom Search JSON API calls and domain extraction.

This file should:
- Query Google for an entity name
- Collect top result domains
- Filter out non-official sites (Yelp, Facebook, etc.)
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests


# ----------------------------
# Hosts we do NOT want returned
# ----------------------------

COMMON_NON_OFFICIAL_HOSTS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "yelp.com",
    "yellowpages.com",
    "bbb.org",
    "mapquest.com",
    "opencorporates.com",
    "crunchbase.com",
    "bloomberg.com",
    "dnb.com",
    "google.com",
}

USER_AGENT = (
    "Mozilla/5.0 (compatible; BardicBeacon/1.0; +internal-tool)"
)


# ----------------------------
# Helper: extract domain
# ----------------------------

def extract_domain(url: str) -> Optional[str]:
    """
    Extract clean domain from a URL.
    Example:
        https://www.acme.com/page → acme.com
    """
    try:
        host = urlparse(url).netloc.lower()

        if host.startswith("www."):
            host = host[4:]

        return host if host else None

    except Exception:
        return None


# ----------------------------
# Google Search API Call
# ----------------------------

def google_custom_search(
    query: str,
    api_key: str,
    cx: str,
    num: int = 5,
    pause_s: float = 0.25,
) -> List[Dict]:
    """
    Calls Google Custom Search JSON API.

    Parameters:
        query   → search string
        api_key → Google API key
        cx      → Search engine ID
        num     → number of results (max 10)
        pause_s → polite delay between API calls

    Returns:
        List of result items (dicts)
    """

    endpoint = "https://www.googleapis.com/customsearch/v1"

    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": max(1, min(num, 10)),
    }

    time.sleep(pause_s)

    resp = requests.get(
        endpoint,
        params=params,
        timeout=15,
        headers={"User-Agent": USER_AGENT},
    )

    resp.raise_for_status()
    data = resp.json()

    return data.get("items", []) or []


# ----------------------------
# Candidate Domain Extraction
# ----------------------------

def candidate_domains_from_search(items: List[Dict]) -> List[str]:
    """
    Extract domain candidates from Google search results.

    Filters out common directory/social media hosts.
    Deduplicates domains while preserving order.
    """

    domains: List[str] = []

    for item in items:
        link = item.get("link")
        if not link:
            continue

        domain = extract_domain(link)
        if not domain:
            continue

        # Skip directory sites
        if domain in COMMON_NON_OFFICIAL_HOSTS:
            continue

        domains.append(domain)

    # Remove duplicates, preserve order
    seen = set()
    unique_domains = []

    for d in domains:
        if d not in seen:
            seen.add(d)
            unique_domains.append(d)

    return unique_domains


# ----------------------------
# Main Convenience Wrapper
# ----------------------------

def search_entity_domains(
    entity_name: str,
    area_code: str = "",
    api_key: str = "",
    cx: str = "",
    num_results: int = 5,
) -> List[str]:
    """
    One-call function used by finder.py.

    Returns a clean ranked list of likely official domains.
    """

    query = f'"{entity_name}" official website {area_code}'.strip()

    items = google_custom_search(
        query=query,
        api_key=api_key,
        cx=cx,
        num=num_results,
    )

    return candidate_domains_from_search(items)
