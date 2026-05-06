import type { MacroRow, RegimeSignalRow } from "../data";
import { numeric } from "../data";

function vixStyle(v: number) {
  if (v > 30) return { color: "#f87171", bg: "rgba(248,113,113,0.10)", border: "rgba(248,113,113,0.22)", sub: "FEAR" };
  if (v > 25) return { color: "#fb923c", bg: "rgba(251,146,60,0.10)",  border: "rgba(251,146,60,0.22)",  sub: "ELEV" };
  if (v > 18) return { color: "#fbbf24", bg: "rgba(251,191,36,0.10)",  border: "rgba(251,191,36,0.22)",  sub: "CAUTION" };
  return       { color: "#34d399", bg: "rgba(52,211,153,0.08)", border: "rgba(52,211,153,0.18)", sub: "LOW" };
}

type Accent = ReturnType<typeof vixStyle> | undefined;

/**
 * Map a 0-100 market-breadth score to (color, sub-label).
 *   ≥70 → emerald  ("Strong" / "Healthy")
 *   50-69 → amber  ("Neutral")
 *   30-49 → amber  ("Weakening" / "Weak")
 *   <30  → red     ("Critical")
 *
 * Falls back to the source row's `label` text for the sub-label so
 * Agent 1's exact wording shows through (e.g. "Strong" / "Critical").
 */
function breadthAccent(score: number, label: string | undefined): Accent {
  if (!Number.isFinite(score)) return undefined;
  const sub = (label ?? "").toUpperCase().slice(0, 9) || (
    score >= 70 ? "STRONG" :
    score >= 50 ? "HEALTHY" :
    score >= 30 ? "WEAK" : "CRITICAL"
  );
  if (score < 30) {
    return { color: "#f87171", bg: "rgba(248,113,113,0.10)", border: "rgba(248,113,113,0.22)", sub };
  }
  if (score < 70) {
    return { color: "#fbbf24", bg: "rgba(251,191,36,0.10)", border: "rgba(251,191,36,0.22)", sub };
  }
  return { color: "#34d399", bg: "rgba(52,211,153,0.08)", border: "rgba(52,211,153,0.18)", sub };
}

/** Distribution-day count → amber/red on threshold (3+ amber, 5+ red). */
function ddAccent(count: number, label: string | undefined): Accent {
  if (!Number.isFinite(count)) return undefined;
  const sub = (label ?? "").toUpperCase().slice(0, 9) || (count >= 5 ? "SEVERE" : count >= 3 ? "HIGH" : "OK");
  if (count >= 5) {
    return { color: "#f87171", bg: "rgba(248,113,113,0.10)", border: "rgba(248,113,113,0.22)", sub };
  }
  if (count >= 3) {
    return { color: "#fbbf24", bg: "rgba(251,191,36,0.10)", border: "rgba(251,191,36,0.22)", sub };
  }
  return { color: "#34d399", bg: "rgba(52,211,153,0.08)", border: "rgba(52,211,153,0.18)", sub };
}

/** FTD label → emerald only when confirmed; otherwise dim slate. */
function ftdAccent(label: string | undefined): { accent: Accent; value: string } {
  const up = (label ?? "").toUpperCase();
  if (up.includes("FTD_CONFIRMED") || up === "FTD" || up.includes("CONFIRMED")) {
    return {
      accent: { color: "#34d399", bg: "rgba(52,211,153,0.08)", border: "rgba(52,211,153,0.18)", sub: "CONFIRMED" },
      value: "FTD ✓",
    };
  }
  return { accent: undefined, value: "—" };
}

type Item = {
  label: string;
  value: string;
  accent?: Accent;
  sub?: string;
};

