#!/usr/bin/env python3
"""
find_entity_websites.py

Reads a CSV with at least:
- entity_name (configurable)
- mailing_state (configurable)

For each entity_name:
1) Uses Google Custom Search JSON API to find likely official website domains.
2) Generates heuristic domain guesses: <normalized>.com/.org/.net
3) Verifies candidate websites via HTTP (requests), with timeouts.
4) Writes:
   - master_results.csv
   - one CSV per mailing_state in ./by_mailing_state/

Usage:
  python find_entity_websites.py \
    --input business_data.csv \
    --name-col entity_name \
    --state-col mailing_state \
    --out master_results.csv \
    --google-api-key "$GOOGLE_API_KEY" \
    --google-cx "$GOOGLE_CX"

Environment variables supported:
  GOOGLE_API_KEY, GOOGLE_CX
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import requests


# ----------------------------
# Config / Utilities
# ----------------------------

COMMON_NON_OFFICIAL_HOSTS = {
    "facebook.com",
    "m.facebook.com",
    "instagram.com",
    "linkedin.com",
    "yelp.com",
    "mapquest.com",
    "yellowpages.com",
    "bbb.org",
    "bloomberg.com",
    "dnb.com",
    "opencorporates.com",
    "crunchbase.com",
    "google.com",
}

USER_AGENT = "Mozilla/5.0 (compatible; BardVerify/1.0; +internal-tool)"


def normalize_name_to_domain_base(name: str) -> str:
    """
    Turn 'Acme Plumbing, LLC' into 'acmeplumbing' (a naive base for guessing domains).
    """
    name = (name or "").lower().strip()

    # Drop common legal suffixes and noise words
    suffixes = [
        r"\bllc\b", r"\binc\b", r"\bcorp\b", r"\bco\b", r"\bcompany\b",
        r"\bltd\b", r"\blimited\b", r"\bpllc\b", r"\bpc\b", r"\bpartners\b",
    ]
    for s in suffixes:
        name = re.sub(s, "", name)

    # Replace '&' with 'and'
    name = name.replace("&", " and ")

    # Remove all non-alphanumerics
    name = re.sub(r"[^a-z0-9]+", "", name)

    return name.strip()


def extract_domain(url: str) -> Optional[str]:
    """
    Extract host from URL and reduce to host; keep full host here (no publicsuffix parsing).
    """
    try:
        host = urlparse(url).netloc.lower()
        if not host:
            return None
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return None


def looks_like_valid_website(url: str, timeout: float = 8.0) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Check if a URL seems to be a live website.
    Strategy:
      - try HEAD, fallback to GET
      - accept HTTP 200-399 as "live"
    Returns: (is_live, status_code, final_url)
    """
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout, headers=headers)
        if r.status_code >= 400 or r.status_code in (405, 403):
            r = requests.get(url, allow_redirects=True, timeout=timeout, headers=headers)
        live = 200 <= r.status_code < 400
        return live, r.status_code, r.url
    except requests.RequestException:
        return False, None, None


# ----------------------------
# Google Custom Search
# ----------------------------

