/**
 * TL;DR Today — single-row "what matters in the next 30 seconds" strip.
 *
 * Sits at the very top of Home. Pulls the most-actionable items from
 * across the app and surfaces ONE row each, max 3 items total. Tap any
 * item → jumps to the relevant tab (caller wires the click handler).
 *
 * Priority order (drops items off the bottom when too many):
 *   1. ACT_NOW triggers           — red, pulsing
 *   2. CRITICAL options defense   — red
 *   3. Earnings TODAY (held)      — orange
 *   4. CLOSE-state triggers       — amber
 *   5. Pending decisions          — slate (informational)
 *
 * Renders null when nothing is actionable today (calm-day → no card).
 */
import type {
  DecisionRow,
  EconomicEventRow,
  ExposurePostureRow,
  LivePriceRow,
  OptionsDefenseRow,
  PositionRow,
  TvConsensus,
  EarningsRow,
} from "../data";
import { evaluateTrigger, numeric } from "../data";
import { Card } from "./Card";
import { Zap, ShieldAlert, Calendar, Hourglass, Clock, Radio } from "lucide-react";

// Macro-blackout window thresholds. Mirrors src/macro_blackouts.py
// and ZeroDTE's macro_news.py — tune both together.
const BLACKOUT_BEFORE_MIN = 15;
const BLACKOUT_AFTER_MIN  = 5;
const APPROACHING_MIN     = 30;  // surface as a "macro soon" tile beyond blackout

