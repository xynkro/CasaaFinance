import Papa from "papaparse";

const SHEET_ID = "1N2AAx1GqTi23Qlq6MZkQoYfQOY7An1K0vvPx65YBiQc";

function csvUrl(gid: string): string {
  return `https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq?tqx=out:csv&gid=${gid}`;
}

const GIDS: Record<string, string> = {
  daily_brief_latest: "1490893125",
  snapshot_caspar: "1233934747",
  snapshot_sarah: "1953218382",
  positions_caspar: "981534946",
  positions_sarah: "444641294",
  decision_queue: "1744723757",
  options: "326503132",
  macro: "447436838",
  wsr_archive: "1065773181",
};

async function fetchTab<T>(tab: keyof typeof GIDS): Promise<T[]> {
  const res = await fetch(csvUrl(GIDS[tab]));
  if (!res.ok) throw new Error(`Sheet fetch failed: ${tab} (${res.status})`);
  const text = await res.text();
  const { data } = Papa.parse<T>(text, { header: true, skipEmptyLines: true });
  return data;
}

/**
 * Normalize snapshot rows from either account's CSV headers into the
 * generic SnapshotRow shape.  Caspar's sheet uses `net_liq_usd` / `cash`,
 * Sarah's uses `net_liq_sgd` / `cash_sgd` / `upl_sgd`, but the frontend
 * expects `net_liq` / `cash` / `upl` everywhere.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeSnapshot(rows: any[]): SnapshotRow[] {
  return rows.map((r) => ({
    date: r.date ?? "",
    net_liq: r.net_liq ?? r.net_liq_usd ?? r.net_liq_sgd ?? "0",
    cash: r.cash ?? r.cash_sgd ?? "0",
    upl: r.upl ?? r.upl_sgd ?? "0",
    upl_pct: r.upl_pct ?? "0",
  }));
}

// ---------- typed rows ----------

export interface DailyBriefRow {
  date: string;
  bullet_1: string;
  bullet_2: string;
  bullet_3: string;
  verdict: string;
  sentiment: string;
  // Rich sections (optional — older rows may be blank)
  headline?: string;
  overnight?: string;   // pipe-separated bullets
  premarket?: string;
  catalysts?: string;
  commodities?: string;
  posture?: string;
  watch?: string;
  raw_md?: string;      // full original markdown brief
}

export interface SnapshotRow {
  date: string;
  net_liq: string;
  cash: string;
  upl: string;
  upl_pct: string;
}

export interface PositionRow {
  date: string;
  ticker: string;
  qty: string;
  avg_cost: string;
  last: string;
  mkt_val: string;
  upl: string;
  weight: string;
}

export interface MacroRow {
  date: string;
  vix: string;
  dxy: string;
  us_10y: string;
  spx: string;
  usd_sgd: string;
}

export interface OptionRow {
  date: string;
  account: string;
  ticker: string;
  right: string;        // "C" | "P"
  strike: string;
  expiry: string;       // "YYYYMMDD"
  qty: string;
  credit: string;       // premium per share
  last: string;
  mkt_val: string;
  upl: string;
  underlying_last: string;
  moneyness: string;    // "ITM" | "ATM" | "OTM"
  dte: string;
  assignment_risk: string; // "LOW" | "MED" | "HIGH"
  wheel_leg: string;    // "CC" | "CSP" | "LONG_CALL" | "LONG_PUT"
  adj_cost_basis: string;
  momentum_5d: string;  // 5-day rate of change %
  trend_risk: string;   // "SAFE" | "DRIFTING" | "CONVERGING" | "BREACHING"
}

export interface DecisionRow {
  date: string;
  account: string;
  ticker: string;
  bucket: string;
  thesis_1liner: string;
  conv: string;
  entry: string;
  target: string;
  status: string;
}

export interface ArchiveRow {
  date: string;
  title: string;
  drive_file_id: string;
  drive_url: string;
}

// ---------- aggregate fetch ----------

export interface DashboardData {
  dailyHistory: DailyBriefRow[];
  daily: DailyBriefRow | null;
  caspar: SnapshotRow | null;
  sarah: SnapshotRow | null;
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  options: OptionRow[];
  decisions: DecisionRow[];
  macro: MacroRow | null;
  // History (all rows, sorted by date ascending)
  casparHistory: SnapshotRow[];
  sarahHistory: SnapshotRow[];
  macroHistory: MacroRow[];
  archive: ArchiveRow[];
  error: string | null;
}

function latest<T extends { date: string }>(rows: T[]): T | null {
  if (!rows.length) return null;
  return rows.reduce((a, b) => (a.date > b.date ? a : b));
}

function latestGroup<T extends { date: string }>(rows: T[]): T[] {
  const l = latest(rows);
  if (!l) return [];
  return rows.filter((r) => r.date === l.date);
}

function sortByDate<T extends { date: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => a.date.localeCompare(b.date));
}

/** Deduplicate rows per date (keep last entry per date). */
function dedup<T extends { date: string }>(rows: T[]): T[] {
  const map = new Map<string, T>();
  for (const r of rows) {
    const key = r.date.slice(0, 10); // normalize to YYYY-MM-DD
    map.set(key, r);
  }
  return sortByDate([...map.values()]);
}

export async function fetchDashboard(): Promise<DashboardData> {
  try {
    const [dailyRows, casparRaw, sarahRaw, casparPos, sarahPos, optionRows, decisions, macroRows, archiveRows] =
      await Promise.all([
        fetchTab<DailyBriefRow>("daily_brief_latest"),
        fetchTab<Record<string, string>>("snapshot_caspar"),
        fetchTab<Record<string, string>>("snapshot_sarah").catch(() => [] as Record<string, string>[]),
        fetchTab<PositionRow>("positions_caspar").catch(() => [] as PositionRow[]),
        fetchTab<PositionRow>("positions_sarah").catch(() => [] as PositionRow[]),
        fetchTab<OptionRow>("options").catch(() => [] as OptionRow[]),
        fetchTab<DecisionRow>("decision_queue").catch(() => [] as DecisionRow[]),
        fetchTab<MacroRow>("macro"),
        fetchTab<ArchiveRow>("wsr_archive").catch(() => [] as ArchiveRow[]),
      ]);
    const casparRows = normalizeSnapshot(casparRaw);
    const sarahRows = normalizeSnapshot(sarahRaw);
    return {
      dailyHistory: dedup(dailyRows).reverse(),
      daily: latest(dailyRows),
      caspar: latest(casparRows),
      sarah: latest(sarahRows),
      casparPositions: latestGroup(casparPos),
      sarahPositions: latestGroup(sarahPos),
      options: latestGroup(optionRows),
      decisions: latestGroup(decisions),
      macro: latest(macroRows),
      casparHistory: dedup(casparRows),
      sarahHistory: dedup(sarahRows),
      macroHistory: dedup(macroRows),
      archive: sortByDate(archiveRows).reverse(),
      error: null,
    };
  } catch (e) {
    return {
      dailyHistory: [], daily: null, caspar: null, sarah: null,
      casparPositions: [], sarahPositions: [], options: [], decisions: [],
      macro: null, casparHistory: [], sarahHistory: [], macroHistory: [],
      archive: [], error: String(e),
    };
  }
}