def google_custom_search(
    query: str,
    api_key: str,
    cx: str,
    num: int = 5,
    pause_s: float = 0.2,
) -> List[Dict]:
    """
    Calls the Google Custom Search JSON API.
    Docs: https://developers.google.com/custom-search/v1/overview
    """
    endpoint = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": max(1, min(num, 10)),
    }
    time.sleep(pause_s)
    resp = requests.get(endpoint, params=params, timeout=15, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", []) or []


def candidate_domains_from_search_items(items: List[Dict]) -> List[str]:
    domains: List[str] = []
    for it in items:
        link = it.get("link")
        if not link:
            continue
        host = extract_domain(link)
        if not host:
            continue
        if host in COMMON_NON_OFFICIAL_HOSTS:
            continue
        domains.append(host)

    # de-dupe preserving order
    seen = set()
    out: List[str] = []
    for d in domains:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


# ----------------------------
# Main process
# ----------------------------

@dataclass
class ResultRow:
    mailing_state: str
    entity_name: str
    search_query: str
    best_domain: str
    best_url: str
    best_http_status: str
    method: str  # "google" or "guess" or "none"
    other_candidates: str  # JSON for traceability


def find_best_website_for_entity(
    entity_name: str,
    mailing_state: str,
    google_api_key: Optional[str],
    google_cx: Optional[str],
    try_tlds: Iterable[str] = ("com", "org", "net"),
    timeout: float = 8.0,
) -> ResultRow:
    # Build a query that includes mailing_state as a location hint.
    query = f'"{entity_name}" official website {mailing_state}'.strip()

    candidates: List[Tuple[str, str]] = []  # (method, candidate_url)
    other_candidates_struct = {"google_domains": [], "guessed_urls": []}

    # 1) Google search candidates
    if google_api_key and google_cx:
        try:
            items = google_custom_search(query, api_key=google_api_key, cx=google_cx, num=5)
            domains = candidate_domains_from_search_items(items)
            other_candidates_struct["google_domains"] = domains

            for d in domains:
                candidates.append(("google", f"https://{d}/"))
                candidates.append(("google", f"http://{d}/"))
        except Exception:
            pass

    # 2) Heuristic guesses
    base = normalize_name_to_domain_base(entity_name)
    if base:
        for tld in try_tlds:
            guessed = f"{base}.{tld}"
            other_candidates_struct["guessed_urls"].append(guessed)
            candidates.append(("guess", f"https://{guessed}/"))
            candidates.append(("guess", f"http://{guessed}/"))

    # 3) Validate candidates in order; first live wins
    for method, url in candidates:
        live, status, final_url = looks_like_valid_website(url, timeout=timeout)
        if live:
            return ResultRow(
                mailing_state=str(mailing_state or ""),
                entity_name=entity_name,
                search_query=query,
                best_domain=extract_domain(final_url or url) or "",
                best_url=final_url or url,
                best_http_status=str(status) if status is not None else "",
                method=method,
                other_candidates=json.dumps(other_candidates_struct, ensure_ascii=False),
            )

    # 4) Nothing found
    return ResultRow(
        mailing_state=str(mailing_state or ""),
        entity_name=entity_name,
        search_query=query,
        best_domain="",
        best_url="",
        best_http_status="",
        method="none",
        other_candidates=json.dumps(other_candidates_struct, ensure_ascii=False),
    )


def write_csv(path: str, rows: List[ResultRow]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "mailing_state",
                "entity_name",
                "search_query",
                "best_domain",
                "best_url",
                "best_http_status",
                "method",
                "other_candidates",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow({
                "mailing_state": r.mailing_state,
                "entity_name": r.entity_name,
                "search_query": r.search_query,
                "best_domain": r.best_domain,
                "best_url": r.best_url,
                "best_http_status": r.best_http_status,
                "method": r.method,
                "other_candidates": r.other_candidates,
            })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Input CSV path")
    ap.add_argument("--out", default="master_results.csv", help="Master output CSV")
    ap.add_argument("--name-col", default="entity_name", help="Column name for entity name")
    ap.add_argument("--state-col", default="mailing_state", help="Column name for mailing state")
    ap.add_argument("--google-api-key", default=os.getenv("GOOGLE_API_KEY"), help="Google API key")
    ap.add_argument("--google-cx", default=os.getenv("GOOGLE_CX"), help="Google Custom Search Engine ID (cx)")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of rows (0 = no limit)")
    ap.add_argument("--sleep", type=float, default=0.2, help="Pause between Google API calls")
    ap.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout seconds")
    args = ap.parse_args()

    google_api_key = args.google_api_key
    google_cx = args.google_cx

    rows_out: List[ResultRow] = []
    by_state: Dict[str, List[ResultRow]] = {}

    with open(args.input, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit("Input CSV has no header row.")
        if args.name_col not in reader.fieldnames:
            raise SystemExit(f"Missing required column: {args.name_col}. Found: {reader.fieldnames}")
        if args.state_col not in reader.fieldnames:
            raise SystemExit(f"Missing required column: {args.state_col}. Found: {reader.fieldnames}")

        for i, row in enumerate(reader, start=1):
            if args.limit and i > args.limit:
                break

            name = (row.get(args.name_col) or "").strip()
            state = (row.get(args.state_col) or "").strip() or "UNKNOWN"

            if not name:
                continue

            res = find_best_website_for_entity(
                entity_name=name,
                mailing_state=state,
                google_api_key=google_api_key,
                google_cx=google_cx,
                timeout=args.timeout,
            )
            rows_out.append(res)
            by_state.setdefault(res.mailing_state or "UNKNOWN", []).append(res)

            # Be polite to APIs
            if google_api_key and google_cx:
                time.sleep(args.sleep)

            if i % 50 == 0:
                print(f"Processed {i} rows...")

    # Write master CSV
    write_csv(args.out, rows_out)

    # Write per-mailing-state CSVs
    out_dir = "by_mailing_state"
    os.makedirs(out_dir, exist_ok=True)
    for mailing_state, items in by_state.items():
        safe_state = re.sub(r"[^0-9A-Za-z_-]+", "_", mailing_state or "UNKNOWN")
        write_csv(os.path.join(out_dir, f"results_state_{safe_state}.csv"), items)

    print(f"Done. Wrote master: {args.out} and per-state files in ./{out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
