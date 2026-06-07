"""realized_premium.py — wheel cost-basis support (Tranche 3 / F3).

The grab captures only recent IBKR fills (sparse, per-session), so to credit a
stock's basis with the premium the wheel has *already realized* on closed option
cycles we need the full execution history. daily_tracker persists each grab's
trades to the `trades` sheet (deduped); this module reads that ledger.

CONSERVATIVE BY DESIGN — read this before changing anything:
  adj_cost_basis feeds trading_rules.cc_allowed(), which requires a covered-call
  strike >= 115% of cost basis for blue-chips. OVER-counting premium pushes basis
  too low and could green-light a CC that locks in a loss. So every ambiguous
  case rounds toward UNDER-counting:
    * scope to the CURRENT holding (trades on/after the most recent stock buy) —
      never credit premium from a prior, already-exited position;
    * exclude currently-OPEN legs (daily_tracker already credits those via the
      live grab) — avoids double counting;
    * count only legs OPENED short (sell-to-open) — a long/directional leg's
      gain is not wheel premium, and crediting it would over-count;
    * net commissions out of every leg — premium is what you actually keep;
    * if the net is negative (bought back for more than collected) return 0 —
      this function only ever LOWERS basis, never raises it.
  Under-counting just leaves basis higher (more conservative CC gate); that is
  the safe direction. Incomplete history (a missed grab) therefore can't create
  risk, only conservatism.
"""
from __future__ import annotations


def _norm_strike(x) -> str:
    """Normalize a strike to a stable string so '95', '95.0', 95.0 all match."""
    try:
        return f"{float(x):.4f}"
    except (TypeError, ValueError):
        return str(x)


def option_key(right, strike, expiry) -> tuple:
    """Identity of an option contract — used to match open legs to ledger fills.
    Callers MUST build their open-option set with this same helper so strike
    formatting can't cause a silent mismatch."""
    return (str(right or "").upper(), _norm_strike(strike), str(expiry or ""))


def _num_key(x) -> str:
    """Canonicalize a numeric field so a grab float (95.0) and the sheet's
    formatted string ('95.00') produce the SAME key — otherwise dedup fails on
    read-back and every fill is re-appended daily."""
    try:
        return f"{float(x):.4f}"
    except (TypeError, ValueError):
        return str(x or "")


def trade_key(t: dict) -> tuple:
    """Natural identity of a fill — used to dedup the ledger across grabs.
    Numeric fields are canonicalized so float-vs-formatted-string can't mismatch."""
    return (
        str(t.get("time", "")), str(t.get("account", "")), str(t.get("symbol", "")),
        str(t.get("sec_type", "")), str(t.get("side", "")),
        str(t.get("right", "") or "").upper(), _num_key(t.get("strike", "")),
        str(t.get("expiry", "") or ""), _num_key(t.get("qty", "")), _num_key(t.get("price", "")),
    )


def new_trades(existing: list[dict], candidates: list[dict]) -> list[dict]:
    """Return only the candidate fills not already present in `existing`."""
    seen = {trade_key(t) for t in existing}
    out = []
    for c in candidates:
        k = trade_key(c)
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def realized_option_premium_per_share(
    trades: list[dict],
    ticker: str,
    shares: float,
    open_option_keys: set[tuple] | None = None,
) -> float:
    """Net realized option premium on `ticker` from CLOSED cycles, per share held.

    `trades`           — the full ledger (list of dicts with sec_type/side/right/
                         strike/expiry/qty/price/multiplier/time).
    `shares`           — current shares held (for the per-share conversion).
    `open_option_keys` — {(right, strike, expiry)} currently open; excluded so we
                         don't double-count legs daily_tracker already credits.

    Returns a value >= 0 (premium only lowers basis). Scoped to the current
    holding period (since the most recent stock BOT). See module docstring for
    the conservatism contract.
    """
    if shares <= 0:
        return 0.0
    open_keys = open_option_keys or set()
    sym_trades = [t for t in trades if str(t.get("symbol", "")) == ticker]

    # Current holding period: on/after the most recent stock purchase. Premium
    # from before that belongs to a prior position and must NOT reduce this basis.
    stk_buy_times = [
        str(t.get("time", "")) for t in sym_trades
        if str(t.get("sec_type", "")) == "STK" and str(t.get("side", "")) == "BOT"
        and t.get("time")
    ]
    since = max(stk_buy_times) if stk_buy_times else ""

    # Group in-window option fills by contract leg so we can require the leg was
    # OPENED short (sell-to-open) before crediting it. A leg whose first fill is a
    # BUY is a long/directional position (or an orphaned close whose opening sell
    # predates the ledger) — its P&L is not realized wheel premium, and crediting
    # it would OVER-count: the one direction this module must never go.
    legs: dict[tuple, list[dict]] = {}
    for t in sym_trades:
        if str(t.get("sec_type", "")) != "OPT":
            continue
        if since and str(t.get("time", "")) < since:
            continue
        key = option_key(t.get("right", ""), t.get("strike", ""), t.get("expiry", ""))
        if key in open_keys:
            continue  # still open — credited elsewhere by daily_tracker's ticker_credits
        legs.setdefault(key, []).append(t)

    net = 0.0
    for leg_trades in legs.values():
        leg_trades.sort(key=lambda t: str(t.get("time", "")))
        if str(leg_trades[0].get("side", "")) != "SLD":
            continue  # not opened short → not wheel premium (see comment above)
        for t in leg_trades:
            try:
                mult = float(t.get("multiplier", 100) or 100)
                qty = abs(float(t.get("qty", 0) or 0))
                price = float(t.get("price", 0) or 0)
                commission = abs(float(t.get("commission", 0) or 0))
            except (TypeError, ValueError):
                continue
            flow = price * qty * mult
            side = str(t.get("side", ""))
            if side == "SLD":
                net += flow       # credit received
            elif side == "BOT":
                net -= flow       # debit paid (buyback)
            net -= commission     # fees always reduce realized premium

    if net <= 0:
        return 0.0
    return net / shares


