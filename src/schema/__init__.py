"""
Sheet tab schemas — dataclasses mirror the 7 tabs one-for-one.

Each class exposes:
  - TAB_NAME    : the literal Google Sheet tab name (must match)
  - HEADERS     : ordered list of column headers (row 1 in the tab)
  - to_row()    : returns a list[str] in HEADERS order for append_row()

If you change a schema here, update the sheet tab header row to match.

----------------------------------------------------------------------------
This module is now a PACKAGE. The dataclasses/constants/helpers were split
into domain submodules for maintainability (schema/_base.py shared helpers,
schema/portfolio.py, schema/options.py, schema/scan.py, schema/macro.py,
schema/decisions.py, schema/gov.py). This ``__init__`` is a FACADE that
re-exports every public name the old flat ``schema.py`` exposed, so existing
imports keep resolving unchanged:

    from src import schema as S      # S.SnapshotCaspar, S._num, S.now_sgt_iso ...
    from src.schema import DecisionRow, PNL_MODEL_PREMIUM
"""
from __future__ import annotations

# Re-export the names that the original flat module leaked into its public
# surface via its own imports, so `dir(schema)` stays byte-for-byte the same
# set of names (callers relying on e.g. `schema.List` keep working).
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List

# ---- Shared helpers / conventions -----------------------------------------
from ._base import (
    SGT,
    US_MARKET_TZ,
    now_sgt_iso,
    now_sgt_date,
    us_market_date,
    _num,
    _ts_suffix,
)

# ---- Portfolio + account snapshots (IBKR + Alpaca) ------------------------
from .portfolio import (
    SnapshotCaspar,
    SnapshotSarah,
    PositionRow,
    TradeRow,
    AlpacaSnapshotRow,
    AlpacaPositionRow,
    PaperBenchmarkRow,
    ExitPlanRow,
    snapshot_caspar_from_ledger,
    positions_caspar_from_ledger,
    snapshot_sarah_from_ledger,
    positions_sarah_from_ledger,
    snapshot_caspar_from_grab,
    snapshot_sarah_from_grab,
    positions_caspar_from_grab,
    positions_sarah_from_grab,
)

# ---- Options domain -------------------------------------------------------
from .options import (
    OptionRow,
    WheelNextLegRow,
    OptionsDefenseRow,
    OptionRecommendationRow,
    OptionsYieldCandidateRow,
    GexRegimeRow,
    HarvestScanRow,
    IvSurfaceScanRow,
    SignalOutcomeRow,
    UoaAlertRow,
    PNL_MODEL_PREMIUM,
    PNL_MODEL_LEGACY,
    options_from_grab,
)

# ---- Technical scan + screeners -------------------------------------------
from .scan import (
    TechnicalScoreRow,
    ScanResultRow,
    ScanMetaRow,
    scan_status,
    ScreenCandidateRow,
    TvSignalRow,
)

# ---- Macro + regime + calendars + news/insider + live price + risk parity --
from .macro import (
    MacroRow,
    RegimeSignalRow,
    ExposurePostureRow,
    RiskParityAuditRow,
    EarningsRow,
    EconomicEventRow,
    AnalystConsensusRow,
    NewsSentimentRow,
    InsiderTransactionRow,
    MacroAlertStateRow,
    MacroLeanRow,
    LivePriceRow,
    macro_from_ledger,
)

# ---- Decisions / briefs / WSR / daily plan / curated / api usage / triggers -
from .decisions import (
    DecisionRow,
    DailyBriefRow,
    WsrArchiveRow,
    WsrSummaryRow,
    ApiUsageRow,
    TriggerAlertRow,
    TelegramOffsetRow,
    DailyPlanRow,
    CuratedPickRow,
    daily_from_sidecar,
    decisions_from_ledger,
)

# ---- Government spending confluence ---------------------------------------
from .gov import (
    GovContractRow,
    CongressTradeRow,
    RecipientTickerMapRow,
    GovUnmappedRecipientRow,
    GovConfluenceSignalRow,
)


__all__ = [
    # shared helpers / constants
    "SGT",
    "US_MARKET_TZ",
    "now_sgt_iso",
    "now_sgt_date",
    "us_market_date",
    "_num",
    "_ts_suffix",
    "PNL_MODEL_PREMIUM",
    "PNL_MODEL_LEGACY",
    # portfolio
    "SnapshotCaspar",
    "SnapshotSarah",
    "PositionRow",
    "TradeRow",
    "AlpacaSnapshotRow",
    "AlpacaPositionRow",
    "PaperBenchmarkRow",
    "ExitPlanRow",
    "snapshot_caspar_from_ledger",
    "positions_caspar_from_ledger",
    "snapshot_sarah_from_ledger",
    "positions_sarah_from_ledger",
    "snapshot_caspar_from_grab",
    "snapshot_sarah_from_grab",
    "positions_caspar_from_grab",
    "positions_sarah_from_grab",
    # options
    "OptionRow",
    "WheelNextLegRow",
    "OptionsDefenseRow",
    "OptionRecommendationRow",
    "OptionsYieldCandidateRow",
    "GexRegimeRow",
    "HarvestScanRow",
    "IvSurfaceScanRow",
    "SignalOutcomeRow",
    "UoaAlertRow",
    "options_from_grab",
    # scan
    "TechnicalScoreRow",
    "ScanResultRow",
    "ScanMetaRow",
    "scan_status",
    "ScreenCandidateRow",
    "TvSignalRow",
    # macro
    "MacroRow",
    "RegimeSignalRow",
    "ExposurePostureRow",
    "RiskParityAuditRow",
    "EarningsRow",
    "EconomicEventRow",
    "AnalystConsensusRow",
    "NewsSentimentRow",
    "InsiderTransactionRow",
    "MacroAlertStateRow",
    "MacroLeanRow",
    "LivePriceRow",
    "macro_from_ledger",
    # decisions
    "DecisionRow",
    "DailyBriefRow",
    "WsrArchiveRow",
    "WsrSummaryRow",
    "ApiUsageRow",
    "TriggerAlertRow",
    "TelegramOffsetRow",
    "DailyPlanRow",
    "CuratedPickRow",
    "daily_from_sidecar",
    "decisions_from_ledger",
    # gov
    "GovContractRow",
    "CongressTradeRow",
    "RecipientTickerMapRow",
    "GovUnmappedRecipientRow",
    "GovConfluenceSignalRow",
]
