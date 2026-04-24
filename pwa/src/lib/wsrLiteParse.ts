/**
 * wsrLiteParse.ts — Parse WSR Lite raw markdown into typed structures.
 *
 * WSR Lite has 6 strict sections. This parser is intentionally permissive:
 * if a section is missing or malformed it degrades gracefully rather than throwing.
 */

export type TriggerStatus = "HIT" | "CLOSE" | "DORMANT";
export type TrafficLight = "🟢" | "🟡" | "🔴";
export type QueueStatus = "ACTIONABLE" | "CLOSE" | "WAIT";
export type BottomLineTag = "Judgement" | "Synthesis" | "Opinion";

export interface TriggerRow {
  ticker: string;
  price: string;
  status: TriggerStatus;
  action: string;
}

export interface TrafficLightRow {
  ticker: string;
  strategy: string;
  strike: string;
  dte: string;
  underlying: string;
  proximity: string;
  flag: TrafficLight;
  note: string;
}

export interface DecisionQueueRow {
  rank: number;
  ticker: string;
  entry: string;
  last: string;
  distancePct: string;
  status: QueueStatus;
  statusNote: string;
}

export interface CatalystDay {
  label: string; // e.g. "Mon Apr 27"
  bullets: string[];
}

export interface BottomLine {
  text: string;
  confidence: number;
  tag: BottomLineTag;
}

export interface WsrLiteParsed {
  date: string;
  triggers: TriggerRow[];
  options: TrafficLightRow[];
  regimeDrift: string;
  regimeUnchanged: boolean;
  decisionQueue: DecisionQueueRow[];
  catalysts: CatalystDay[];
  bottomLine: BottomLine;
}

// ── helpers ──────────────────────────────────────────────────────────────────

function extractSection(md: string, heading: string): string {
  const re = new RegExp(
    `##\\s+${heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[^\n]*\n([\\s\\S]+?)(?=\n##|$)`,
    "i"
  );
  return re.exec(md)?.[1]?.trim() ?? "";
}

function parseTrafficFlag(raw: string): TrafficLight {
  if (raw.includes("🔴") || raw.toLowerCase().includes("red")) return "🔴";
  if (raw.includes("🟡") || raw.toLowerCase().includes("yellow")) return "🟡";
  return "🟢";
}

function parseTriggerStatus(raw: string): TriggerStatus {
  const u = raw.toUpperCase();
  if (u.includes("HIT")) return "HIT";
  if (u.includes("CLOSE")) return "CLOSE";
  return "DORMANT";
}

function parseQueueStatus(raw: string): QueueStatus {
  const u = raw.toUpperCase();
  if (u.includes("ACTIONABLE")) return "ACTIONABLE";
  if (u.includes("CLOSE")) return "CLOSE";
  return "WAIT";
}

