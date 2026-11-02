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

Sarah's book (SGD base) is optional and INERT until configured. It is built
fresh from Flex when EITHER
  (a) the main report also carries her account (accounts linked under one
      login; the report is split by accountId), OR
  (b) env IB_FLEX_TOKEN_SARAH + IB_FLEX_QUERY_ID_SARAH are both set (her own
      login, her own Flex query).
Otherwise — or if her data is missing/incomplete/unfetchable — she is carried
forward exactly as before (never clobbered with emptiness) and Caspar's sync
still completes; the exit code is Caspar's. See
docs/runbooks/ibkr-flex-both-books.md.

Usage:
  IB_FLEX_TOKEN=... python scripts/ibkr_flex_sync.py --query 1501198          # print positions
  IB_FLEX_TOKEN=... python scripts/ibkr_flex_sync.py --query 1501198 --json   # raw JSON
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from typing import Callable, Mapping

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


def _iter_tagged(root: ET.Element, tag: str):
    """Yield (account_id, element) for every `tag` element in the report.

    A Flex report is FlexQueryResponse > FlexStatements > FlexStatement(accountId)
    > section > rows. A query covering several accounts is expected to carry one
    FlexStatement per account, but that is not something we could verify from
    IBKR's docs, so the account is resolved defensively: the row's own
    accountId wins, else the enclosing FlexStatement's, else "" (unlabelled —
    a bare/legacy single-account report). That handles both "one statement per
    account" and "rows from several accounts mixed in one statement".
    """
    stmts = list(root.iter("FlexStatement"))
    if not stmts:
        for el in root.iter(tag):
            yield (el.attrib.get("accountId") or "", el)
        return
    for st in stmts:
        sid = st.attrib.get("accountId") or ""
        for el in st.iter(tag):
            yield (el.attrib.get("accountId") or sid, el)


