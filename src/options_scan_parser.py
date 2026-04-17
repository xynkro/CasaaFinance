"""
options_scan_parser.py — Parse ad-hoc options scan markdown files into
OptionRecommendationRow instances.

Handles format:
    ### SELL_TO_OPEN HIMS $14.5P ~May24 (37d) — Sarah

    | Metric | Value |
    |--------|-------|
    | Delta | -0.158 |
    | Premium | $0.71 per share ($71 per contract) |
    | Annualised yield | 48.0% |
    | Cash required | $1,450 per contract |
    | Breakeven if assigned | $13.79 |
    | Target entry price | $15.00 |
    | IV Rank | 68 |

    **(Judgement)** ... Confidence 0.72.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

# ### SELL_TO_OPEN HIMS $14.5P ~May24 (37d) — Sarah
CANDIDATE_RE = re.compile(
    r"###\s+(?P<action>SELL_TO_OPEN|BUY_TO_OPEN|CLOSE)\s+"
    r"(?P<ticker>[A-Z]+)\s+\$(?P<strike>[\d.]+)(?P<right>[PC])\s+"
    r"~?(?P<expiry>[^\s(]+)(?:\s*\((?P<dte>\d+)d\))?\s*—\s*(?P<account>\w+)",
    re.IGNORECASE,
)

# | Premium | $0.71 per share ($71 per contract) |
PREMIUM_RE = re.compile(r"\|\s*Premium\s*\|\s*\$([\d.]+)", re.IGNORECASE)
DELTA_RE = re.compile(r"\|\s*Delta\s*\|\s*(-?[\d.]+)", re.IGNORECASE)
YIELD_RE = re.compile(r"\|\s*Annualised yield\s*\|\s*([\d.]+)%", re.IGNORECASE)
CASH_RE = re.compile(r"\|\s*Cash required\s*\|\s*\$([\d,]+)", re.IGNORECASE)
BREAKEVEN_RE = re.compile(r"\|\s*Breakeven(?:\s+if\s+assigned)?\s*\|\s*\$([\d.]+)", re.IGNORECASE)
IV_RANK_RE = re.compile(r"\|\s*IV Rank\s*\|\s*([\d.]+)", re.IGNORECASE)

# **(Judgement)** ... Confidence 0.72.
JUDGE_RE = re.compile(r"\*\*\(Judg(?:e)?ment\)\*\*\s+(.+?)(?=\n\n|\Z)", re.DOTALL)
CONFIDENCE_RE = re.compile(r"Confidence\s+(?:is\s+)?(\d+\.?\d*)", re.IGNORECASE)


def _extract_float(pattern: re.Pattern, block: str, default: float = 0.0) -> float:
    m = pattern.search(block)
    if not m:
        return default
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return default


def _normalize_expiry(raw: str) -> str:
    """Turn 'May24', '2026-05-24', '20260524' into 'YYYYMMDD' when possible."""
    raw = raw.strip().replace(",", "")
    # 8-digit YYYYMMDD
    if re.fullmatch(r"\d{8}", raw):
        return raw
    # YYYY-MM-DD
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    # MonDay format (e.g. May24 = May 24) — ambiguous on year, leave as-is
    return raw


def parse_scan_file(
    md_path: Path,
    date: str,
) -> List[dict]:
    """
    Parse an options scan markdown file. Returns a list of dicts suitable for
    OptionRecommendationRow construction.
    """
    text = md_path.read_text()
    results = []

    # Split on ### headers — each candidate is its own section
    sections = re.split(r"^###\s+", text, flags=re.MULTILINE)

    for section in sections[1:]:  # first split is the preamble
        # Re-add the ### for the regex
        block = "### " + section
        m = CANDIDATE_RE.search(block)
        if not m:
            continue

        action = m.group("action").upper()
        ticker = m.group("ticker")
        strike = float(m.group("strike"))
        right = m.group("right").upper()
        expiry_raw = m.group("expiry")
        account = m.group("account").lower()

        # Infer strategy from action + right
        if action == "SELL_TO_OPEN" and right == "P":
            strategy = "CSP"
        elif action == "SELL_TO_OPEN" and right == "C":
            strategy = "CC"
        elif action == "BUY_TO_OPEN" and right == "C":
            strategy = "LONG_CALL"
        elif action == "BUY_TO_OPEN" and right == "P":
            strategy = "LONG_PUT"
        else:
            strategy = action

        # Judgement block
        judge_m = JUDGE_RE.search(block)
        thesis = judge_m.group(1).strip() if judge_m else ""
        thesis = re.sub(r"\s+", " ", thesis)[:500]

        conf_m = CONFIDENCE_RE.search(thesis or "")
        thesis_confidence = float(conf_m.group(1)) if conf_m else 0.0

        results.append({
            "date": date,
            "source": md_path.name,
            "account": account,
            "ticker": ticker,
            "strategy": strategy,
            "right": right,
            "strike": strike,
            "expiry": _normalize_expiry(expiry_raw),
            "premium_per_share": _extract_float(PREMIUM_RE, block),
            "delta": _extract_float(DELTA_RE, block),
            "annual_yield_pct": _extract_float(YIELD_RE, block),
            "breakeven": _extract_float(BREAKEVEN_RE, block),
            "cash_required": _extract_float(CASH_RE, block),
            "iv_rank": _extract_float(IV_RANK_RE, block),
            "thesis_confidence": thesis_confidence,
            "thesis": thesis,
            "status": "proposed",
        })

    return results


def scan_file_is_options(md_path: Path) -> bool:
    """Quick check: does the filename suggest it's an options scan?"""
    name = md_path.name.lower()
    return "options" in name or "option_scan" in name or "options_scan" in name


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("Usage: options_scan_parser.py <markdown_file> [date]")
        sys.exit(1)
    path = Path(sys.argv[1])
    date = sys.argv[2] if len(sys.argv) > 2 else "2026-01-01"
    out = parse_scan_file(path, date)
    print(json.dumps(out, indent=2))
