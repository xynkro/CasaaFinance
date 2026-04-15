import Papa from "papaparse";

const SHEET_ID = "1N2AAx1GqTi23Qlq6MZkQoYfQOY7An1K0vvPx65YBiQc";

function csvUrl(gid: string): string {
  return `https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq?tqx=out:csv&gid=${gid}`;
}

// GIDs — set these after enabling "publish to web" per tab in Sheets.
// To find a tab's GID: open the sheet, click the tab, look at the URL fragment #gid=XXXX.
const GIDS: Record<string, string> = {
  daily_brief_latest: "0",
  snapshot_caspar: "1",
  snapshot_sarah: "2",
  macro: "3",
};

async function fetchTab<T>(tab: keyof typeof GIDS): Promise<T[]> {
  const res = await fetch(csvUrl(GIDS[tab]));
  if (!res.ok) throw new Error(`Sheet fetch failed: ${tab} (${res.status})`);
  const text = await res.text();
  const { data } = Papa.parse<T>(text, { header: true, skipEmptyLines: true });
  return data;
}

// ---------- typed rows ----------

export interface DailyBriefRow {
  date: string;
  bullet_1: string;
  bullet_2: string;
  bullet_3: string;
  verdict: string;
  sentiment: string;
}

export interface SnapshotRow {
  date: string;
  net_liq: string;
  cash: string;
  upl: string;
  upl_pct: string;
}

export interface MacroRow {
  date: string;
  vix: string;
  dxy: string;
  us_10y: string;
  spx: string;
  usd_sgd: string;
}

// ---------- aggregate fetch ----------

export interface DashboardData {
  daily: DailyBriefRow | null;
  caspar: SnapshotRow | null;
  sarah: SnapshotRow | null;
  macro: MacroRow | null;
  error: string | null;
}

function latest<T extends { date: string }>(rows: T[]): T | null {
  if (!rows.length) return null;
  return rows.reduce((a, b) => (a.date > b.date ? a : b));
}

export async function fetchDashboard(): Promise<DashboardData> {
  try {
    const [dailyRows, casparRows, sarahRows, macroRows] = await Promise.all([
      fetchTab<DailyBriefRow>("daily_brief_latest"),
      fetchTab<SnapshotRow>("snapshot_caspar"),
      fetchTab<SnapshotRow>("snapshot_sarah").catch(() => [] as SnapshotRow[]),
      fetchTab<MacroRow>("macro"),
    ]);
    return {
      daily: latest(dailyRows),
      caspar: latest(casparRows),
      sarah: latest(sarahRows),
      macro: latest(macroRows),
      error: null,
    };
  } catch (e) {
    return { daily: null, caspar: null, sarah: null, macro: null, error: String(e) };
  }
}
