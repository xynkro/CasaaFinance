/**
 * SGX-FX helpers — keep mixed-currency portfolios honest.
 *
 * Caspar's account is USD-based but he holds a few SGX names (C6L, G3B,
 * etc.) which IBKR reports in raw SGD. Without converting, the SGD value
 * gets summed as USD and inflates NLV. Sarah's account is SGD-based but
 * her positions table also includes USD names (Tesla / Coupang etc.).
 *
 * Mirror of the `SGX_TICKERS` set in `src/yahoo_grab.py` so the cron and
 * the PWA agree on which symbols need FX adjustment.
 */
export const SGX_TICKERS: ReadonlySet<string> = new Set([
  "C6L", "G3B", "D05", "O39", "U11", "Z74", "V03", "ES3",
]);

export function isSgx(ticker: string | undefined): boolean {
  if (!ticker) return false;
  return SGX_TICKERS.has(ticker.toUpperCase());
}

/**
 * Convert a position's raw mkt_val (in its native currency — USD for US
 * stocks, SGD for SGX) into the account's base currency.
 *
 * @param raw       position mkt_val as stored in the sheet (native ccy)
 * @param ticker    ticker symbol — used to detect SGX vs US
 * @param account   "caspar" (USD base) or "sarah" (SGD base)
 * @param usdSgd    spot USD/SGD rate (e.g. 1.302). Falls back to 1.30 if NaN.
 */
export function toAcctCcy(
  raw: number,
  ticker: string,
  account: "caspar" | "sarah",
  usdSgd: number,
): number {
  if (!Number.isFinite(raw)) return 0;
  const fx = Number.isFinite(usdSgd) && usdSgd > 0 ? usdSgd : 1.30;
  const sgx = isSgx(ticker);
  if (account === "caspar" && sgx) return raw / fx;       // SGD → USD
  if (account === "sarah"  && !sgx) return raw * fx;      // USD → SGD
  return raw;                                              // already in account ccy
}
