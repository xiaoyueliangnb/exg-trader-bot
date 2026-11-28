import { describe, expect, it } from "vitest";
import { ago, clock, fmt, hourBands, hourRanges, pad, peakDiff, toneOf } from "./format";

describe("fmt", () => {
  it("空值显示破折号", () => {
    expect(fmt(null)).toBe("—");
    expect(fmt(undefined)).toBe("—");
    expect(fmt(Number.NaN)).toBe("—");
  });

  it("与本机中文格式一致", () => {
    expect(fmt(1234)).toBe((1234).toLocaleString("zh-CN"));
    expect(fmt(1.5, 1)).toBe((1.5).toLocaleString("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
  });
});

describe("clock", () => {
  it("按总分钟显示", () => {
    expect(clock(65)).toBe("01:05");
    expect(clock(1800)).toBe("30:00");
    expect(clock(-3)).toBe("00:00");
    expect(clock(null)).toBe("");
  });
});

describe("ago", () => {
  const now = new Date("2026-11-28T01:30:00").getTime();

  it("按距离分档", () => {
    expect(ago("2026-11-28 01:29:30", now)).toBe("刚刚");
    expect(ago("2026-11-28 01:20:00", now)).toBe("10 分钟前");
    expect(ago("2026-11-28 00:20:00", now)).toBe("1 小时前");
    expect(ago("2026-11-26 01:30:00", now)).toBe("2 天前");
    expect(ago(null, now)).toBe("—");
  });
});

describe("时段", () => {
  it("合并相邻小时", () => {
    expect(hourBands([14, 12, 13, 17])).toEqual([
      [12, 15],
      [17, 18],
    ]);
    expect(hourRanges([12, 13, 14, 17])).toBe("12–15、17–18");
    expect(hourRanges([])).toBe("无");
    expect(pad(3)).toBe("03");
  });

  it("对比当前高峰和建议高峰", () => {
    expect(peakDiff([12, 13, 16], [12, 13, 14])).toEqual({ add: [14], drop: [16] });
  });
});

describe("toneOf", () => {
  it("零和空为中性", () => {
    expect(toneOf(0)).toBe("");
    expect(toneOf(null)).toBe("");
    expect(toneOf(3)).toBe("good");
    expect(toneOf(-1)).toBe("bad");
  });
});
