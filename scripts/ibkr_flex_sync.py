#!/usr/bin/env python3
"""Headless IBKR position sync via the Flex Web Service.

No TWS, no IB Gateway, no interactive login — just a long-lived Flex token + a
Flex Query ID. This is the only IBKR path that runs unattended (incl. in cloud
CI), so it can keep the *real* book current on a schedule.

Flow (IBKR Flex Web Service v3):
  1. SendRequest(token, queryId)        -> ReferenceCode + GetStatement Url
  2. GetStatement(token, ReferenceCode) -> report XML, OR a "still generating"
     warning (code 1019/1001) which we poll through.

Auth: token from env IB_FLEX_TOKEN (CI secret / local export — NEVER committed).
Query: --query <id> or env IB_FLEX_QUERY_ID.

Usage:
  IB_FLEX_TOKEN=... python scripts/ibkr_flex_sync.py --query 1501198          # print positions
  IB_FLEX_TOKEN=... python scripts/ibkr_flex_sync.py --query 1501198 --json   # raw JSON
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

import requests

BASE = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService"


def _send_request(token: str, query_id: str, *, tries: int = 6, wait: float = 20.0) -> tuple[str, str]:
    """Step 1 — queue the report. Returns (reference_code, get_statement_url).

    SendRequest itself can return a transient Fail (1001 "try again shortly",
    1018 too-many-requests, 1019 generating) — common in the pre-market window
    when IBKR is regenerating statements. Retry with backoff before giving up.
    """
    last = ""
    for _ in range(tries):
        r = requests.get(f"{BASE}.SendRequest",
                         params={"t": token, "q": query_id, "v": "3"},
                         headers={"User-Agent": "casaa-flex-sync/1.0"}, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        status = (root.findtext("Status") or "").strip()
        if status == "Success":
            ref = (root.findtext("ReferenceCode") or "").strip()
            url = (root.findtext("Url") or f"{BASE}.GetStatement").strip()
            if not ref:
                raise RuntimeError(f"SendRequest: no ReferenceCode: {r.text[:400]}")
            return ref, url
        code = (root.findtext("ErrorCode") or "").strip()
        last = r.text[:400]
        if code in ("1001", "1018", "1019") or status == "Warn":
            time.sleep(wait); continue
        raise RuntimeError(f"SendRequest failed: {last}")
    raise RuntimeError(f"SendRequest still transient after {tries} tries: {last}")


def fetch_report(token: str, query_id: str, *, tries: int = 18, wait: float = 8.0) -> str:
    """Queue + poll until the Flex report XML is ready. Returns the report XML."""
    ref, url = _send_request(token, query_id)
    for attempt in range(tries):
        g = requests.get(url, params={"t": token, "q": ref, "v": "3"},
                         headers={"User-Agent": "casaa-flex-sync/1.0"}, timeout=90)
        g.raise_for_status()
        txt = g.text
        try:
            root = ET.fromstring(txt)
        except ET.ParseError:
            time.sleep(wait); continue
        # Success: the actual report is a FlexQueryResponse.
        if root.tag == "FlexQueryResponse" or root.find(".//OpenPosition") is not None:
            return txt
        # Still generating (Status=Warn, ErrorCode 1019/1001) -> poll again.
        code = (root.findtext("ErrorCode") or "").strip()
        status = (root.findtext("Status") or "").strip()
        if status == "Warn" or code in ("1019", "1001"):
            time.sleep(wait); continue
        raise RuntimeError(f"GetStatement error: {txt[:400]}")
    raise RuntimeError(f"Flex report {query_id} not ready after {tries} polls")


def parse_open_positions(report_xml: str) -> list[dict]:
    """Extract OpenPosition rows (stocks + options) as plain dicts."""
    root = ET.fromstring(report_xml)
    out = []
    for el in root.iter("OpenPosition"):
        a = el.attrib
        out.append({
            "account": a.get("accountId", ""),
            "asset": a.get("assetCategory", ""),     # STK | OPT | ...
            "symbol": a.get("symbol", ""),
            "qty": float(a.get("position", 0) or 0),
            "mark": float(a.get("markPrice", 0) or 0),
            "value": float(a.get("positionValue", 0) or 0),
            "cost_price": float(a.get("costBasisPrice", 0) or 0),
            "cost_money": float(a.get("costBasisMoney", 0) or 0),
            "upl": float(a.get("fifoPnlUnrealized", 0) or 0),
            # Option detail (blank for stocks)
            "put_call": a.get("putCall", ""),
            "strike": a.get("strike", ""),
            "expiry": a.get("expiry", ""),
            "multiplier": a.get("multiplier", ""),
            "underlying": a.get("underlyingSymbol", ""),
        })
    return out


def parse_account(report_xml: str) -> dict:
    """Best-effort account + equity summary (NLV/cash) from the report."""
    root = ET.fromstring(report_xml)
    info = {}
    ai = root.find(".//AccountInformation")
    if ai is not None:
        info["account"] = ai.attrib.get("accountId", "")
        info["currency"] = ai.attrib.get("currency", "")
        info["name"] = ai.attrib.get("name", "")
    # Latest equity summary row (NLV/cash/stock) if present.
    eq = list(root.iter("EquitySummaryByReportDateInBase"))
    if eq:
        last = eq[-1].attrib
        info["nlv"] = float(last.get("total", 0) or 0)
        info["cash"] = float(last.get("cash", 0) or 0)
        info["stock"] = float(last.get("stock", 0) or 0)
        info["report_date"] = last.get("reportDate", "")
    return info


def main() -> int:
    p = argparse.ArgumentParser(description="Headless IBKR position sync via Flex Web Service")
    p.add_argument("--query", default=os.environ.get("IB_FLEX_QUERY_ID", ""),
                   help="Flex Query ID (or env IB_FLEX_QUERY_ID)")
    p.add_argument("--json", action="store_true", help="Print raw parsed JSON")
    args = p.parse_args()

    token = os.environ.get("IB_FLEX_TOKEN", "").strip()
    if not token:
        print("IB_FLEX_TOKEN not set", file=sys.stderr)
        return 2
    if not args.query:
        print("No query id (--query or IB_FLEX_QUERY_ID)", file=sys.stderr)
        return 2

    report = fetch_report(token, args.query)
    positions = parse_open_positions(report)
    account = parse_account(report)

    if args.json:
        print(json.dumps({"account": account, "positions": positions}, indent=2))
        return 0

    stk = [p_ for p_ in positions if p_["asset"] == "STK"]
    opt = [p_ for p_ in positions if p_["asset"] == "OPT"]
    acct = account.get("account") or (positions[0]["account"] if positions else "?")
    print(f"Account {acct}  NLV ${account.get('nlv', 0):,.0f}  cash ${account.get('cash', 0):,.0f}"
          f"  (as of {account.get('report_date', '?')})")
    print(f"{len(stk)} stock positions, {len(opt)} option legs:\n")
    for s in sorted(stk, key=lambda x: -abs(x["value"])):
        print(f"  {s['symbol']:8} {s['qty']:>8.0f} @ ${s['mark']:>9.2f}  "
              f"= ${s['value']:>11,.0f}  UPL ${s['upl']:>+10,.0f}")
    for o in opt:
        print(f"  {o['underlying'] or o['symbol']:8} {o['qty']:>+4.0f} {o['put_call']}"
              f" {o['strike']} exp {o['expiry']}  UPL ${o['upl']:>+9,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
