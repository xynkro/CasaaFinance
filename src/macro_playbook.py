"""
macro_playbook.py — the FREE, non-canned "so what" on macro releases.

The keyword-heuristic "so what" on news *headlines* failed (it just restated the
headline). This works because it keys off STRUCTURED data — a macro release's
ACTUAL vs FORECAST — not free text. The number tells you the surprise; the
playbook maps (event, surprise direction) → a specific, tailored implication.
Zero AI tokens, and it can't degrade into filler because it's anchored to a real
beat/miss.

Tailored to Caspar's book: premium seller (CSP/CC/credit spreads) on a
growth-tilted core-satellite (QQQ core + momentum) with an IEF/GLD/VIXM hedge.
"""
from __future__ import annotations

# Each event type maps to what a HIGHER-than-forecast print implies:
#   hawkish  — rates higher-for-longer (inflation hot, jobs strong, Fed hike)
#   dovish   — cuts more likely (unemployment up, claims up)
#   risk_on  — growth strong (GDP, retail, ISM/PMI)
# A MISS flips the lean to its opposite.
_PLAYBOOK: list[tuple[tuple[str, ...], str, str]] = [
    # (match substrings, label, hot_is)
    (("core pce", "pce price"),                 "Core PCE",          "hawkish"),
    (("core cpi",),                             "Core CPI",          "hawkish"),
    (("cpi", "consumer price"),                 "CPI",               "hawkish"),
    (("ppi", "producer price"),                 "PPI",               "hawkish"),
    (("average hourly earnings",),              "Avg Hourly Earnings", "hawkish"),
    (("nonfarm payroll", "non-farm payroll", "nfp"), "Nonfarm Payrolls", "hawkish"),
    (("unemployment rate",),                    "Unemployment Rate", "dovish"),
    (("initial jobless claims", "jobless claims"), "Jobless Claims", "dovish"),
    (("fed interest rate", "fed funds", "fomc", "interest rate decision"),
                                                "Fed Decision",      "hawkish"),
    (("gdp",),                                  "GDP",               "risk_on"),
    (("retail sales",),                         "Retail Sales",      "risk_on"),
    (("ism", "pmi"),                            "ISM/PMI",           "risk_on"),
]

_OPPOSITE = {"hawkish": "dovish", "dovish": "hawkish",
             "risk_on": "risk_off", "risk_off": "risk_on"}

# lean → (market take, book note for Caspar)
_LEAN = {
    "hawkish": (
        "rate-cut odds fall → pressure on duration + growth multiples; USD firmer.",
        "QQQ core + momentum face multiple compression; IEF/TLT soften. "
        "Premium-selling: richer IV aids theta, but widen short strikes — gap risk up.",
    ),
    "dovish": (
        "rate-cut odds rise → supportive for duration + growth; USD softer.",
        "tailwind for the QQQ core + IEF; gold often firms. Premium-selling: vol "
        "may compress (less credit) but pins favour your short strikes.",
    ),
    "risk_on": (
        "growth-positive; equities supported (watch the hawkish-rates second-order).",
        "supports QQQ core + the momentum satellite; the hedge sleeve drags today "
        "— fine, it's insurance.",
    ),
    "risk_off": (
        "growth-negative; defensive bid, equities pressured.",
        "your IEF/GLD/VIXM hedge earns its keep; momentum satellite is most "
        "exposed — respect the stops.",
    ),
}


def _f(v) -> float | None:
    try:
        return float(str(v).replace(",", "").replace("%", "").replace("K", "").strip())
    except (TypeError, ValueError):
        return None


def _match(event: str) -> tuple[str, str] | None:
    e = (event or "").lower()
    for subs, label, hot_is in _PLAYBOOK:
        if any(s in e for s in subs):
            return label, hot_is
    return None


def interpret_surprise(event: str, actual, forecast, previous=None,
                       unit: str = "") -> dict | None:
    """Return a tailored 'so what' for a macro release, or None when there's no
    playbook match / no forecast / the print is in line (no surprise to flag).

    Keys: label, actual, forecast, previous, unit, direction (BEAT|MISS),
    lean, market_take, book_note.
    """
    m = _match(event)
    if not m:
        return None
    label, hot_is = m
    a, fc = _f(actual), _f(forecast)
    if a is None or fc is None:
        return None                      # need both to compute a surprise

    delta = a - fc
    tol = max(0.1, 0.03 * abs(fc))       # skip trivially in-line prints
    if abs(delta) < tol:
        return None

    direction = "BEAT" if a > fc else "MISS"
    lean = hot_is if a > fc else _OPPOSITE[hot_is]
    market_take, book_note = _LEAN[lean]
    return {
        "label": label,
        "actual": a, "forecast": fc, "previous": _f(previous),
        "unit": unit or "",
        "direction": direction,
        "lean": lean,
        "market_take": market_take,
        "book_note": book_note,
    }