def _fx(v) -> float | None:
    """fxRateToBase as a positive float, or None when absent/blank/garbage."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def report_account_ids(report_xml: str) -> set[str]:
    """Every non-empty account id the report names (statements, rows, info)."""
    root = ET.fromstring(report_xml)
    ids = {st.attrib.get("accountId") or "" for st in root.iter("FlexStatement")}
    for tag in ("OpenPosition", "EquitySummaryByReportDateInBase", "AccountInformation"):
        ids.update(a for a, _ in _iter_tagged(root, tag))
    ids.discard("")
    return ids


def parse_open_positions(report_xml: str) -> list[dict]:
    """Extract OpenPosition rows (stocks + options) as plain dicts.

    All values are in the POSITION's own currency (`currency`); `fx_to_base`
    (Flex `fxRateToBase`) converts one unit of that currency to the account's
    base currency. Caspar is USD-base so it is 1 for his USD names.
    """
    root = ET.fromstring(report_xml)
    out = []
    for acct, el in _iter_tagged(root, "OpenPosition"):
        a = el.attrib
        out.append({
            "account": acct,
            "asset": a.get("assetCategory", ""),     # STK | OPT | ...
            "symbol": a.get("symbol", ""),
            "qty": float(a.get("position", 0) or 0),
            "mark": float(a.get("markPrice", 0) or 0),
            "value": float(a.get("positionValue", 0) or 0),
            "cost_price": float(a.get("costBasisPrice", 0) or 0),
            "cost_money": float(a.get("costBasisMoney", 0) or 0),
            "upl": float(a.get("fifoPnlUnrealized", 0) or 0),
            # Native currency + conversion to the account's base currency.
            "currency": (a.get("currency") or "").upper(),
            "fx_to_base": _fx(a.get("fxRateToBase")),
            "level": (a.get("levelOfDetail") or "").upper(),   # SUMMARY | LOT
            # Option detail (blank for stocks)
            "put_call": a.get("putCall", ""),
            "strike": a.get("strike", ""),
            "expiry": a.get("expiry", ""),
            "multiplier": a.get("multiplier", ""),
            "underlying": a.get("underlyingSymbol", ""),
        })
    # A query that ticks BOTH Summary and Lot detail returns each position
    # twice (one SUMMARY row + its LOT rows) — summing them would double the
    # share count. Where an account has SUMMARY rows, drop its LOT rows.
    summarised = {r["account"] for r in out if r["level"] == "SUMMARY"}
    return [r for r in out if not (r["level"] == "LOT" and r["account"] in summarised)]


def parse_account(report_xml: str, account_id: str | None = None,
                  *, unlabelled: bool = True) -> dict:
    """Best-effort account + equity summary (NLV/cash) for ONE account.

    A multi-account report holds one equity-summary row per account (and per
    report date); taking "the last row in the document" would hand the second
    account's NLV to the first. So rows are matched on `account_id`.
    `account_id=None` means "the first account the report names" (identical to
    the old behaviour for a single-account report). `unlabelled` also accepts
    rows that carry no account id at all (bare single-account reports).
    """
    root = ET.fromstring(report_xml)
    infos = list(_iter_tagged(root, "AccountInformation"))
    eqs = list(_iter_tagged(root, "EquitySummaryByReportDateInBase"))
    if account_id is None:
        account_id = next((a for a, _ in infos + eqs if a), "")

    def wanted(a: str) -> bool:
        return a == account_id or (unlabelled and a == "")

    info: dict = {}
    ai = next((el for a, el in infos if wanted(a)), None)
    if ai is not None:
        info["account"] = ai.attrib.get("accountId", "")
        info["currency"] = ai.attrib.get("currency", "")
        info["name"] = ai.attrib.get("name", "")
    # Latest equity summary row (NLV/cash/stock) by reportDate, if present.
    mine = [el for a, el in eqs if wanted(a)]
    if mine:
        last = max(enumerate(mine),
                   key=lambda t: (t[1].attrib.get("reportDate", ""), t[0]))[1].attrib
        info["nlv"] = float(last.get("total", 0) or 0)
        info["cash"] = float(last.get("cash", 0) or 0)
        info["stock"] = float(last.get("stock", 0) or 0)
        info["options"] = float(last.get("options", 0) or 0)
        info["report_date"] = last.get("reportDate", "")
        info["eq_currency"] = (last.get("currency") or "").upper()
        # Whether the query actually selected total + cash: absence must not
        # read as a genuine zero balance.
        info["eq_has_total_cash"] = "total" in last and "cash" in last
    return info


# ── PortfolioGrab JSON bridge (--sync) ──────────────────────────────────────
# Maps Flex rows into the exact JSON shape ibkr_grab.build_grab_json produces,
# so the existing `sync.py grab --json` pipeline (positions_caspar /
# snapshot_caspar / options tabs) works unchanged. Caspar comes fresh from
# Flex. Sarah is fresh from Flex only when her data is present AND complete
# (see resolve_sarah); otherwise she is CARRIED FORWARD from the latest
# existing grab file — never clobber her data with emptiness.
#
# UNITS (Sarah, SGD base) — must match what the TWS grab wrote, because the
# Sheet tabs, yahoo_grab.py and the PWA (lib/sgxFx.ts toAcctCcy) all assume it:
#   * positions[] / options[]  (avg_cost, last, mkt_val, upl) are in each
#     position's NATIVE currency (USD for US names, SGD for SGX) — exactly what
#     ib_insync's portfolio() returned. They are NOT converted: the PWA
#     multiplies USD rows by USDSGD itself at read time, so pre-converting here
#     would apply the FX rate twice.
#   * summary net_liquidation_sgd / total_cash_sgd are SGD (account base).
#   * summary unrealized_pnl_mixed feeds Sheet column upl_sgd, so it is SGD:
#     sum(native upl x Flex fxRateToBase). (The TWS grab always wrote 0 here;
#     yahoo_grab / daily_tracker later overwrite it with the same SGD sum.)
#   * Flex OpenPosition values are in the position currency; fxRateToBase
#     (position ccy -> base) is used only for those aggregates and weight_pct.

CASPAR_ACCOUNT = "U6773281"
SARAH_ACCOUNT = "U16000287"
SARAH_BASE = "SGD"
ENV_SARAH_TOKEN = "IB_FLEX_TOKEN_SARAH"
ENV_SARAH_QUERY = "IB_FLEX_QUERY_ID_SARAH"
GRABS_DIR = "PortfolioGrabs"


def flex_cost_price(p: dict, multiplier: float = 1.0) -> float:
    """PER-SHARE cost basis from a Flex OpenPosition row.

    `costBasisPrice` is the direct field, but Flex has been returning it empty
    for this account since ~2026-06-10 — which wrote avg_cost 0 into the sheet
    and made every position read as pure profit. `costBasisMoney` is a
    separate column on the same row and survives when the price one does not,
    so derive from it.

    costBasisMoney = costBasisPrice x qty x multiplier, so options MUST pass
    their multiplier: dividing by qty alone leaves a PER-CONTRACT figure, and
    the option caller then scales by the multiplier a second time — a 100x
    overstatement. abs() on both because a short's cost money and quantity are
    negative while the per-share basis is not.
    """
    direct = float(p.get("cost_price", 0) or 0)
    if direct:
        return direct
    money = float(p.get("cost_money", 0) or 0)
    qty = float(p.get("qty", 0) or 0)
    # A 0 multiplier means the contract size is unknown — return 0 (== "no
    # cost basis") rather than silently defaulting to 1 and emitting a figure
    # that is wrong by the contract size.
    mult = float(multiplier)
    if not money or not qty or not mult:
        return 0.0
    return abs(money) / (abs(qty) * mult)


def _flex_stock_row(p: dict, nlv: float, to_base: bool = False) -> dict:
    """Stock row in the position's NATIVE currency.

    `to_base` only affects weight_pct: `nlv` is in the account's base currency,
    so a native-currency mkt_val is scaled by fx_to_base first. Left False for
    Caspar (unchanged behaviour); True for Sarah, whose book mixes USD and SGD.
    """
    mkt_val = p["value"]
    cost_price = flex_cost_price(p)
    upl = p["upl"] or round((p["mark"] - cost_price) * p["qty"], 2)
    fx = (p.get("fx_to_base") or 1.0) if to_base else 1.0
    return {
        "symbol": p["symbol"], "sec_type": "STK", "exchange": "",
        "qty": p["qty"], "avg_cost": cost_price, "last": p["mark"],
        "mkt_val": mkt_val, "upl": upl,
        "weight_pct": round(abs(mkt_val) * fx / nlv * 100, 2) if nlv else 0,
    }


def _flex_option_row(p: dict) -> dict:
    mult = int(float(p["multiplier"] or 100))
    # Flex costBasisPrice is PER SHARE; the grab schema (ib_insync averageCost)
    # carries options PER CONTRACT — scale by the multiplier to match.
    cost_price = flex_cost_price(p, mult)
    avg_cost = round(cost_price * mult, 2)
    upl = p["upl"] or round((p["mark"] - cost_price) * p["qty"] * mult, 2)
    side_dir = "short" if p["qty"] < 0 else "long"
    side_type = "call" if p["put_call"] == "C" else "put"
    return {
        "symbol": p["underlying"] or p["symbol"].split()[0],
        "sec_type": "OPT", "exchange": "",
        "qty": p["qty"], "avg_cost": avg_cost, "last": p["mark"],
        "mkt_val": p["value"], "upl": upl,
        "side": f"{side_dir}_{side_type}",
        "right": p["put_call"], "strike": float(p["strike"] or 0),
        "expiry": str(p["expiry"] or "").replace("-", ""),
        "multiplier": mult, "avg_cost_credit": abs(avg_cost),
    }


def _latest_grab(root: str) -> dict:
    """Newest existing PortfolioGrab JSON (for the Sarah carry-forward)."""
    import glob
    paths = sorted(glob.glob(os.path.join(root, "*_PortfolioGrab.json")))
    if not paths:
        return {}
    try:
        return json.loads(open(paths[-1]).read())
    except Exception:
        return {}


class SarahDataError(ValueError):
    """Sarah's Flex data is absent/incomplete — carry her forward instead.

    Messages are shown in public CI logs: reasons only, never values.
    """


def build_sarah_block(account: dict, positions: list[dict], prev_summary: dict) -> dict:
    """Sarah's `accounts.sarah` block from Flex rows already scoped to her.

    Raises SarahDataError unless the data is complete enough to overwrite her
    Sheet rows safely. See the UNITS note above for what each field means.
    """
    if not positions and not account:
        raise SarahDataError("no rows for her account in the report")
    nlv = float(account.get("nlv", 0) or 0)
    if not account.get("eq_has_total_cash") or nlv <= 0:
        raise SarahDataError("no equity summary with total + cash")
    base = (account.get("currency") or account.get("eq_currency") or "").upper()
    if not base:
        raise SarahDataError("base currency not in report (select currency)")
    if base != SARAH_BASE:
        raise SarahDataError(f"base currency is {base}, expected {SARAH_BASE}")
    stock_sgd = float(account.get("stock", 0) or 0)
    if not positions and (stock_sgd or float(account.get("options", 0) or 0)):
        # Equity summary says she holds something but the position section is
        # missing — writing an empty book would erase her holdings.
        raise SarahDataError("equity summary shows holdings but no open positions came back")

    stocks, options, upl_sgd = [], [], 0.0
    for p in positions:
        if p["asset"] not in ("STK", "OPT"):
            continue
        fx = p.get("fx_to_base")
        if not fx:
            if (p.get("currency") or "").upper() != base:
                raise SarahDataError("a position has no fxRateToBase (select it)")
            fx = 1.0
        p = {**p, "fx_to_base": fx}
        row = (_flex_stock_row(p, nlv, to_base=True) if p["asset"] == "STK"
               else _flex_option_row(p))
        (stocks if p["asset"] == "STK" else options).append(row)
        upl_sgd += row["upl"] * fx          # native upl -> SGD for the aggregate only

    return {
        "account_id": SARAH_ACCOUNT,
        "base_currency": SARAH_BASE,
        "summary": {
            "net_liquidation_sgd": nlv,
            # Flex EOD statements carry no margin fields — carry the previous
            # grab's values rather than writing 0s (same as Caspar).
            "buying_power_sgd": float(prev_summary.get("buying_power_sgd", 0) or 0),
            "total_cash_sgd": float(account.get("cash", 0) or 0),
            "unrealized_pnl_mixed": round(upl_sgd, 2),    # SGD despite the legacy key name
            "realized_pnl": 0.0,
            "excess_liquidity_sgd": float(prev_summary.get("excess_liquidity_sgd", 0) or 0),
            "total_market_value_mixed": stock_sgd,         # SGD (equity-summary stock, base ccy)
        },
        "positions": stocks,
        "options": options,
        "trades": [],
    }


def _sarah_from_report(report_xml: str, prev_summary: dict, *, unlabelled: bool) -> dict:
    """Her block out of one report. `unlabelled`: rows with no accountId are
    hers (true for her own login's report, false when split from the main one,
    where unlabelled rows belong to Caspar)."""
    wanted = lambda a: a == SARAH_ACCOUNT or (unlabelled and a == "")   # noqa: E731
    rows = [p for p in parse_open_positions(report_xml) if wanted(p["account"])]
    account = parse_account(report_xml, SARAH_ACCOUNT, unlabelled=unlabelled)
    return build_sarah_block(account, rows, prev_summary)


def _safe_err(e: BaseException, *secrets: str) -> str:
    """One-line, secret-free description of a failure for public CI logs.

    requests' exceptions embed the full URL — including the `t=<token>` query
    parameter — so for those only the class name is kept.
    """
    name = type(e).__name__
    if isinstance(e, requests.RequestException):
        return name
    msg = " ".join(str(e).split())
    for s in secrets:
        if s:
            msg = msg.replace(s, "***")
    msg = re.sub(r"([?&]t=)[^&\s]+", r"\1***", msg)
    return f"{name}: {msg[:160]}"


def resolve_sarah(main_report: str, prev_grab: dict, env: Mapping[str, str],
                  fetch: Callable[[str, str], str] | None = None) -> tuple[dict | None, str]:
    """Decide how Sarah's book is produced. Never raises.

    Returns (fresh_block, status_line). A None block means "carry forward" and
    the caller keeps today's behaviour. The status line is printed as-is, so it
    carries reasons only — no balances, share counts, tokens or query ids.
    """
    fetch = fetch or fetch_report
    prev = ((prev_grab.get("accounts") or {}).get("sarah") or {}).get("summary") or {}
    token = (env.get(ENV_SARAH_TOKEN) or "").strip()
    qid = (env.get(ENV_SARAH_QUERY) or "").strip()
    reasons: list[str] = []

    # (a) Accounts linked under one login: she is already in the main report.
    try:
        if SARAH_ACCOUNT in report_account_ids(main_report):
            return (_sarah_from_report(main_report, prev, unlabelled=False),
                    "sarah: fresh from Flex (split from the main report by accountId)")
    except Exception as e:                                  # noqa: BLE001
        reasons.append(f"main report has her account but it is unusable ({_safe_err(e)})")

    # (b) Her own login: second token + query.
    if token and qid:
        try:
            return (_sarah_from_report(fetch(token, qid), prev, unlabelled=True),
                    "sarah: fresh from Flex (second report)")
        except Exception as e:                              # noqa: BLE001
            reasons.append(f"second report unusable ({_safe_err(e, token, qid)})")
    elif token or qid:
        reasons.append(f"{ENV_SARAH_QUERY if token else ENV_SARAH_TOKEN} is not set")

    if not reasons:
        return None, "sarah: carried forward (no Sarah credentials set, her account not in the main report)"
    return None, "sarah: carried forward — " + "; ".join(reasons)


def build_flex_grab(account: dict, positions: list[dict], prev_grab: dict,
                    sarah: dict | None = None) -> dict:
    """Assemble the PortfolioGrab JSON: fresh Flex Caspar + Sarah.

    `sarah` is a complete block from build_sarah_block, or None to carry her
    forward verbatim from `prev_grab` (the original behaviour).
    """
    from datetime import datetime
    nlv = float(account.get("nlv", 0) or 0)
    # Caspar's rows ONLY — when the Flex report also carries Sarah's account
    # (U16000287), her rows must not leak into his book; they go through
    # build_sarah_block instead.
    mine = [p for p in positions
            if (p.get("account") or CASPAR_ACCOUNT) == CASPAR_ACCOUNT]
    stocks = [_flex_stock_row(p, nlv) for p in mine if p["asset"] == "STK"]
    options = [_flex_option_row(p) for p in mine if p["asset"] == "OPT"]
    prev_caspar_summary = ((prev_grab.get("accounts") or {}).get("caspar") or {}).get("summary", {})
    now = datetime.now()
    return {
        "grab_date": now.strftime("%Y-%m-%d"),
        "grab_timestamp_sgt": now.astimezone().isoformat(),
        "source": f"IBKR Flex Web Service (EOD statement {account.get('report_date', '?')})",
        "schema_version": "1.1",
        "writer": "ibkr_flex_sync.py",
        "accounts": {
            "caspar": {
                "account_id": account.get("account") or CASPAR_ACCOUNT,
                "base_currency": account.get("currency") or "USD",
                "summary": {
                    "net_liquidation": nlv,
                    "total_cash": float(account.get("cash", 0) or 0),
                    # Flex EOD statements don't carry margin fields — carry the
                    # previous grab's values forward rather than writing 0s that
                    # downstream sizing could misread as "no buying power".
                    "buying_power": float(prev_caspar_summary.get("buying_power", 0)),
                    "excess_liquidity": float(prev_caspar_summary.get("excess_liquidity", 0)),
                    "unrealized_pnl": round(sum(s["upl"] for s in stocks)
                                            + sum(o["upl"] for o in options), 2),
                    "realized_pnl": 0.0,
                    "total_market_value": float(account.get("stock", 0) or 0),
                },
                "positions": stocks,
                "options": options,
                "trades": [],
            },
            # Sarah: fresh from Flex when resolve_sarah produced a complete
            # block; otherwise carried verbatim from the latest grab (same role
            # as ibkr_grab --merge). With no prior grab (CI) the carried block
            # is empty, which sync.py's per-account gate skips — her existing
            # Sheet rows are left untouched, never overwritten with emptiness.
            "sarah": (sarah if sarah is not None
                      else ((prev_grab.get("accounts") or {}).get("sarah")
                            or {"account_id": SARAH_ACCOUNT, "base_currency": SARAH_BASE,
                                "summary": {}, "positions": [], "options": [], "trades": []})),
        },
    }


def run_sync(report: str, root: str, env: Mapping[str, str], *,
             fetch: Callable[[str, str], str] | None = None,
             runner: Callable | None = None) -> int:
    """Build + write the grab JSON and push it through `sync.py grab`.

    Sarah is resolved AFTER Caspar's report is already in hand and can never
    raise out of here, so a problem on her side cannot fail his sync. The
    return value is sync.py's exit code, i.e. Caspar's (and Sarah's, when
    fresh) write result.
    """
    import subprocess
    runner = runner or subprocess.run
    positions = parse_open_positions(report)
    account = parse_account(report, CASPAR_ACCOUNT)
    out_dir = os.path.join(root, GRABS_DIR)
    prev = _latest_grab(out_dir)
    try:
        sarah, sarah_status = resolve_sarah(report, prev, env, fetch)
    except Exception as e:                                  # noqa: BLE001 — belt and braces
        sarah, sarah_status = None, f"sarah: carried forward — unexpected error ({_safe_err(e)})"
    grab = build_flex_grab(account, positions, prev, sarah)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{grab['grab_date'].replace('-', '')}_PortfolioGrab.json")
    with open(out_path, "w") as f:
        json.dump(grab, f, indent=2)
    print(f"Saved {out_path} "
          f"({len(grab['accounts']['caspar']['positions'])} stocks, "
          f"{len(grab['accounts']['caspar']['options'])} option legs)")
    print(sarah_status)
    r = runner([sys.executable, "src/sync.py", "grab", "--json", out_path], cwd=root)
    return r.returncode


def main() -> int:
    p = argparse.ArgumentParser(description="Headless IBKR position sync via Flex Web Service")
    p.add_argument("--query", default=os.environ.get("IB_FLEX_QUERY_ID", ""),
                   help="Flex Query ID (or env IB_FLEX_QUERY_ID)")
    p.add_argument("--json", action="store_true", help="Print raw parsed JSON")
    p.add_argument("--sync", action="store_true",
                   help="Write the PortfolioGrab JSON and push it to the Sheet via sync.py grab")
    args = p.parse_args()

    token = os.environ.get("IB_FLEX_TOKEN", "").strip()
    if not token:
        print("IB_FLEX_TOKEN not set", file=sys.stderr)
        return 2
    if not args.query:
        print("No query id (--query or IB_FLEX_QUERY_ID)", file=sys.stderr)
        return 2

    report = fetch_report(token, args.query)

    if args.json:
        # Local debugging only: every account in the report, tagged by `account`.
        print(json.dumps({"account": parse_account(report, CASPAR_ACCOUNT),
                          "positions": parse_open_positions(report)}, indent=2))
        return 0

    if args.sync:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return run_sync(report, root, os.environ)

    positions = parse_open_positions(report)
    account = parse_account(report, CASPAR_ACCOUNT)

    # Interactive print is Caspar's book only (a report that also carries
    # Sarah's account must not show her rows as his).
    positions = [p_ for p_ in positions
                 if (p_.get("account") or CASPAR_ACCOUNT) == CASPAR_ACCOUNT]
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