function stripMd(s: string): string {
  return s.replace(/\*{1,3}/g, "").replace(/`/g, "").trim();
}

// ── section parsers ───────────────────────────────────────────────────────────

function parseTriggers(section: string): TriggerRow[] {
  const rows: TriggerRow[] = [];
  for (const line of section.split("\n")) {
    const m = line.match(/^\s*[-*]\s+\*{0,2}([A-Z]+)\*{0,2}\s+([\S]+)\s+[—–-]+\s+\*{0,2}(HIT|CLOSE|DORMANT)\*{0,2}[^.]*\.?\s*(.*)/i);
    if (!m) continue;
    rows.push({
      ticker: m[1].trim(),
      price: m[2].replace(/[*]/g, "").trim(),
      status: parseTriggerStatus(m[3]),
      action: stripMd(m[4] ?? ""),
    });
  }
  return rows;
}

function parseTableRows(section: string): string[][] {
  return section
    .split("\n")
    .filter((l) => l.includes("|") && !/^[\s|:-]+$/.test(l))
    .map((l) =>
      l
        .split("|")
        .map((c) => c.trim())
        .filter((c) => c.length > 0)
    )
    .filter((r) => r.length >= 2);
}

function parseOptionsTraffic(section: string): TrafficLightRow[] {
  const rows = parseTableRows(section);
  const header = rows[0]?.map((h) => h.toLowerCase()) ?? [];
  const isHeaderRow = header.some((h) => h.includes("tick") || h.includes("flag"));
  const dataRows = isHeaderRow ? rows.slice(1) : rows;
  return dataRows.map((r) => ({
    ticker:     r[0] ?? "",
    strategy:   r[1] ?? "",
    strike:     r[2] ?? "",
    dte:        r[3] ?? "",
    underlying: r[4] ?? "",
    proximity:  r[5] ?? "",
    flag:       parseTrafficFlag(r[6] ?? ""),
    note:       stripMd(r[7] ?? ""),
  }));
}

function parseDecisionQueue(section: string): DecisionQueueRow[] {
  const rows = parseTableRows(section);
  const header = rows[0]?.map((h) => h.toLowerCase()) ?? [];
  const isHeaderRow = header.some((h) => h.includes("rank") || h.includes("tick"));
  const dataRows = isHeaderRow ? rows.slice(1) : rows;
  return dataRows.map((r) => {
    const statusRaw = stripMd(r[5] ?? "");
    const statusNote = statusRaw.replace(/^(ACTIONABLE|CLOSE|WAIT)\s*/i, "").replace(/^[—–-]+\s*/, "").trim();
    return {
      rank:        parseInt(r[0] ?? "0", 10) || 0,
      ticker:      stripMd(r[1] ?? ""),
      entry:       r[2] ?? "",
      last:        r[3] ?? "",
      distancePct: r[4] ?? "",
      status:      parseQueueStatus(statusRaw),
      statusNote,
    };
  });
}

function parseCatalysts(section: string): CatalystDay[] {
  const days: CatalystDay[] = [];
  let current: CatalystDay | null = null;
  for (const line of section.split("\n")) {
    const dayMatch = line.match(/[-*]\s+\*{0,2}((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[^:*]+)\*{0,2}:/i);
    if (dayMatch) {
      current = { label: dayMatch[1].trim(), bullets: [] };
      days.push(current);
      const rest = line.slice(line.indexOf(":") + 1).trim().replace(/\*{1,3}/g, "").trim();
      if (rest) current.bullets.push(stripMd(rest));
    } else if (current && line.match(/^\s*[-*]\s+/)) {
      current.bullets.push(stripMd(line.replace(/^\s*[-*]\s+/, "")));
    }
  }
  return days;
}

function parseBottomLine(section: string): BottomLine {
  const text = stripMd(section.replace(/Confidence[:\s]+[\d.]+\.?/gi, "").trim());
  const confM = section.match(/[Cc]onfidence[:\s]+([\d.]+)/);
  const confidence = confM ? parseFloat(confM[1]) : 0.7;
  const tagM = section.match(/\((Judgement|Synthesis|Opinion)\)/i);
  const tag = (tagM?.[1] ?? "Synthesis") as BottomLineTag;
  return { text, confidence, tag };
}

function parseDateFromHeading(md: string): string {
  const m = md.match(/(\d{4}-\d{2}-\d{2})/);
  return m?.[1] ?? "";
}

// ── main export ───────────────────────────────────────────────────────────────

export function parseWsrLite(raw_md: string): WsrLiteParsed {
  const triggerSection   = extractSection(raw_md, "Trigger Audit");
  const optionsSection   = extractSection(raw_md, "Options Book Traffic Lights");
  const regimeSection    = extractSection(raw_md, "Regime Drift");
  const queueSection     = extractSection(raw_md, "Decision Queue Status");
  const catalystSection  = extractSection(raw_md, "Catalyst Calendar");
  const bottomSection    = extractSection(raw_md, "Bottom Line");

  return {
    date:           parseDateFromHeading(raw_md),
    triggers:       parseTriggers(triggerSection),
    options:        parseOptionsTraffic(optionsSection),
    regimeDrift:    regimeSection,
    regimeUnchanged: /REGIME\s+UNCHANGED/i.test(regimeSection),
    decisionQueue:  parseDecisionQueue(queueSection),
    catalysts:      parseCatalysts(catalystSection),
    bottomLine:     parseBottomLine(bottomSection),
  };
}

/** Returns true if the WSR Lite is "fresh" — within 72 h (covers Fri → Mon gap). */
export function isWsrLiteFresh(dateStr: string): boolean {
  if (!dateStr) return false;
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return false;
  return Date.now() - d.getTime() < 72 * 3_600_000;
}

/** Next Wed or Fri after `now` at 19:30 SGT, formatted as readable string. */
export function nextPulseLabel(): string {
  const now = new Date();
  // SGT = UTC+8
  const sgtMs = now.getTime() + 8 * 3_600_000;
  const sgt = new Date(sgtMs);
  const day = sgt.getUTCDay(); // 0=Sun…6=Sat
  const hour = sgt.getUTCHours();
  const min = sgt.getUTCMinutes();
  const passedToday = hour > 19 || (hour === 19 && min >= 30);

  // Days until next Wed(3) or Fri(5)
  const targets = [3, 5];
  let best = 8;
  for (const t of targets) {
    let diff = t - day;
    if (diff < 0) diff += 7;
    if (diff === 0 && passedToday) diff = 7;
    if (diff < best) best = diff;
  }
  const next = new Date(sgtMs + best * 86_400_000);
  return next.toLocaleDateString("en-SG", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" }) + " 19:30 SGT";
}
