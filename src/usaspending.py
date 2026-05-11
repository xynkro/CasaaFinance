"""USAspending.gov API client.

Wraps the public spending_by_award endpoint with pagination + retries.
No API key required. Soft rate limits — we batch by date so a single
day's contracts comes back in 1-3 pages of 100 rows each.

Reference:
  https://github.com/fedspendingtransparency/usaspending-api/blob/master/
  usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md

The endpoint returns one row per (award + modification). We dedupe on
`generated_internal_id` upstream when writing to Sheets so re-runs
of the same date are idempotent.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

API_BASE = "https://api.usaspending.gov"
ENDPOINT = f"{API_BASE}/api/v2/search/spending_by_award/"

# Award type codes from USAspending taxonomy:
#   A,B,C,D       = Definitive Contracts (BPA Call, Purchase Order, etc.)
#   IDV_A..IDV_E  = Indefinite-Delivery Vehicles (multi-year umbrella contracts)
# Skipping grants/loans for v1 — the strategy is contract-catalyst-driven.
#
# IMPORTANT: USAspending rejects requests that mix groups ("award_type_codes
# must only contain types from one group"). So fetch_awards() makes TWO
# passes — one for contracts, one for IDVs — and merges results.
CONTRACT_AWARD_TYPES = ["A", "B", "C", "D"]
IDV_AWARD_TYPES = ["IDV_A", "IDV_B", "IDV_C", "IDV_D", "IDV_E"]

# Fields we read out of the API. Names must match exactly the keys USAspending
# documents — typo => silent empty data. Verified against the contract YAML
# in the open-source repo.
DEFAULT_FIELDS = [
    "Award ID",
    "generated_internal_id",
    "Recipient Name",
    "Recipient UEI",
    "recipient_id",
    "Award Amount",
    "Total Outlays",
    "Contract Award Type",
    "Action Date",
    "Last Modified Date",
    "Start Date",
    "End Date",
    "Awarding Agency",
    "Awarding Sub Agency",
    "NAICS",
    "Description",
    "Place of Performance State Code",
]

DEFAULT_PAGE_SIZE = 100  # max allowed by the endpoint
DEFAULT_MAX_PAGES = 50   # upper bound — typical day is 5-15 pages
USER_AGENT = "FinancePWA/1.0 (gov-confluence-strategy)"


def fetch_awards(
    start_date: str,
    end_date: str,
    fields: list[str] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout: float = 30.0,
    include_contracts: bool = True,
    include_idvs: bool = True,
) -> list[dict[str, Any]]:
    """Fetch all contract awards in [start_date, end_date].

    Makes two passes (contracts + IDVs) since USAspending rejects mixed-group
    queries. Results are merged and deduped on `generated_internal_id`.

    Args:
        start_date / end_date: ISO YYYY-MM-DD strings, inclusive.
        fields: list of API field names to return per row.
        page_size: rows per page (max 100).
        max_pages: hard cap on pagination per group.
        timeout: per-request HTTP timeout.
        include_contracts: if True, fetch A/B/C/D award types.
        include_idvs: if True, fetch IDV_A..IDV_E.

    Returns:
        Flat list of award dicts. Pagination is walked transparently.
        Returns [] on persistent errors after retries.
    """
    fields_list = list(fields or DEFAULT_FIELDS)
    groups: list[list[str]] = []
    if include_contracts:
        groups.append(CONTRACT_AWARD_TYPES)
    if include_idvs:
        groups.append(IDV_AWARD_TYPES)

    seen_ids: set[str] = set()
    merged: list[dict] = []
    for group_codes in groups:
        rows = _fetch_one_group(
            start_date, end_date, group_codes, fields_list,
            page_size, max_pages, timeout,
        )
        for r in rows:
            rid = r.get("generated_internal_id") or r.get("internal_id") or r.get("Award ID")
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            merged.append(r)
    log.info(
        "USAspending fetch complete: %d unique awards across %d group(s) for %s..%s",
        len(merged), len(groups), start_date, end_date,
    )
    return merged


def _fetch_one_group(
    start_date: str,
    end_date: str,
    award_type_codes: list[str],
    fields: list[str],
    page_size: int,
    max_pages: int,
    timeout: float,
) -> list[dict]:
    """Single-group paginated fetch. Walks until empty or max_pages hit."""
    body_template = {
        "filters": {
            "time_period": [{
                "start_date": start_date,
                "end_date": end_date,
            }],
            "award_type_codes": list(award_type_codes),
        },
        "fields": list(fields),
        # Order ensures we don't miss new awards inserted mid-pagination
        # (USAspending serves paginated results from a stable snapshot).
        "sort": "Award Amount",
        "order": "desc",
        "limit": page_size,
    }

    out: list[dict] = []
    for page in range(1, max_pages + 1):
        body = {**body_template, "page": page}
        result = _post_with_retries(body, timeout=timeout)
        if result is None:
            log.warning(
                "USAspending fetch failed at page %d (group=%s) after retries — "
                "returning %d rows so far",
                page, ",".join(award_type_codes), len(out),
            )
            break

        rows = result.get("results", []) or []
        out.extend(rows)
        log.info(
            "USAspending group=%s page %d: %d rows (group total: %d)",
            "contracts" if "A" in award_type_codes else "idvs",
            page, len(rows), len(out),
        )

        meta = result.get("page_metadata") or {}
        if not meta.get("hasNext"):
            break
        # Brief delay between pages — the API is generous but we're polite.
        time.sleep(0.3)

    return out


def _post_with_retries(body: dict, timeout: float, attempts: int = 3) -> dict | None:
    """POST to spending_by_award with exponential backoff on 5xx / connect errors.

    Returns parsed JSON dict on success, None on persistent failure.
    """
    delay = 2.0
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            r = requests.post(
                ENDPOINT,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                },
                timeout=timeout,
            )
            if r.status_code >= 500:
                raise requests.HTTPError(f"server {r.status_code}", response=r)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last_exc = e
            log.warning(
                "USAspending POST attempt %d/%d failed: %s — retrying in %.1fs",
                i + 1, attempts, e, delay,
            )
            time.sleep(delay)
            delay *= 2
    log.error("USAspending POST failed after %d attempts: %s", attempts, last_exc)
    return None


# ── Field accessor helpers ──────────────────────────────────────────────────
# USAspending response keys are humanized strings ("Award ID", "Recipient
# Name") which is awkward in Python. These helpers wrap the indirection.

def get_award_id(row: dict) -> str:
    return str(row.get("generated_internal_id") or row.get("Award ID") or "")


def get_recipient_name(row: dict) -> str:
    return str(row.get("Recipient Name") or "")


def get_award_amount(row: dict) -> float:
    v = row.get("Award Amount")
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def get_total_outlays(row: dict) -> float:
    """Total Outlays approximates TCV (Total Contract Value) for multi-year
    awards. Falls back to Award Amount for simple year-only contracts."""
    v = row.get("Total Outlays") or row.get("Award Amount")
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def get_action_date(row: dict) -> str:
    """Date the award action occurred.

    USAspending's API frequently returns `Action Date: None` even when
    the field is requested — the open-source API appears to populate it
    inconsistently across award types. Fall back to `Last Modified Date`
    (when the record was last touched, which is a good proxy since our
    `time_period` filter is on action_date anyway) and finally `Start Date`.
    Returning empty string when ALL three are missing means downstream
    screener filters drop the row — preferable to silently inserting
    today's date.
    """
    raw = (
        row.get("Action Date")
        or row.get("Last Modified Date")
        or row.get("Start Date")
        or ""
    )
    return str(raw)[:10]


def get_period_start(row: dict) -> str:
    return str(row.get("Start Date") or "")[:10]


def get_period_end(row: dict) -> str:
    return str(row.get("End Date") or "")[:10]


def get_agency(row: dict) -> str:
    a = row.get("Awarding Agency")
    if isinstance(a, dict):
        return str(a.get("name") or "")
    return str(a or "")


def get_sub_agency(row: dict) -> str:
    a = row.get("Awarding Sub Agency")
    if isinstance(a, dict):
        return str(a.get("name") or "")
    return str(a or "")


def get_naics_code(row: dict) -> str:
    n = row.get("NAICS")
    if isinstance(n, dict):
        return str(n.get("code") or "")
    return ""


def get_naics_description(row: dict) -> str:
    n = row.get("NAICS")
    if isinstance(n, dict):
        return str(n.get("description") or "")
    return ""


def get_place_state(row: dict) -> str:
    return str(row.get("Place of Performance State Code") or "")


def get_description(row: dict) -> str:
    return str(row.get("Description") or "")
