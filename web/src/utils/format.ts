export function fmt(n: number | null | undefined, digits?: number): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  if (digits == null) return v.toLocaleString("zh-CN");
  return v.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtSigned(n: number | null | undefined, digits?: number): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const body = fmt(Math.abs(n), digits);
  if (n > 0) return `+${body}`;
  if (n < 0) return `-${body}`;
  return body;
}

export function pct(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return "—";
  return `${Math.round(Number(x) * 100)}%`;
}

export function pad(h: number): string {
  return String(h).padStart(2, "0");
}

/** 倒计时。90 秒显示 01:30，30 分钟显示 30:00。 */
export function clock(sec: number | null | undefined): string {
  if (sec == null || Number.isNaN(sec)) return "";
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function parseTime(iso: string): number {
  return new Date(iso.replace(" ", "T")).getTime();
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const sec = (now - parseTime(iso)) / 1000;
  if (!Number.isFinite(sec) || sec < 60) return "刚刚";
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  return `${Math.floor(sec / 86400)} 天前`;
}

/** 把小时列表收成半开区间，12,13,14 → [12, 15]。 */
export function hourBands(hours: number[]): [number, number][] {
  const out: [number, number][] = [];
  for (const h of [...hours].sort((a, b) => a - b)) {
    const last = out[out.length - 1];
    if (last && last[1] === h) last[1] = h + 1;
    else out.push([h, h + 1]);
  }
  return out;
}

export function hourRanges(hours: number[]): string {
  const bands = hourBands(hours);
  if (!bands.length) return "无";
  return bands.map(([a, b]) => `${a}–${b}`).join("、");
}

export function peakDiff(current: number[], suggested: number[]) {
  const cur = new Set(current);
  const sug = new Set(suggested);
  return {
    add: [...sug].filter((h) => !cur.has(h)).sort((a, b) => a - b),
    drop: [...cur].filter((h) => !sug.has(h)).sort((a, b) => a - b),
  };
}

export type Tone = "good" | "bad" | "";

export function toneOf(n: number | null | undefined): Tone {
  if (n == null || Number.isNaN(Number(n)) || Number(n) === 0) return "";
  return Number(n) > 0 ? "good" : "bad";
}

export function uptimeText(startedAt: string | null | undefined, now = Date.now()): string {
  if (!startedAt) return "";
  const sec = (now - new Date(startedAt).getTime()) / 1000;
  if (!Number.isFinite(sec) || sec < 0) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h ? `已运行 ${h} 小时 ${m} 分` : `已运行 ${m} 分钟`;
}
