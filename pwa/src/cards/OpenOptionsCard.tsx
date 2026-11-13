import { useEffect, useState, type FormEvent } from "react";
import { fetchTab } from "../data/transport";
import { Card } from "./Card";

type Account = "caspar" | "sarah";
type Right = "P" | "C";
type RawRow = Record<string, unknown>;
type Leg = {
  account: Account;
  ticker: string;
  right: Right;
  strike: number;
  expiry: string;
  qty: number;
};
type Option = Leg & {
  row: RawRow;
  credit: number | undefined;
  captured: number | undefined;
};

const ET = "America/New_York";
const accounts: Account[] = ["caspar", "sarah"];
const accountNames = { caspar: "Caspar", sarah: "Sarah" };
const verdicts: Record<string, string> = {
  stop: "Stop line hit", below: "Under the strike", above: "Over the strike",
  profit: "Take profit", dte21: "21 days left", hold: "Holding",
};
const urgent = new Set(["stop", "below", "above", "profit"]);
const savedMessage = "Saved. It shows here after the next check, within about 45 minutes.";
const inputClass = "focusable w-full min-w-0 rounded-lg border border-[var(--border-bright)] bg-[var(--surface)] px-2.5 py-2 text-[length:var(--t-sm)] tabular-nums";
const buttonClass = "focusable min-h-11 rounded-lg border border-[var(--border-bright)] px-3 py-2 text-[length:var(--t-xs)] font-medium disabled:opacity-50";
const accentClass = `${buttonClass} bg-[var(--accent-dim)]`;

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function number(value: unknown): number | undefined {
  const raw = text(value).trim();
  if (!raw) return undefined;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function partsAt(time: number, timeZone = ET) {
  return Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).formatToParts(time).map(({ type, value }) => [type, value]));
}

function todayEt(time = Date.now()): string {
  const p = partsAt(time);
  return `${p.year}-${p.month}-${p.day}`;
}

function expiryDate(value: string): Date | undefined {
  if (!/^\d{8}$/.test(value)) return undefined;
  const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === iso ? date : undefined;
}

