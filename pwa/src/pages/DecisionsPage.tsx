/**
 * DecisionsPage — the page shell for the Decisions tab.
 *
 * The card + tab-bar + watchlist sub-components were extracted into
 * ``./decisions/*`` for maintainability; this file owns the page-level state
 * (account/sub-tab selection, the selected-decision modal), the per-ticker
 * data joins (price / TV consensus / earnings), the filtering + sort, and the
 * layout that composes the imported cards and the extracted sub-components.
 * Behavior and visual output are unchanged from the original monolith.
 */
import { useState } from "react";
import type {
  DecisionRow,
  ExposurePostureRow,
  LivePriceRow,
  PositionRow,
  ScreenCandidateRow,
  DailyPlanRow,
  SnapshotRow,
  TechnicalScoreRow,
  OptionsDefenseRow,
  WheelNextLegRow,
  ExitPlanRow,
  TvConsensus,
  EarningsRow,
  AnalystConsensusRow,
  NewsSummary,
  InsiderSummary,
  CuratedPickRow,
} from "../data";
import { Card } from "../cards/Card";
import { BuyRecommendationsCard } from "../cards/BuyRecommendationsCard";
import { FreshIdeasCard } from "../cards/FreshIdeasCard";
import { ActionQueueCard } from "../cards/ActionQueueCard";
import { ExposureBudgetCard } from "../cards/ExposureBudgetCard";
import { TodaysPlanCard } from "../cards/TodaysPlanCard";
import { StockDetail } from "../components/StockDetail";
import { resolveStatus, DECISION_STATUS } from "../components/ui";
import { Target } from "lucide-react";
import { OPTIONS_STRATEGIES, statusSortKey, lookupCurrentPrice } from "./decisions/format";
import type { AccountTab, SubTab } from "./decisions/format";
import { DecisionCard } from "./decisions/DecisionCard";
import { AccountTabBar, SubTabBar, SectionHeader } from "./decisions/DecisionTabs";
import { MfWatchlistStrip } from "./decisions/MfWatchlistStrip";