export function MacroStrip({
  macro,
  regimeSignals,
}: {
  macro: MacroRow | null;
  regimeSignals?: Record<string, RegimeSignalRow>;
}) {
  if (!macro) return null;

  const vix    = Number(macro.vix);
  const dxy    = Number(macro.dxy);
  const us10y  = Number(macro.us_10y);
  const spx    = Number(macro.spx);
  const usdsgd = Number(macro.usd_sgd);
  const vix_   = vixStyle(vix);

  const items: Item[] = [
    { label: "VIX",  value: vix.toFixed(1),   accent: vix_,  sub: vix_.sub  },
    { label: "SPX",  value: spx >= 1000 ? `${(spx / 1000).toFixed(2)}k` : spx.toFixed(0) },
    { label: "10Y",  value: `${us10y.toFixed(2)}%` },
    { label: "DXY",  value: dxy.toFixed(1) },
    { label: "SGD",  value: usdsgd.toFixed(3) },
  ];

  // Regime pills — only added when the underlying source row is
  // available. Sources without rows render as "—" so the lineup is
  // always 8 pills (5 macro + 3 regime), telegraphing what's pending.
  const breadth = regimeSignals?.["market_breadth"];
  const dd      = regimeSignals?.["distribution_day"];
  const ftd     = regimeSignals?.["ftd"];

  const breadthScore = numeric(breadth?.score, NaN);
  const ddScore = numeric(dd?.score, NaN);  // expect Agent 1 to put DD count in `score`
  const ftdMeta = ftdAccent(ftd?.label);

  // Always emit the three regime pills — fallback to "—" when a
  // source hasn't reported yet.
  const breadthLabel = (breadth?.label ?? "").trim();
  items.push({
    label: "BR",
    value: Number.isFinite(breadthScore) ? `${breadthScore.toFixed(0)}/100` : "—",
    accent: Number.isFinite(breadthScore) ? breadthAccent(breadthScore, breadthLabel) : undefined,
    sub: Number.isFinite(breadthScore)
      ? (breadthLabel.toUpperCase().slice(0, 9) || undefined)
      : undefined,
  });
  const ddLabel = (dd?.label ?? "").trim();
  items.push({
    label: "DD",
    value: Number.isFinite(ddScore) ? `${ddScore.toFixed(0)} D25` : "—",
    accent: Number.isFinite(ddScore) ? ddAccent(ddScore, ddLabel) : undefined,
    sub: Number.isFinite(ddScore) ? (ddLabel.toUpperCase().slice(0, 9) || undefined) : undefined,
  });
  items.push({
    label: "FTD",
    value: ftdMeta.value,
    accent: ftdMeta.accent,
    sub: ftdMeta.accent?.sub,
  });

  return (
    <div className="flex gap-2 overflow-x-auto no-scrollbar py-1.5 -mx-1 px-1">
      {items.map((item) => {
        const hl = item.accent;
        return (
          <div
            key={item.label}
            className="shrink-0 flex items-center gap-2 px-3 py-1.5 rounded-xl"
            style={{
              background: hl ? hl.bg : "rgba(255,255,255,0.04)",
              border: `1px solid ${hl ? hl.border : "rgba(255,255,255,0.065)"}`,
              boxShadow: hl
                ? `0 0 14px ${hl.bg}, inset 0 1px 0 rgba(255,255,255,0.06)`
                : "inset 0 1px 0 rgba(255,255,255,0.04)",
            }}
          >
            <span
              style={{
                fontSize: "var(--t-2xs)",
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase" as const,
                color: hl ? hl.color : "rgb(71 85 105)",
              }}
            >
              {item.label}
            </span>
            <span
              style={{
                fontSize: "var(--t-xs)",
                fontWeight: 700,
                fontVariantNumeric: "tabular-nums",
                color: hl ? hl.color : "rgb(226 232 240)",
              }}
            >
              {item.value}
            </span>
            {item.sub && hl && (
              <span
                style={{
                  fontSize: "8px",
                  fontWeight: 800,
                  letterSpacing: "0.06em",
                  padding: "1px 4px",
                  borderRadius: 5,
                  background: `${hl.color}22`,
                  color: hl.color,
                }}
              >
                {item.sub}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