// A zone-less server timestamp is ET wall time, never the device's local time.
// Resolve its UTC instant using Intl's IANA timezone rules, including DST.
function updatedTime(value: unknown): number | undefined {
  const raw = text(value).trim();
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?(?:Z|[+-]\d{2}:\d{2})?$/.test(raw)) return undefined;
  if (/(Z|[+-]\d{2}:\d{2})$/.test(raw)) {
    const time = Date.parse(raw);
    return Number.isFinite(time) ? time : undefined;
  }
  const parsed = Date.parse(`${raw}Z`);
  if (!Number.isFinite(parsed)) return undefined;
  const wall = Math.floor(parsed / 1000) * 1000;
  let time = wall;
  for (let i = 0; i < 3; i++) {
    const p = partsAt(time);
    const represented = Date.parse(`${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}Z`);
    time += wall - represented;
  }
  const p = partsAt(time);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}` === raw.slice(0, 16) ? time + parsed - wall : undefined;
}

function isStale(updated: number, now: number): boolean {
  const p = partsAt(now);
  const day = new Date(`${p.year}-${p.month}-${p.day}T12:00:00Z`).getUTCDay();
  const minute = Number(p.hour) * 60 + Number(p.minute);
  return day >= 1 && day <= 5 && minute >= 570 && minute < 960 && now - updated > 45 * 60_000;
}

function clock(time: number, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(time);
}

function legId(leg: Leg): string {
  return `${leg.account}|${leg.ticker}|${leg.right}${leg.strike}|${leg.expiry}`;
}

function parseOption(row: RawRow): Option | undefined {
  const account = text(row.account).trim().toLowerCase();
  const ticker = text(row.ticker).trim().toUpperCase();
  const right = text(row.right).trim().toUpperCase();
  const strike = number(row.strike);
  const qty = number(row.qty);
  const expiry = text(row.expiry).trim();
  if ((account !== "caspar" && account !== "sarah") || !/^[A-Z][A-Z.]*$/.test(ticker) ||
      (right !== "P" && right !== "C") || strike === undefined || strike <= 0 ||
      qty === undefined || !Number.isSafeInteger(qty) || qty === 0 || !expiryDate(expiry)) return undefined;
  return { account, ticker, right, strike, expiry, qty, row, credit: number(row.credit), captured: number(row.captured_pct) };
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function saveTrade(leg: Leg, change: { status: "open"; price: number } | { status: "closed"; close_price: number }) {
  if (!navigator.onLine) throw new Error("You are offline. Reconnect and save again.");
  const { auth, writeTrade } = await import("../lib/firebase");
  if (!auth.currentUser) throw new Error("Sign in to save this option.");
  // The close branch deliberately has no price: merge preserves the sale credit.
  await writeTrade(legId(leg), { ...leg, date: todayEt(), ...change, source: "app" });
}

function PriceLadder({ option }: { option: Option }) {
  // Highest price at the top. Ticks sit at their true price; labels keep a minimum
  // gap so close lines never overlap, with a short leader back to the tick.
  const points = [
    { label: "take profit", value: number(option.row.profit_spot) },
    { label: "0.20 delta", value: number(option.row.delta20_spot) },
    { label: "strike", value: option.strike },
    { label: "stop", value: number(option.row.stop_spot) },
    { label: "break-even", value: number(option.row.breakeven) },
    { label: "now", value: number(option.row.spot) },
  ].filter((p): p is { label: string; value: number } => p.value !== undefined && p.value > 0)
    .sort((a, b) => b.value - a.value);
  const gap = 17, top = 10;
  const height = Math.max(top * 2 + gap * (points.length - 1), 96);
  const high = points[0].value, low = points[points.length - 1].value;
  const yFor = (v: number) => high === low ? height / 2 : top + (high - v) / (high - low) * (height - top * 2);
  const ticks = points.map((p) => ({ ...p, y: yFor(p.value), labelY: yFor(p.value) }));
  for (let i = 1; i < ticks.length; i++) ticks[i].labelY = Math.max(ticks[i].labelY, ticks[i - 1].labelY + gap);
  const overflow = ticks[ticks.length - 1].labelY - (height - top);
  if (overflow > 0) {
    ticks[ticks.length - 1].labelY -= overflow;
    for (let i = ticks.length - 2; i >= 0; i--) ticks[i].labelY = Math.min(ticks[i].labelY, ticks[i + 1].labelY - gap);
  }
  const axis = 96;
  return (
    <svg viewBox={`0 0 280 ${height}`} className="block w-full max-w-sm tabular-nums" role="img"
      aria-label={`Stock price ladder: ${points.map((p) => `${p.label} $${p.value.toFixed(2)}`).join(", ")}`}>
      <line x1={axis} x2={axis} y1={top - 4} y2={height - top + 4} stroke="currentColor" opacity="0.35" />
      {ticks.map((t) => {
        const now = t.label === "now";
        const tone = t.label === "stop" ? "var(--c-negative)" : t.label === "take profit" ? "var(--c-positive)" : "currentColor";
        return (
          <g key={t.label} fill={tone} fontSize="12" fontWeight={now ? 600 : 400}>
            <line x1={axis - 5} x2={axis + 5} y1={t.y} y2={t.y} stroke={tone} />
            <path d={`M ${axis + 6} ${t.y} L ${axis + 14} ${t.labelY}`} fill="none" stroke="currentColor" opacity="0.3" />
            {now && <circle cx={axis} cy={t.y} r="4.5" fill="var(--accent)" />}
            <text x={axis - 12} y={t.labelY} dy="0.35em" textAnchor="end">${t.value.toFixed(2)}</text>
            <text x={axis + 18} y={t.labelY} dy="0.35em">{t.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

function TradeActions({ option }: { option: Option }) {
  const [mode, setMode] = useState<"fill" | "close" | null>(null);
  const [value, setValue] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<"fill" | "close" | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || !mode) return;
    const price = number(value);
    if (price === undefined || (mode === "fill" ? price <= 0 : price < 0)) {
      setError(mode === "fill" ? "Enter a fill price greater than zero." : "Enter a buy-back price of zero or more.");
      return;
    }
    setPending(true);
    setError("");
    try {
      const { account, ticker, right, strike, expiry, qty } = option;
      await saveTrade({ account, ticker, right, strike, expiry, qty }, mode === "fill"
        ? { status: "open", price }
        : { status: "closed", close_price: price });
      setSaved(mode);
      setMode(null);
      setValue("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-2">
      {saved && <p role="status" className="text-[length:var(--t-xs)]">{savedMessage}</p>}
      {saved === "close" && <p className="text-[length:var(--t-xs)]">Close recorded.</p>}
      {!mode && <div className="flex flex-wrap gap-2">
        {option.credit === undefined && !saved && <button type="button" className={accentClass}
          onClick={() => { setMode("fill"); setError(""); }}>Add fill price</button>}
        <button type="button" className={buttonClass}
          onClick={() => { setMode("close"); setError(""); }}>I closed it</button>
      </div>}
      {mode && <form onSubmit={submit} noValidate className="space-y-2">
        <label className="block max-w-xs space-y-1 text-[length:var(--t-xs)]">
          <span>{mode === "fill" ? "Fill price per share ($)" : "Buy-back price per share ($)"}</span>
          <input type="number" inputMode="decimal" step="any" min="0" required autoFocus
            className={inputClass} value={value} disabled={pending} onChange={(e) => setValue(e.target.value)} />
        </label>
        <div className="flex gap-2">
          <button type="submit" disabled={pending} className={accentClass}>{pending ? "Saving…" : "Save"}</button>
          <button type="button" disabled={pending} className={buttonClass}
            onClick={() => { setMode(null); setValue(""); setError(""); }}>Cancel</button>
        </div>
      </form>}
      {error && <p role="alert" className="break-words text-[length:var(--t-xs)]">{error}</p>}
    </div>
  );
}

function OptionBlock({ option }: { option: Option }) {
  const verdict = text(option.row.verdict).trim();
  const keeper = text(option.row.keeper).trim();
  const keeperLabel = ({ keep: "Keep", cut: "Don't keep", unsure: "Unsure" } as Record<string, string>)[keeper] ?? "Unsure";
  const dte = number(option.row.dte);
  const expiry = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }).format(expiryDate(option.expiry));
  return (
    <article className="min-w-0 space-y-2.5">
      <div className="space-y-1">
        <h4 className="text-[length:var(--t-sm)] font-semibold tabular-nums">
          {option.ticker} ${option.strike.toFixed(2)} {option.right === "P" ? "put" : "call"} · {expiry}
          {dte !== undefined && ` · ${dte} ${dte === 1 ? "day" : "days"}`}
        </h4>
        <p className={`text-[length:var(--t-xs)] font-medium ${verdict === "stop" || verdict === "below"
          ? "text-[var(--c-negative)]" : verdict === "profit" ? "text-[var(--c-positive)]" : ""}`}>
          {verdicts[verdict] ?? "Verdict unavailable"}
        </p>
      </div>
      <p className="whitespace-pre-wrap break-words text-[length:var(--t-sm)] leading-relaxed">{text(option.row.action)}</p>
      {option.credit !== undefined && option.captured !== undefined && <div className="space-y-1.5">
        <p className="text-[length:var(--t-xs)] tabular-nums">Kept so far: {Math.round(option.captured * 100)}% of the credit</p>
        <div className="h-1 overflow-hidden rounded-full bg-[var(--surface-bright)]" aria-hidden="true">
          <div className="h-full bg-[var(--accent)]" style={{ width: `${Math.max(0, Math.min(1, option.captured)) * 100}%` }} />
        </div>
      </div>}
      <p className="break-words text-[length:var(--t-xs)]">If it goes wrong: {keeperLabel}{text(option.row.keeper_why) && ` · ${text(option.row.keeper_why)}`}</p>
      <PriceLadder option={option} />
      <TradeActions option={option} />
    </article>
  );
}

function NewOptionForm() {
  const [account, setAccount] = useState<Account>("caspar");
  const [ticker, setTicker] = useState("");
  const [right, setRight] = useState<Right>("P");
  const [strike, setStrike] = useState("");
  const [expiry, setExpiry] = useState("");
  const [contracts, setContracts] = useState("1");
  const [price, setPrice] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setSaved(false);
    setError("");
    const symbol = ticker.trim().toUpperCase();
    const strikeNumber = number(strike);
    const priceNumber = number(price);
    const qty = number(contracts);
    const expiryKey = expiry.replaceAll("-", "");
    if (!/^[A-Z][A-Z.]*$/.test(symbol)) { setError("Enter a ticker, letters only (BRK.B is fine)."); return; }
    if (strikeNumber === undefined || strikeNumber <= 0) { setError("Strike must be greater than zero."); return; }
    if (!expiryDate(expiryKey) || expiry <= todayEt()) { setError("Expiry must be a future date in New York."); return; }
    if (qty === undefined || !Number.isSafeInteger(qty) || qty <= 0) { setError("Contracts must be a positive whole number."); return; }
    if (priceNumber === undefined || priceNumber <= 0) { setError("Fill price must be greater than zero."); return; }
    setPending(true);
    try {
      await saveTrade({ account, ticker: symbol, right, strike: strikeNumber, expiry: expiryKey, qty: -qty }, { status: "open", price: priceNumber });
      setSaved(true);
      setTicker(""); setStrike(""); setExpiry(""); setContracts("1"); setPrice("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-3 border-t border-[var(--border)] pt-4">
      <h3 className="text-[length:var(--t-sm)] font-semibold">Log a new option</h3>
      <fieldset disabled={pending} className="grid min-w-0 grid-cols-2 gap-3 text-[length:var(--t-xs)]">
        <label className="min-w-0 space-y-1"><span>Account</span>
          <select className={inputClass} value={account} onChange={(e) => setAccount(e.target.value as Account)}>
            {accounts.map((a) => <option key={a} value={a}>{accountNames[a]}</option>)}
          </select>
        </label>
        <label className="min-w-0 space-y-1"><span>Ticker</span>
          <input className={inputClass} value={ticker} required autoCapitalize="characters" spellCheck={false} onChange={(e) => setTicker(e.target.value)} />
        </label>
        <label className="min-w-0 space-y-1"><span>Put / call</span>
          <select className={inputClass} value={right} onChange={(e) => setRight(e.target.value as Right)}>
            <option value="P">Put</option><option value="C">Call</option>
          </select>
        </label>
        <label className="min-w-0 space-y-1"><span>Strike ($)</span>
          <input className={inputClass} type="number" inputMode="decimal" step="any" min="0" required value={strike} onChange={(e) => setStrike(e.target.value)} />
        </label>
        <label className="col-span-2 min-w-0 space-y-1"><span>Expiry</span>
          <input className={inputClass} type="date" required value={expiry} onChange={(e) => setExpiry(e.target.value)} />
        </label>
        <label className="min-w-0 space-y-1"><span>Contracts sold</span>
          <input className={inputClass} type="number" inputMode="numeric" step="1" min="1" required value={contracts} onChange={(e) => setContracts(e.target.value)} />
        </label>
        <label className="min-w-0 space-y-1"><span>Fill per share ($)</span>
          <input className={inputClass} type="number" inputMode="decimal" step="any" min="0" required value={price} onChange={(e) => setPrice(e.target.value)} />
        </label>
      </fieldset>
      <button className={accentClass} disabled={pending} type="submit">{pending ? "Saving…" : "Save option"}</button>
      {error && <p role="alert" className="break-words text-[length:var(--t-xs)]">{error}</p>}
      {saved && <p role="status" className="text-[length:var(--t-xs)]">{savedMessage}</p>}
    </form>
  );
}

export function OpenOptionsCard() {
  const [rows, setRows] = useState<RawRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let active = true;
    fetchTab<RawRow>("holdings_monitor").then((data) => {
      if (active) setRows(data);
    }).catch((err: unknown) => {
      if (active) setError(errorText(err));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [attempt]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const timed = rows.map((row) => ({ row, time: updatedTime(row.updated_at) }));
  const latest = timed.reduce<number | undefined>((max, item) => item.time !== undefined && (max === undefined || item.time > max) ? item.time : max, undefined);
  const newest = latest === undefined ? [] : timed.filter((item) => item.time === latest);
  const options = newest.map(({ row }) => parseOption(row)).filter((option): option is Option => option !== undefined);
  const invalid = newest.length - options.length + timed.filter((item) => item.time === undefined).length;
  options.sort((a, b) => accounts.indexOf(a.account) - accounts.indexOf(b.account)
    || Number(urgent.has(text(b.row.verdict).trim())) - Number(urgent.has(text(a.row.verdict).trim()))
    || a.expiry.localeCompare(b.expiry) || a.ticker.localeCompare(b.ticker) || a.strike - b.strike);

  return (
    <Card className="min-w-0 space-y-5">
      <header className="space-y-1">
        <h2 className="text-[length:var(--t-sm)] font-semibold">Open options</h2>
        {latest !== undefined && <p className="text-[length:var(--t-xs)] tabular-nums">
          as of {clock(latest, ET)} ET · {clock(latest, "Asia/Singapore")} SGT
          {isStale(latest, now) && <span className="ml-2 font-medium">may be out of date</span>}
        </p>}
      </header>
      {loading ? <p role="status" className="text-[length:var(--t-sm)]">Loading open options…</p>
        : error ? <div className="space-y-2">
          <p role="alert" className="break-words text-[length:var(--t-xs)]">{error}</p>
          <button className={buttonClass} type="button" onClick={() => { setLoading(true); setError(""); setAttempt((n) => n + 1); }}>Try again</button>
        </div> : <>
          {invalid > 0 && <p role="alert" className="text-[length:var(--t-xs)]">Some option rows have invalid dates or contract details and could not be displayed.</p>}
          {options.length === 0 && <p className="text-[length:var(--t-sm)]">{invalid ? "No valid open option rows available." : "No open options."}</p>}
          {accounts.map((account) => {
            const group = options.filter((option) => option.account === account);
            return group.length > 0 && <section key={account} aria-label={accountNames[account]} className="space-y-4">
              <h3 className="text-[length:var(--t-xs)] font-semibold">{accountNames[account]}</h3>
              <div className="space-y-6">{group.map((option) => <OptionBlock key={legId(option)} option={option} />)}</div>
            </section>;
          })}
        </>}
      <NewOptionForm />
    </Card>
  );
}
