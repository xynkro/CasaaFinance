import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Search, X, ChevronRight, TrendingUp, TrendingDown, Minus } from "lucide-react";
import type { TechnicalScoreRow } from "../data";
import { sectorFor } from "../lib/emojis";

interface Props {
  open: boolean;
  onClose: () => void;
  technicalScores: TechnicalScoreRow[];
  onSelect: (ticker: string, techScore?: TechnicalScoreRow) => void;
}

function ScorePill({ signal }: { signal: string }) {
  const color =
    signal === "BUY" ? "#34d399" :
    signal.startsWith("SELL") ? "#f87171" :
    "rgb(100 116 139)";
  const Icon = signal === "BUY" ? TrendingUp : signal.startsWith("SELL") ? TrendingDown : Minus;
  return (
    <span
      className="inline-flex items-center gap-1 text-[length:var(--t-2xs)] font-bold px-2 py-0.5 rounded-lg"
      style={{ background: `${color}18`, color }}
    >
      <Icon size={9} />
      {signal}
    </span>
  );
}

export function TickerLookupSheet({ open, onClose, technicalScores, onSelect }: Props) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-focus the input each time the sheet opens. Reset of the query is
  // handled in the close handlers below — keeping it out of the effect
  // avoids a setState-in-effect cascade (react-hooks/set-state-in-effect).
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => inputRef.current?.focus(), 80);
    return () => clearTimeout(t);
  }, [open]);

  const handleClose = () => {
    setQuery("");
    onClose();
  };

  const upper = query.trim().toUpperCase();

  // Suggestions: tickers starting with query
  const suggestions = upper.length >= 1
    ? technicalScores
        .filter((t) => t.ticker.startsWith(upper))
        .sort((a, b) => Number(b.score_buy) - Number(a.score_buy))
        .slice(0, 6)
    : [];

  const handleAnalyze = () => {
    if (!upper) return;
    const match = technicalScores.find((t) => t.ticker === upper);
    onSelect(upper, match);
    handleClose();
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleAnalyze();
    if (e.key === "Escape") handleClose();
  };

  if (!open) return null;

  return createPortal(
    <>
      {/* Scrim */}
      <div
        className="fixed inset-0 z-40"
        style={{ background: "rgba(0,0,0,0.55)", backdropFilter: "blur(6px)", WebkitBackdropFilter: "blur(6px)" }}
        onClick={handleClose}
      />

      {/* Bottom sheet */}
      <div
        className="fixed bottom-0 left-0 right-0 z-50 rounded-t-[28px] flex flex-col"
        style={{
          background: "rgba(11,13,20,0.98)",
          border: "1px solid rgba(255,255,255,0.09)",
          borderBottom: "none",
          boxShadow: "0 -24px 80px rgba(0,0,0,0.6)",
          paddingBottom: "max(env(safe-area-inset-bottom), 16px)",
        }}
      >
        {/* Drag handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-9 h-1 rounded-full" style={{ background: "rgba(255,255,255,0.15)" }} />
        </div>

        <div className="px-4 pt-3 pb-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[length:var(--t-lg)] font-bold text-white">Analyse a Ticker</h2>
            <button
              onClick={handleClose}
              className="w-7 h-7 rounded-full flex items-center justify-center"
              style={{ background: "rgba(255,255,255,0.08)" }}
            >
              <X size={13} style={{ color: "rgb(148 163 184)" }} />
            </button>
          </div>

          {/* Search input */}
          <div
            className="flex items-center gap-3 rounded-2xl px-4 py-3 mb-3"
            style={{
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.1)",
              boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
            }}
          >
            <Search size={16} style={{ color: "rgb(100 116 139)", flexShrink: 0 }} />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value.toUpperCase())}
              onKeyDown={handleKey}
              placeholder="TSLA, NVDA, AAPL…"
              className="flex-1 bg-transparent text-[length:var(--t-lg)] font-bold text-white outline-none placeholder:text-slate-700 tracking-wide"
              autoCapitalize="characters"
              autoCorrect="off"
              spellCheck={false}
              inputMode="text"
            />
            {query && (
              <button onClick={() => setQuery("")} className="active:opacity-60">
                <X size={14} style={{ color: "rgb(100 116 139)" }} />
              </button>
            )}
          </div>

          {/* Suggestions from existing scan data */}
          {suggestions.length > 0 && (
            <div
              className="rounded-2xl overflow-hidden mb-3"
              style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
            >
              {suggestions.map((t, i) => {
                const { emoji } = sectorFor(t.ticker);
                const signal = t.entry_exit_signal || "HOLD";
                const rsi = Number(t.rsi_14).toFixed(0);
                const macd = t.macd_cross === "bullish" ? "↑ MACD" : t.macd_cross === "bearish" ? "↓ MACD" : null;
                return (
                  <button
                    key={t.ticker}
                    onClick={() => { onSelect(t.ticker, t); handleClose(); }}
                    className="w-full flex items-center gap-3 px-4 py-3 active:bg-white/5 text-left transition-colors"
                    style={{ borderTop: i > 0 ? "1px solid rgba(255,255,255,0.05)" : "none" }}
                  >
                    <span className="text-[length:var(--t-lg)] leading-none">{emoji}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[length:var(--t-sm)] font-bold text-white">{t.ticker}</span>
                        <ScorePill signal={signal} />
                      </div>
                      <div className="text-[length:var(--t-xs)] text-slate-500 mt-0.5">
                        RSI {rsi}
                        {macd && <span className={macd.startsWith("↑") ? " text-emerald-500" : " text-red-400"}> · {macd}</span>}
                        {t.trend && <span> · {t.trend}</span>}
                      </div>
                    </div>
                    <ChevronRight size={14} style={{ color: "rgb(71 85 105)", flexShrink: 0 }} />
                  </button>
                );
              })}
            </div>
          )}

          {/* Analyse button */}
          <button
            onClick={handleAnalyze}
            disabled={!upper}
            className="w-full py-4 rounded-2xl text-[length:var(--t-sm)] font-bold text-white transition-all active:scale-[0.98] disabled:opacity-30"
            style={{
              background: upper
                ? `linear-gradient(135deg, rgb(var(--accent-rgb)), rgba(var(--accent-rgb),0.7))`
                : "rgba(255,255,255,0.05)",
              border: upper ? "none" : "1px solid rgba(255,255,255,0.07)",
              boxShadow: upper ? `0 4px 24px rgba(var(--accent-rgb),0.3)` : "none",
            }}
          >
            {upper ? `Analyse ${upper}` : "Type a ticker to analyse"}
          </button>

          {!upper && (
            <p className="text-center text-[length:var(--t-xs)] text-slate-600 mt-2.5 leading-relaxed">
              Shows chart, RSI, MACD, Bollinger Bands and more.{"\n"}
              In-scan tickers also show Casaa scores.
            </p>
          )}
        </div>
      </div>
    </>,
    document.body
  );
}
