/**
 * Emoji helpers for contextual visual cues.
 * Keep these simple and semantic — no decoration for decoration's sake.
 */

/** VIX regime — helps "read the room" at a glance. */
export function vixEmoji(vix: number): { emoji: string; label: string; tone: string } {
  if (isNaN(vix) || vix <= 0) return { emoji: "❓", label: "Unknown", tone: "text-slate-500" };
  if (vix < 14) return { emoji: "😌", label: "Calm", tone: "text-emerald-400" };
  if (vix < 20) return { emoji: "😐", label: "Normal", tone: "text-slate-300" };
  if (vix < 28) return { emoji: "😰", label: "Elevated", tone: "text-yellow-400" };
  if (vix < 40) return { emoji: "🚨", label: "Stress", tone: "text-orange-400" };
  return { emoji: "💀", label: "Panic", tone: "text-red-500" };
}

/** Sentiment chip helper used across Home and Archive. */
export const SENTIMENT: Record<string, {
  emoji: string;
  label: string;
  bg: string;
  text: string;
  dot: string;
}> = {
  bullish: { emoji: "🟢", label: "Bullish", bg: "bg-emerald-500/15", text: "text-emerald-400", dot: "bg-emerald-400" },
  neutral: { emoji: "🟡", label: "Neutral", bg: "bg-yellow-500/15", text: "text-yellow-400", dot: "bg-yellow-400" },
  bearish: { emoji: "🔴", label: "Bearish", bg: "bg-red-500/15", text: "text-red-400", dot: "bg-red-400" },
};

/**
 * Sector classification for known tickers in the household portfolio.
 * Extend this as new tickers get added.
 */
const SECTOR_MAP: Record<string, { sector: string; emoji: string }> = {
  // Big tech
  AAPL:  { sector: "Technology", emoji: "🍎" },
  MSFT:  { sector: "Technology", emoji: "💻" },
  GOOGL: { sector: "Technology", emoji: "🔍" },
  GOOG:  { sector: "Technology", emoji: "🔍" },
  META:  { sector: "Technology", emoji: "📱" },
  AMZN:  { sector: "E-commerce", emoji: "📦" },
  // Semis
  NVDA:  { sector: "Semiconductors", emoji: "🎮" },
  AMD:   { sector: "Semiconductors", emoji: "🎮" },
  INTC:  { sector: "Semiconductors", emoji: "🎮" },
  TSM:   { sector: "Semiconductors", emoji: "🎮" },
  SMH:   { sector: "Semiconductors", emoji: "🎮" },
  // EV / auto
  TSLA:  { sector: "EV / Auto", emoji: "🚗" },
  // Leveraged ETFs
  TQQQ:  { sector: "Leveraged Tech", emoji: "⚡" },
  SSO:   { sector: "Leveraged Index", emoji: "⚡" },
  SQQQ:  { sector: "Leveraged Tech", emoji: "⚡" },
  UPRO:  { sector: "Leveraged Index", emoji: "⚡" },
  // Defense / drones / AI
  RCAT:  { sector: "Defense", emoji: "🛸" },
  BBAI:  { sector: "AI / Defense", emoji: "🤖" },
  PLTR:  { sector: "AI / Defense", emoji: "🤖" },
  LMT:   { sector: "Defense", emoji: "🛡️" },
  // Crypto-adjacent
  BTBT:  { sector: "Crypto", emoji: "🪙" },
  COIN:  { sector: "Crypto", emoji: "🪙" },
  MSTR:  { sector: "Crypto", emoji: "🪙" },
  IBIT:  { sector: "Crypto", emoji: "🪙" },
  // Real estate / rates
  OPEN:  { sector: "Real Estate", emoji: "🏠" },
  // Dividend / defensive
  SCHD:  { sector: "Dividend", emoji: "💰" },
  VIG:   { sector: "Dividend", emoji: "💰" },
  VYM:   { sector: "Dividend", emoji: "💰" },
  // Precious metals
  SLV:   { sector: "Silver", emoji: "🥈" },
  GLD:   { sector: "Gold", emoji: "🥇" },
  IAU:   { sector: "Gold", emoji: "🥇" },
  // Airlines / travel
  C6L:   { sector: "Airlines", emoji: "✈️" },
  // Broad-market ETFs
  G3B:   { sector: "SG Broad Market", emoji: "🇸🇬" },
  ES3:   { sector: "SG Broad Market", emoji: "🇸🇬" },
  SPY:   { sector: "US Broad Market", emoji: "📈" },
  VOO:   { sector: "US Broad Market", emoji: "📈" },
  QQQ:   { sector: "US Tech Index", emoji: "📈" },
  VTI:   { sector: "US Total Market", emoji: "📈" },
  // Healthcare / pharma
  MDT:   { sector: "Healthcare", emoji: "💊" },
  JNJ:   { sector: "Healthcare", emoji: "💊" },
  PFE:   { sector: "Healthcare", emoji: "💊" },
  UNH:   { sector: "Healthcare", emoji: "💊" },
  // Consumer staples
  MDLZ:  { sector: "Consumer Staples", emoji: "🍫" },
  KO:    { sector: "Consumer Staples", emoji: "🥤" },
  PEP:   { sector: "Consumer Staples", emoji: "🥤" },
  // Industrials
  HON:   { sector: "Industrials", emoji: "🏭" },
  // Financials
  JPM:   { sector: "Financials", emoji: "🏦" },
  BAC:   { sector: "Financials", emoji: "🏦" },
  GS:    { sector: "Financials", emoji: "🏦" },
  // Energy
  XOM:   { sector: "Energy", emoji: "🛢️" },
  CVX:   { sector: "Energy", emoji: "🛢️" },
  USO:   { sector: "Energy", emoji: "🛢️" },
};

export function sectorFor(ticker: string): { sector: string; emoji: string } {
  const t = ticker.toUpperCase();
  return SECTOR_MAP[t] ?? { sector: "Other", emoji: "📊" };
}

/** Macro indicator emojis for the ticker strip. */
export const MACRO_EMOJI: Record<string, string> = {
  VIX: "🌡️",
  DXY: "💵",
  "10Y": "📈",
  SPX: "📊",
  "USD/SGD": "🇸🇬",
};