export function TldrTodayCard({
  decisions,
  optionsDefense,
  earnings,
  economicEvents,
  livePrices,
  exposurePosture,
  tvSignals,
  casparPositions,
  sarahPositions,
  onJumpDecisions,
  onJumpOptions,
}: {
  decisions: DecisionRow[];
  optionsDefense: OptionsDefenseRow[];
  earnings: EarningsRow[];
  economicEvents: EconomicEventRow[];
  livePrices: Map<string, LivePriceRow>;
  exposurePosture: ExposurePostureRow | null;
  tvSignals: Map<string, TvConsensus> | undefined;
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  onJumpDecisions: () => void;
  onJumpOptions: () => void;
}) {
  // ---- 1. ACT_NOW triggers ----
  const actNow: { ticker: string; account: string; reason: string }[] = [];
  const close: { ticker: string; account: string; reason: string }[] = [];
  for (const d of decisions) {
    if ((d.status || "").toLowerCase() !== "watching") continue;
    const t = (d.ticker || "").toUpperCase();
    const live = livePrices.get(t);
    const cur = live ? numeric(live.last) : undefined;
    const ev = evaluateTrigger(d, cur, exposurePosture, tvSignals?.get(t));
    if (ev.state === "act_now") {
      actNow.push({ ticker: d.ticker, account: d.account, reason: ev.reason });
    } else if (ev.state === "close") {
      close.push({ ticker: d.ticker, account: d.account, reason: ev.reason });
    }
  }

  // ---- 2. Critical defense ----
  const criticalDefense = optionsDefense.filter(
    (d) => d.severity === "CRITICAL" || d.severity === "HIGH",
  );

  // ---- 3. Earnings today on held positions ----
  const todayStr = new Date().toISOString().slice(0, 10);
  const heldTickers = new Set([
    ...casparPositions.map((p) => (p.ticker || "").toUpperCase()),
    ...sarahPositions.map((p) => (p.ticker || "").toUpperCase()),
  ]);
  const earningsToday = earnings.filter(
    (e) => e.date === todayStr && heldTickers.has((e.ticker || "").toUpperCase()),
  );

  // ---- 4. Macro blackout / approaching ----
  // Mirror of src/macro_blackouts.py + ZeroDTE's macro_news.py.
  // Find the soonest high-impact US event within the next APPROACHING window.
  // Within ±BLACKOUT minutes → "BLACKOUT" tile (red, top priority after ACT_NOW).
  // Within APPROACHING minutes → "MACRO SOON" tile (amber, lower priority).
  const macroSoon = (() => {
    const nowMs = Date.now();
    let best: { event: string; minutesUntil: number; severity: "blackout" | "approaching" } | null = null;
    for (const e of economicEvents) {
      const impact = (e.impact || "").toLowerCase();
      if (impact !== "high") continue;
      // economic_calendar `time` is "YYYY-MM-DD HH:MM:SS" UTC. The PWA's
      // EconomicEventRow exposes `date` and `time` separately; combine.
      const ts = `${e.date} ${e.time || "00:00:00"}`.replace(" ", "T") + "Z";
      const t = Date.parse(ts);
      if (isNaN(t)) continue;
      const deltaMin = (t - nowMs) / 60000;
      if (deltaMin < -BLACKOUT_AFTER_MIN) continue;
      if (deltaMin > APPROACHING_MIN) continue;
      const severity: "blackout" | "approaching" =
        deltaMin <= BLACKOUT_BEFORE_MIN && deltaMin >= -BLACKOUT_AFTER_MIN ? "blackout" : "approaching";
      if (!best || Math.abs(deltaMin) < Math.abs(best.minutesUntil)) {
        best = { event: e.event, minutesUntil: Math.round(deltaMin), severity };
      }
    }
    return best;
  })();

  // ---- 5. Pending count ----
  const pending = decisions.filter((d) => (d.status || "").toLowerCase() === "pending").length;

  // ---- Compose items in priority order, max 3 rows ----
  type Row = { kind: "act" | "macro" | "def" | "ern" | "close" | "pen"; node: React.ReactNode };
  const rows: Row[] = [];

  // Macro BLACKOUT — sits ABOVE act_now because pages within blackout
  // are deferred anyway by trigger_alerts.py. Surface the reason
  // first so the user understands why nothing's firing.
  if (macroSoon?.severity === "blackout") {
    const t = macroSoon.minutesUntil;
    const tStr = t >= 0 ? `${t} min` : `${Math.abs(t)}min ago`;
    rows.push({
      kind: "macro",
      node: (
        <Item
          key="macro-bl"
          Icon={Radio}
          color="#fca5a5"
          pulse
          label="MACRO BLACKOUT"
          body={macroSoon.event}
          sub={`${tStr} — Telegram pushes deferred until window clears`}
          onClick={onJumpDecisions}
        />
      ),
    });
  }

  // Track urgent items that exist but don't fit the 3-row cap — rendered as
  // an overflow footer so nothing critical is EVER silently evicted.
  let urgentEvicted = 0;

  // Critical DEFENSE — outranks new entries: protecting held money beats
  // entering (post-mortem doctrine). It used to rank BELOW act-now, so a
  // blackout + two act-nows silently evicted a breached short strike.
  if (criticalDefense.length > 0) {
    if (rows.length < 3) {
      const lead = criticalDefense[0];
      rows.push({
        kind: "def",
        node: (
          <Item
            key="def"
            Icon={ShieldAlert}
            color="#fca5a5"
            pulse
            label={`${lead.severity} DEFENSE`}
            body={`${lead.ticker} ${lead.right}${lead.strike}`}
            sub={
              criticalDefense.length > 1
                ? `${lead.title} · +${criticalDefense.length - 1} more`
                : lead.title
            }
            onClick={onJumpOptions}
          />
        ),
      });
    } else {
      urgentEvicted += 1;
    }
  }

  // ACT NOW (one row per fire, up to 2)
  let actShown = 0;
  for (const a of actNow.slice(0, 2)) {
    if (rows.length >= 3) break;
    actShown += 1;
    rows.push({
      kind: "act",
      node: (
        <Item
          key={`act-${a.ticker}`}
          Icon={Zap}
          color="#fca5a5"
          pulse
          label="ACT NOW"
          body={`${a.ticker.toUpperCase()} · ${a.account.toUpperCase()}`}
          sub={a.reason}
          onClick={onJumpDecisions}
        />
      ),
    });
  }
  urgentEvicted += Math.max(0, actNow.length - actShown);

  // Macro APPROACHING (15-30 min away — heads up, not a hard gate)
  if (macroSoon?.severity === "approaching" && rows.length < 3) {
    rows.push({
      kind: "macro",
      node: (
        <Item
          key="macro-soon"
          Icon={Radio}
          color="#fb923c"
          label="MACRO SOON"
          body={macroSoon.event}
          sub={`in ${macroSoon.minutesUntil} min — blackout starts at ${BLACKOUT_BEFORE_MIN}min mark`}
          onClick={onJumpDecisions}
        />
      ),
    });
  }

  // Earnings today
  if (earningsToday.length > 0 && rows.length < 3) {
    rows.push({
      kind: "ern",
      node: (
        <Item
          key="ern"
          Icon={Calendar}
          color="#fb923c"
          label="EARNINGS TODAY"
          body={earningsToday.map((e) => e.ticker).slice(0, 3).join(" · ")}
          sub={earningsToday.length > 3 ? `+${earningsToday.length - 3} more held` : undefined}
          onClick={onJumpOptions}
        />
      ),
    });
  }

  // Close-state triggers (only if room left)
  if (close.length > 0) {
    if (rows.length < 3) {
      const lead = close[0];
      rows.push({
        kind: "close",
        node: (
          <Item
            key="close"
            Icon={Hourglass}
            color="#fcd34d"
            label="CLOSE"
            body={`${lead.ticker.toUpperCase()} · ${lead.account.toUpperCase()}`}
            sub={close.length > 1 ? `${lead.reason} · +${close.length - 1} more` : lead.reason}
            onClick={onJumpDecisions}
          />
        ),
      });
    } else {
      urgentEvicted += 1;
    }
  }

  // Pending count (informational tail)
  if (pending > 0 && rows.length < 3) {
    rows.push({
      kind: "pen",
      node: (
        <Item
          key="pen"
          Icon={Clock}
          color="#94a3b8"
          label={`${pending} PENDING`}
          body="Decision queue"
          sub="awaiting acceptance"
          onClick={onJumpDecisions}
        />
      ),
    });
  }

  if (!rows.length) return null;

  return (
    <Card>
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider text-slate-500">
            TL;DR Today
          </span>
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-600">
          {new Date().toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}
        </span>
      </div>
      <div className="space-y-1.5">
        {rows.map((r) => r.node)}
      </div>
      {urgentEvicted > 0 && (
        <button
          onClick={onJumpDecisions}
          className="mt-1.5 w-full text-left text-[length:var(--t-2xs)] font-semibold text-amber-400/90 active:opacity-70"
        >
          ⚠ +{urgentEvicted} more urgent item{urgentEvicted !== 1 ? "s" : ""} didn’t fit — tap to review
        </button>
      )}
    </Card>
  );
}

function Item({
  Icon,
  color,
  pulse,
  label,
  body,
  sub,
  onClick,
}: {
  Icon: typeof Zap;
  color: string;
  pulse?: boolean;
  label: string;
  body: string;
  sub?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left rounded-xl px-3 py-2 active:bg-white/3 transition-colors"
      style={{
        background: `${color}15`,
        border: `1px solid ${color}30`,
      }}
    >
      <div className="flex items-center gap-2.5">
        <Icon
          size={14}
          className={pulse ? "animate-pulse" : ""}
          style={{ color, flexShrink: 0 }}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-[length:var(--t-2xs)] font-bold uppercase tracking-wider"
              style={{ color }}
            >
              {label}
            </span>
            <span className="text-[length:var(--t-sm)] font-semibold text-slate-100">{body}</span>
          </div>
          {sub && (
            <div className="text-[length:var(--t-2xs)] text-slate-500 mt-0.5 truncate">
              {sub}
            </div>
          )}
        </div>
      </div>
    </button>
  );
}
