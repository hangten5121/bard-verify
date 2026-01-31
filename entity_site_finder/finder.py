"""
finder.py

Main orchestration logic for Bardic Beacon.

This module:
- Searches Google for entity websites
- Generates guessed .com/.org/.net domains
- Checks which candidate is live
- Returns the best match

Used by:
- Streamlit app (app.py)
- Batch scripts
- Future API deployment
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from .google_search import search_entity_domains
from .normalize import normalize_name_to_domain_base
from .http_check import looks_like_valid_website


# ----------------------------
# Result object
# ----------------------------

@dataclass
class ResultRow:
    """
    Output structure returned per entity.

    This gets written directly into the output CSV.
    """

    area_code: str
    entity_name: str
    search_query: str
    best_domain: str
    best_url: str
    best_http_status: str
    method: str  # "google", "guess", or "none"
    other_candidates: str


# ----------------------------
# Main finder function
# ----------------------------

def find_best_website_for_entity(
    entity_name: str,
    area_code: str,
    google_api_key: Optional[str],
    google_cx: Optional[str],
    try_tlds: Iterable[str] = ("com", "org", "net"),
    timeout: float = 8.0,
) -> ResultRow:
    """
    Finds the best live official-looking website for an entity.

    Strategy:
    1. Use Google Custom Search API → candidate domains
    2. Guess domains from normalized entity name (.com/.org/.net)
    3. Validate candidates via HTTP HEAD/GET
    4. Return the first working result

    Returns:
        ResultRow with best match
    """

    query = f'"{entity_name}" official website {area_code}'.strip()

    candidates: List[Tuple[str, str]] = []
    metadata = {
        "google_domains": [],
        "guessed_urls": [],
    }

    # --------------------------------------
    # 1) Google Search Candidate Domains
    # --------------------------------------

    if google_api_key and google_cx:
        try:
            domains = search_entity_domains(
                entity_name=entity_name,
                area_code=area_code,
                api_key=google_api_key,
                cx=google_cx,
                num_results=5,
            )

            metadata["google_domains"] = domains

            for domain in domains:
                candidates.append(("google", f"https://{domain}/"))
                candidates.append(("google", f"http://{domain}/"))

        except Exception:
            # If Google fails, fallback to guessing
            pass

    # --------------------------------------
    # 2) Heuristic Domain Guessing
    # --------------------------------------

    domain_base = normalize_name_to_domain_base(entity_name)

    if domain_base:
        for tld in try_tlds:
            guessed_domain = f"{domain_base}.{tld}"
            metadata["guessed_urls"].append(guessed_domain)

            candidates.append(("guess", f"https://{guessed_domain}/"))
            candidates.append(("guess", f"http://{guessed_domain}/"))

    # --------------------------------------
    # 3) Validate Candidates (first live wins)
    # --------------------------------------

    for method, url in candidates:
        live, status, final_url = looks_like_valid_website(url, timeout=timeout)

        if live:
            best_domain = final_url.replace("https://", "").replace("http://", "").split("/")[0]

            return ResultRow(
                area_code=str(area_code),
                entity_name=entity_name,
                search_query=query,
                best_domain=best_domain,
                best_url=final_url or url,
                best_http_status=str(status),
                method=method,
                other_candidates=json.dumps(metadata),
            )

    # --------------------------------------
    # 4) Nothing Found
    # --------------------------------------

    return ResultRow(
        area_code=str(area_code),
        entity_name=entity_name,
        search_query=query,
        best_domain="",
        best_url="",
        best_http_status="",
        method="none",
        other_candidates=json.dumps(metadata),
    )
