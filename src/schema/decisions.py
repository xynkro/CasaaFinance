"""Decision-queue, daily-brief, WSR archive/summary, daily-plan, curated-picks,
API-usage, trigger-alert + telegram-offset schemas, and their factory helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ._base import _num, _ts_suffix


@dataclass
class DecisionRow:
    TAB_NAME = "decision_queue"
    HEADERS = [
        "date", "account", "ticker", "bucket", "thesis_1liner", "conv", "entry", "target", "status",
        # Unified options-spec extension (Phase A of decisions-ideas-merge).
        # All fields below are optional — share entries default to "" / 0.
        "strategy",            # "" | "BUY_DIP" | "TRIM" | "CSP" | "CC" | "PMCC" | "LONG_CALL" | "LONG_PUT"
        "right",               # "" | "C" | "P"
        "strike",              # 0 for share entries
        "expiry",              # "" | "YYYYMMDD"
        "premium_per_share",   # 0 for shares
        "delta",               # 0 for shares
        "annual_yield_pct",    # 0 for shares
        "breakeven",           # 0 if not applicable
        "cash_required",       # 0 if not applicable
        "iv_rank",             # 0 if not applicable (0-100 scale)
        "thesis_confidence",   # 0.0 - 1.0 (brain analytic signal, separate from gut-feel `conv`)
        "thesis",              # full multi-sentence brain thesis (separate from thesis_1liner)
        "source",              # "" | "wsr_full" | "wsr_lite" | "manual" | "risk_parity"
        # --- accumulation extension (Phase 5b — Risk Parity tranche plans) ---
        # Both fields appended at END so existing index-based access in
        # push_decisions / risk_parity_recommend (which reads r[9]=strategy,
        # r[11]=strike for upsert keys) is preserved.
        "qty",                 # planned total share/contract count (int as string; 0 if unknown)
        "accumulation_plan",   # pipe-separated tranches: "5sh now | 5sh +30d | 5sh on -5% pullback to $79.20"
        # --- structured gates (Phase 6 — TriggerBadge reliability) ---
        # JSON-encoded array of gate strings, format "<type>:<required>".
        # Replaces brittle accumulation_plan string-parsing in the PWA's
        # evaluateTrigger(). Recognised types: exposure, tv_daily, tv_weekly,
        # earnings_clear (no required value), regime_above:<score>.
        # Empty string = no gates → treat trigger as ungated.
        # Examples:
        #   '["exposure:NEW_ENTRY_ALLOWED", "tv_daily:BUY"]'
        #   '["earnings_clear"]'
        "gates",
    ]

    date: str
    account: str          # "caspar" | "sarah"
    ticker: str
    bucket: str           # e.g. "BUY NOW" | "WATCH" | "CSP" | "PMCC" | "WHEEL"
    thesis_1liner: str
    conv: float           # 1-5 gut-feel conviction (kept distinct from thesis_confidence)
    entry: float
    target: float
    status: str           # "pending" | "watching" | "filled" | "killed" | "expired"
    # --- options-spec extension (all optional, default to "" / 0 for share entries) ---
    strategy: str = ""
    right: str = ""
    strike: float = 0.0
    expiry: str = ""
    premium_per_share: float = 0.0
    delta: float = 0.0
    annual_yield_pct: float = 0.0
    breakeven: float = 0.0
    cash_required: float = 0.0
    iv_rank: float = 0.0
    thesis_confidence: float = 0.0
    thesis: str = ""
    source: str = ""
    # --- accumulation extension (Phase 5b) ---
    qty: int = 0
    accumulation_plan: str = ""
    # --- structured gates (Phase 6) ---
    # JSON-encoded array of gate strings (or empty). The push_decisions
    # script accepts either a pre-encoded string OR a list[str] and
    # normalises to a JSON string before storing.
    gates: str = ""

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.account, self.ticker, self.bucket, self.thesis_1liner,
            _num(self.conv, 0), _num(self.entry, 4), _num(self.target, 4), self.status,
            self.strategy, self.right,
            _num(self.strike, 2), self.expiry,
            _num(self.premium_per_share, 4), _num(self.delta, 4),
            _num(self.annual_yield_pct, 2), _num(self.breakeven, 2),
            _num(self.cash_required, 2), _num(self.iv_rank, 0),
            _num(self.thesis_confidence, 2), self.thesis, self.source,
            str(int(self.qty)) if self.qty else "",
            self.accumulation_plan,
            self.gates,
        ]


@dataclass
class DailyBriefRow:
    TAB_NAME = "daily_brief_latest"
    HEADERS = [
        "date", "bullet_1", "bullet_2", "bullet_3", "verdict", "sentiment",
        "headline", "overnight", "premarket", "catalysts", "commodities",
        "posture", "watch", "raw_md",
        "earnings_today", "macro_today", "negative_news", "insider_alert",
        "gov_confluence",
    ]

    date: str
    bullet_1: str = ""
    bullet_2: str = ""
    bullet_3: str = ""
    verdict: str = ""
    sentiment: str = ""
    headline: str = ""      # opening line of the brief (big summary)
    overnight: str = ""     # e.g. "S&P 6,886 (+1.02%) | Nasdaq +1.23% | VIX 18.59 -2.77%"
    premarket: str = ""     # e.g. "ES +0.22% | Brent $99 | Gold $4,748"
    catalysts: str = ""     # pipe-separated, e.g. "20:30 PPI|Fed speakers|Q1 earnings"
    commodities: str = ""   # pipe-separated, e.g. "WTI $93 | Gold $4800 | USD/SGD 1.2733"
    posture: str = ""       # free text, e.g. "POSTURE CHANGE: YES. ..."
    watch: str = ""         # pipe-separated watchlist items
    raw_md: str = ""        # full original brief text for in-app detail view
    earnings_today: str = ""   # pipe-separated, e.g. "NVDA AMC est $1.79|WIX BMO est $1.26"
    macro_today: str = ""      # pipe-separated, e.g. "13:30 US CPI MoM est 0.3%|Fed Cook 09:45 ET"
    negative_news: str = ""    # pipe-separated, e.g. "BYND -0.7 'Restructuring talks fail'"
    insider_alert: str = ""    # pipe-separated, e.g. "NVDA Huang sold 50k @ $213 = $10.6M"
    gov_confluence: str = ""   # pipe-separated, e.g. "AVAV score 87 Tier-A → BUY_DIP"

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.bullet_1, self.bullet_2, self.bullet_3, self.verdict, self.sentiment,
            self.headline, self.overnight, self.premarket, self.catalysts, self.commodities,
            self.posture, self.watch, self.raw_md,
            self.earnings_today, self.macro_today, self.negative_news,
            self.insider_alert, self.gov_confluence,
        ]


@dataclass
class WsrArchiveRow:
    TAB_NAME = "wsr_archive"
    HEADERS = ["date", "title", "drive_file_id", "drive_url"]

    date: str
    title: str
    drive_file_id: str
    drive_url: str = ""

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        url = self.drive_url or f"https://drive.google.com/file/d/{self.drive_file_id}/view"
        return [d, self.title, self.drive_file_id, url]


@dataclass
class WsrSummaryRow:
    """Latest WSR markdown parsed into a structured summary for the Home page."""
    TAB_NAME = "wsr_summary"
    HEADERS = [
        "date", "source", "verdict", "confidence", "regime",
        "macro_read", "action_summary", "options_summary",
        "redteam_summary", "week_events", "raw_md",
    ]

    date: str
    source: str
    verdict: str
    confidence: float
    regime: str
    macro_read: str
    action_summary: str
    options_summary: str
    redteam_summary: str = ""
    week_events: str = ""
    raw_md: str = ""

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.source, self.verdict, _num(self.confidence, 2),
            self.regime, self.macro_read, self.action_summary,
            self.options_summary, self.redteam_summary,
            self.week_events, self.raw_md,
        ]


@dataclass
class ApiUsageRow:
    """
    Per-workflow Anthropic API usage + cost log. Populated by
    `scripts/api_usage_scrape.py` parsing the result JSON that
    claude-code-action writes at the end of each brain run:

        {"type":"result","subtype":"success","is_error":false,
         "duration_ms":1271673,"num_turns":62,
         "total_cost_usd":5.671771,"permission_denials_count":0}

    UPSERT key: `run_id` (one row per GH Actions run). Re-scrapes are
    idempotent. The Settings panel reads this for MTD spend +
    per-workflow + recent-runs tables.

    NOTE: only Anthropic costs are tracked here. Finnhub/TV/Yahoo are
    free tier. FMP is the user's separate paid subscription (not
    metered per-call by us).
    """
    TAB_NAME = "api_usage"
    HEADERS = [
        "date",            # SGT iso "YYYY-MM-DDTHHMMSS" (run completion time)
        "run_id",          # GH Actions run id (UPSERT key)
        "workflow",        # "daily-brief" | "wsr-full" | "wsr-lite" | "market-scan" | etc.
        "model",           # "claude-opus-4-7" | "claude-sonnet-4-5"
        "status",          # "success" | "failure" | "cancelled"
        "num_turns",
        "duration_ms",
        "total_cost_usd",
        "updated_at",      # SGT iso when this row was scraped
    ]

    date: str
    run_id: str
    workflow: str
    model: str
    status: str
    num_turns: int
    duration_ms: int
    total_cost_usd: float
    updated_at: str

    def to_row(self, audit: bool = True) -> List[str]:
        return [
            self.date, self.run_id, self.workflow, self.model, self.status,
            str(self.num_turns), str(self.duration_ms),
            _num(self.total_cost_usd, 4), self.updated_at,
        ]


@dataclass
class TriggerAlertRow:
    """
    Per-decision trigger-state ledger — used by `scripts/trigger_alerts.py`
    to detect *transitions* into ACT_NOW so we don't fire the same
    Telegram twice within a single trigger window.

    One row per `decision_key` (`<date>|<account>|<ticker>|<strategy>|<strike>`).
    UPSERT semantics: every trigger-alerts cron run rewrites the row's
    `last_state` and `updated_at`; `last_alert_at` only updates when we
    actually send a Telegram (so we can compare to detect re-fires).

    Re-firing rule: an ACT_NOW transition is counted as new only if the
    PREVIOUS row's `last_state` was NOT already act_now. Returning to
    act_now after a brief dip back to "ready" or "close" within the
    same calendar day still counts as the same fire (we suppress).
    """
    TAB_NAME = "trigger_alerts"
    HEADERS = [
        "decision_key",        # UPSERT key
        "ticker",
        "account",
        "strategy",
        "last_state",          # "dormant" | "close" | "ready" | "act_now"
        "last_alert_state",    # state at last Telegram fire
        "last_alert_at",       # SGT iso (only updates when we ACTUALLY send)
        "current_price",
        "entry_price",
        "blocking_gates",      # pipe-separated, for the user's reference
        "updated_at",          # SGT iso (always updates per cron run)
    ]

    decision_key: str
    ticker: str
    account: str
    strategy: str
    last_state: str
    last_alert_state: str = ""
    last_alert_at: str = ""
    current_price: float = 0.0
    entry_price: float = 0.0
    blocking_gates: str = ""
    updated_at: str = ""

    def to_row(self, audit: bool = True) -> List[str]:
        return [
            self.decision_key, self.ticker, self.account, self.strategy,
            self.last_state, self.last_alert_state, self.last_alert_at,
            _num(self.current_price, 4), _num(self.entry_price, 4),
            self.blocking_gates, self.updated_at,
        ]


@dataclass
class TelegramOffsetRow:
    """
    Single-row tracker for Telegram getUpdates offset.

    The portfolio responder cron polls getUpdates every N min; offset is
    the highest update_id we've already processed + 1, so subsequent
    polls skip over already-handled messages. Survives across GH Actions
    runs because GH cron containers are ephemeral.

    Always exactly one data row (key="last") — UPSERT on every run.
    """
    TAB_NAME = "telegram_offset"
    HEADERS = ["key", "last_update_id", "updated_at"]

    key: str
    last_update_id: int
    updated_at: str

    def to_row(self, audit: bool = True) -> List[str]:
        return [self.key, str(self.last_update_id), self.updated_at]


@dataclass
class DailyPlanRow:
    """THE single source of truth for what the auto-trader will do today.

    Built by build_daily_plan.py (standing allocation + ranked opportunities),
    shown verbatim on the PWA "Today's Plan", and executed verbatim by
    alpaca_paper_execute.py — so the recommendation IS the execution. The
    fill_status column doubles as the audit trail (filled / skipped:<why>).
    """
    TAB_NAME = "daily_plan"
    HEADERS = [
        "date", "rank",
        "leg",            # hedge | protector | growth | income
        "ticker",
        "strategy",       # ALLOC | CSP | CC | PCS | CCS | IC | LONG_CALL | GROWTH
        "detail",         # human one-liner (strikes/credit, or "5% NLV → $5,257")
        "conviction",     # 0-100 unified score
        "target_pct",     # standing-allocation target as % of NLV (0 for opportunities)
        "notional",       # target/order dollars
        "reason",         # why it's in the plan (provenance)
        "source",         # source tab: risk_parity | scan_results | screen_candidates
        "execute",        # "TRUE" = the auto-trader will place it
        "fill_status",    # "" | filled | skipped:<reason> | failed:<reason>
        "updated_at",
    ]

    date: str
    rank: int
    leg: str
    ticker: str
    strategy: str
    detail: str = ""
    conviction: float = 0.0
    target_pct: float = 0.0
    notional: float = 0.0
    reason: str = ""
    source: str = ""
    execute: bool = False
    fill_status: str = ""
    updated_at: str = ""

    def to_row(self) -> List[str]:
        return [
            self.date, str(self.rank), self.leg, self.ticker, self.strategy,
            self.detail, _num(self.conviction, 1), _num(self.target_pct, 1),
            _num(self.notional, 2), self.reason, self.source,
            "TRUE" if self.execute else "", self.fill_status, self.updated_at,
        ]


@dataclass
class CuratedPickRow:
    """One curated pick from an external human-vetted source (Motley Fool Stock
    Advisor today). Read in-session via Chrome MCP, classified into a role, and
    fed to the engine as INPUT — never an auto-signal. Equal-weight + separately
    benchmarked vs SPY so we KNOW if the subscription earns its keep."""
    TAB_NAME = "curated_picks"
    HEADERS = ["date", "ticker", "role", "mf_type", "rec_date", "rec_price",
               "market_cap", "return_since_rec", "return_vs_sp", "moneyball_score",
               "source", "note", "updated_at"]

    date: str
    ticker: str
    role: str            # core | watchlist | overlay | reference
    mf_type: str = ""    # Cautious | Moderate | Aggressive (MF risk type)
    rec_date: str = ""
    rec_price: str = ""
    market_cap: str = ""
    return_since_rec: str = ""
    return_vs_sp: str = ""
    moneyball_score: str = ""
    source: str = "motley_fool"
    note: str = ""
    updated_at: str = ""

    def to_row(self) -> List[str]:
        return [self.date, self.ticker, self.role, self.mf_type, self.rec_date,
                self.rec_price, self.market_cap, self.return_since_rec,
                self.return_vs_sp, self.moneyball_score, self.source,
                self.note, self.updated_at]


# ---------- Factory helpers ----------

def daily_from_sidecar(sidecar: dict) -> DailyBriefRow:
    bullets = sidecar.get("bullets") or ["", "", ""]
    bullets = (bullets + ["", "", ""])[:3]
    # Optional rich sections — join lists with "|" for storage in a single sheet cell
    def _join(v):
        if isinstance(v, list):
            return " | ".join(str(x) for x in v)
        return str(v or "")
    return DailyBriefRow(
        date=str(sidecar.get("date", "")),
        bullet_1=bullets[0],
        bullet_2=bullets[1],
        bullet_3=bullets[2],
        verdict=str(sidecar.get("verdict", "")),
        sentiment=str(sidecar.get("sentiment", "")),
        headline=str(sidecar.get("headline", "")),
        overnight=_join(sidecar.get("overnight")),
        premarket=_join(sidecar.get("premarket")),
        catalysts=_join(sidecar.get("catalysts")),
        commodities=_join(sidecar.get("commodities")),
        posture=str(sidecar.get("posture", "")),
        watch=_join(sidecar.get("watch")),
        raw_md=str(sidecar.get("raw_md", "")),
    )


def decisions_from_ledger(ledger: dict, date: str) -> List[DecisionRow]:
    """
    WSR ledger may carry 'decisions' directly OR we parse from md.
    Prefer ledger.decisions if present (cleaner contract).

    Mirrors the parsing in scripts/push_decisions.py so both write paths
    produce key-consistent rows under the (date, account, ticker, strategy,
    strike) compound upsert key. Legacy ledgers that only carry the original
    9 fields still produce well-formed rows (just with empty strategy / 0
    strike / etc.).
    """
    out = []
    for d in (ledger.get("decisions") or []):
        out.append(DecisionRow(
            date=date,
            account=str(d.get("account", "caspar")),
            ticker=str(d.get("ticker", "")),
            bucket=str(d.get("bucket", "")),
            thesis_1liner=str(d.get("thesis_1liner", d.get("thesis", "")))[:500],
            conv=round(float(d.get("conv", 3) or 3)),
            entry=float(d.get("entry", 0.0)),
            target=float(d.get("target", 0.0)),
            status=str(d.get("status", "pending")),
            # Optional options-spec fields — default "" / 0 for share entries.
            strategy=(str(d.get("strategy", "") or "")).strip().upper(),
            right=(str(d.get("right", "") or "")).strip().upper(),
            strike=float(d.get("strike", 0) or 0),
            expiry=(str(d.get("expiry", "") or "")).strip(),
            premium_per_share=float(d.get("premium_per_share", 0) or 0),
            delta=float(d.get("delta", 0) or 0),
            annual_yield_pct=float(d.get("annual_yield_pct", 0) or 0),
            breakeven=float(d.get("breakeven", 0) or 0),
            cash_required=float(d.get("cash_required", 0) or 0),
            iv_rank=float(d.get("iv_rank", 0) or 0),
            thesis_confidence=float(d.get("thesis_confidence", 0) or 0),
            thesis=(str(d.get("thesis", "") or "")).strip(),
            source=(str(d.get("source", "") or "")).strip(),
            qty=int(d.get("qty", 0) or 0),
            accumulation_plan=(str(d.get("accumulation_plan", "") or "")).strip(),
        ))
    return out
