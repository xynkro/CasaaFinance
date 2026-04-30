import type { MacroRow } from "../data";

function vixStyle(v: number) {
  if (v > 30) return { color: "#f87171", bg: "rgba(248,113,113,0.10)", border: "rgba(248,113,113,0.22)", sub: "FEAR" };
  if (v > 25) return { color: "#fb923c", bg: "rgba(251,146,60,0.10)",  border: "rgba(251,146,60,0.22)",  sub: "ELEV" };
  if (v > 18) return { color: "#fbbf24", bg: "rgba(251,191,36,0.10)",  border: "rgba(251,191,36,0.22)",  sub: "CAUTION" };
  return       { color: "#34d399", bg: "rgba(52,211,153,0.08)", border: "rgba(52,211,153,0.18)", sub: "LOW" };
}

export function MacroStrip({ macro }: { macro: MacroRow | null }) {
  if (!macro) return null;

  const vix    = Number(macro.vix);
  const dxy    = Number(macro.dxy);
  const us10y  = Number(macro.us_10y);
  const spx    = Number(macro.spx);
  const usdsgd = Number(macro.usd_sgd);
  const vix_   = vixStyle(vix);

  const items = [
    { label: "VIX",  value: vix.toFixed(1),   accent: vix_,  sub: vix_.sub  },
    { label: "SPX",  value: spx >= 1000 ? `${(spx / 1000).toFixed(2)}k` : spx.toFixed(0) },
    { label: "10Y",  value: `${us10y.toFixed(2)}%` },
    { label: "DXY",  value: dxy.toFixed(1) },
    { label: "SGD",  value: usdsgd.toFixed(3) },
  ];

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