export function DecisionsPage({
  decisions,
  technicalScores,
  technicalScoresHistory,
  optionsDefense,
  wheelNextLeg,
  exitPlans,
  casparPositions,
  sarahPositions,
  exposurePosture,
  casparSnapshot,
  sarahSnapshot,
  tvSignals,
  earnings,
  analystByTicker,
  newsByTicker,
  insiderByTicker,
  screenCandidates,
  livePrices,
  dailyPlan = [],
  mfWatchlist = [],
}: {
  decisions: DecisionRow[];
  technicalScores?: TechnicalScoreRow[];
  technicalScoresHistory?: TechnicalScoreRow[];
  optionsDefense?: OptionsDefenseRow[];
  wheelNextLeg?: WheelNextLegRow[];
  exitPlans?: ExitPlanRow[];
  casparPositions?: PositionRow[];
  sarahPositions?: PositionRow[];
  exposurePosture?: ExposurePostureRow | null;
  casparSnapshot?: SnapshotRow | null;
  sarahSnapshot?: SnapshotRow | null;
  tvSignals?: Map<string, TvConsensus>;
  earnings?: EarningsRow[];
  analystByTicker?: Map<string, AnalystConsensusRow>;
  newsByTicker?: Map<string, NewsSummary>;
  insiderByTicker?: Map<string, InsiderSummary>;
  screenCandidates?: ScreenCandidateRow[];
  livePrices?: Map<string, LivePriceRow>;
  dailyPlan?: DailyPlanRow[];
  mfWatchlist?: CuratedPickRow[];
}) {
  const [selected, setSelected] = useState<DecisionRow | null>(null);
  const [accountTab, setAccountTab] = useState<AccountTab>("caspar");
  const [subTab, setSubTab] = useState<SubTab>("all");

  const techByTicker = new Map<string, TechnicalScoreRow>();
  for (const t of technicalScores ?? []) techByTicker.set(t.ticker, t);

  const earningsByTicker = new Map<string, EarningsRow>();
  if (earnings && earnings.length) {
    const today = new Date().toISOString().slice(0, 10);
    for (const e of earnings) {
      if (!e.ticker || !e.date || e.date < today) continue;
      const t = e.ticker.toUpperCase();
      const prev = earningsByTicker.get(t);
      if (!prev || e.date < prev.date) earningsByTicker.set(t, e);
    }
  }

  const priceFor = (ticker: string) =>
    lookupCurrentPrice(
      ticker,
      casparPositions ?? [],
      sarahPositions ?? [],
      technicalScores ?? [],
      livePrices ?? new Map(),
    );

  const tvFor = (ticker: string): TvConsensus | undefined => {
    if (!tvSignals || !ticker) return undefined;
    return tvSignals.get(ticker.toUpperCase());
  };

  const showBuyRecs = (technicalScores?.length ?? 0) > 0;

  // Split by account
  const isAccount = (d: DecisionRow, acc: AccountTab) => {
    const a = (d.account ?? "").toLowerCase();
    if (acc === "caspar") return a === "caspar" || a === "watchlist" || a === "";
    return a === "sarah";
  };

  const casparDecisions = decisions.filter((d) => isAccount(d, "caspar"));
  const sarahDecisions = decisions.filter((d) => isAccount(d, "sarah"));
  const activeDecisions = accountTab === "caspar" ? casparDecisions : sarahDecisions;

  // Split by strategy type within current account
  const optionsInAccount = activeDecisions
    .filter((d) => OPTIONS_STRATEGIES.includes(d.strategy ?? ""))
    .sort((a, b) => statusSortKey(a.status) - statusSortKey(b.status));

  const stocksInAccount = activeDecisions
    .filter((d) => !OPTIONS_STRATEGIES.includes(d.strategy ?? ""))
    .sort((a, b) => statusSortKey(a.status) - statusSortKey(b.status));

  // What to render based on sub-tab
  const visibleDecisions =
    subTab === "options" ? optionsInAccount :
    subTab === "stocks" ? stocksInAccount :
    [...optionsInAccount, ...stocksInAccount];

  // Status counts for summary pills (filtered view)
  const counts: Record<string, number> = {};
  for (const d of visibleDecisions) {
    const s = d.status?.toLowerCase() || "unknown";
    counts[s] = (counts[s] || 0) + 1;
  }

  let fadeIdx = 1;
  const nextFade = () => `fade-up fade-up-${Math.min(fadeIdx++, 4)}`;

  const renderCard = (d: DecisionRow, i: number, prefix: string) => (
    <div key={`${prefix}-${d.ticker}-${d.date}-${i}`}>
      <DecisionCard
        decision={d}
        onTap={() => setSelected(d)}
        currentPrice={priceFor(d.ticker)}
        tvConsensus={tvFor(d.ticker)}
        earnings={earningsByTicker.get((d.ticker || "").toUpperCase())}
        analyst={analystByTicker?.get((d.ticker || "").toUpperCase())}
        news={newsByTicker?.get((d.ticker || "").toUpperCase())}
        insider={insiderByTicker?.get((d.ticker || "").toUpperCase())}
        exposurePosture={exposurePosture}
      />
    </div>
  );

  return (
    <>
      <div className="px-4 pb-4 flex flex-col gap-4">
        {/* The unified auto-trader plan — what the bot recommends AND executes
            today (recommendation == execution). Shown first so this is the
            "what's the system doing" answer. The cards below are the legacy
            manual decision queue (kept for review). */}
        {dailyPlan.length > 0 && (
          <div className={nextFade()}>
            <TodaysPlanCard plan={dailyPlan} newsByTicker={newsByTicker} />
          </div>
        )}

        <div className={nextFade()}>
          <ExposureBudgetCard
            posture={exposurePosture ?? null}
            caspar={casparSnapshot ?? null}
            sarah={sarahSnapshot ?? null}
          />
        </div>

        {/* Account tabs: Caspar / Sarah */}
        <div className={nextFade()}>
          <AccountTabBar
            active={accountTab}
            onChange={(t) => { setAccountTab(t); setSubTab("all"); }}
            counts={{ caspar: casparDecisions.length, sarah: sarahDecisions.length }}
          />
        </div>

        {/* Sub-tabs: All / Options / Stocks */}
        <div className="flex items-center justify-between">
          <SubTabBar
            active={subTab}
            onChange={setSubTab}
            counts={{
              all: activeDecisions.length,
              options: optionsInAccount.length,
              stocks: stocksInAccount.length,
            }}
          />
        </div>

        <div className={nextFade()}>
          <ActionQueueCard
            optionsDefense={optionsDefense ?? []}
            wheelNextLeg={wheelNextLeg ?? []}
            exitPlans={exitPlans ?? []}
            technicalScores={technicalScores}
            technicalScoresHistory={technicalScoresHistory}
          />
        </div>

        {showBuyRecs && (
          <div className={nextFade()}>
            <BuyRecommendationsCard
              technicalScores={technicalScores ?? []}
              technicalScoresHistory={technicalScoresHistory}
            />
          </div>
        )}

        <div className={nextFade()}>
          <FreshIdeasCard
            candidates={screenCandidates ?? []}
            technicalScores={technicalScores ?? []}
            technicalScoresHistory={technicalScoresHistory}
          />
        </div>

        {/* Motley Fool watchlist — read-only research strip. Renders null when
            empty via the strip's own guard. Suggestion-only, never traded. */}
        {mfWatchlist.length > 0 && (
          <div className={nextFade()}>
            <MfWatchlistStrip watchlist={mfWatchlist} />
          </div>
        )}

        {visibleDecisions.length > 0 ? (
          <>
            {/* Summary pills */}
            <div className="flex gap-2 overflow-x-auto no-scrollbar py-1 -mx-1 px-1">
              {Object.entries(counts).map(([status, count]) => {
                const cfg = DECISION_STATUS[status] ?? resolveStatus(status);
                return (
                  <div
                    key={status}
                    className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full ${cfg.bg} border ${cfg.border}`}
                  >
                    <span className={`text-[length:var(--t-xs)] font-semibold ${cfg.text}`}>{count}</span>
                    <span className={`text-[length:var(--t-2xs)] ${cfg.text} opacity-70`}>{cfg.label}</span>
                  </div>
                );
              })}
            </div>

            {subTab === "all" ? (
              <>
                {optionsInAccount.length > 0 && (
                  <div className="flex flex-col gap-2.5">
                    <SectionHeader label="Options" count={optionsInAccount.length} />
                    {optionsInAccount.map((d, i) => renderCard(d, i, "opt"))}
                  </div>
                )}
                {stocksInAccount.length > 0 && (
                  <div className="flex flex-col gap-2.5">
                    <SectionHeader label="Stocks" count={stocksInAccount.length} />
                    {stocksInAccount.map((d, i) => renderCard(d, i, "stk"))}
                  </div>
                )}
              </>
            ) : (
              <div className="flex flex-col gap-2.5">
                {visibleDecisions.map((d, i) => renderCard(d, i, subTab))}
              </div>
            )}
          </>
        ) : (
          <Card>
            <div className="flex flex-col items-center gap-2 py-4">
              <Target size={18} className="text-slate-600" />
              <p className="text-[length:var(--t-xs)] text-slate-500">
                No {subTab === "all" ? "" : subTab + " "}decisions for {accountTab === "caspar" ? "Caspar" : "Sarah"}
              </p>
            </div>
          </Card>
        )}
      </div>

      {selected && (
        <StockDetail
          decision={selected}
          ticker={selected.ticker}
          techScore={techByTicker.get(selected.ticker)}
          techHistory={technicalScoresHistory}
          currency={selected.account?.toLowerCase() === "sarah" ? "SGD" : "USD"}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
