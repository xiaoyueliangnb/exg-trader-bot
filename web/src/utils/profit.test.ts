import { describe, expect, it } from "vitest";
import { groupByMonth, movingAverage, roundProfit, summarizeDays } from "./profit";

describe("roundProfit", () => {
  it("604 / 658 的 10 币一套利润是 138", () => {
    const r = roundProfit(604, 658, 10);
    expect(r.listed).toBe(6040);
    expect(r.feeIn).toBe(302);
    expect(r.feeOut).toBe(100);
    expect(r.earned).toBe(6580);
    expect(r.profit).toBe(138);
  });
});

describe("movingAverage", () => {
  it("窗口不足时为 null", () => {
    expect(movingAverage([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });
});

describe("汇总", () => {
  const days = [
    { date: "2026-11-27", profit: 100, n_pair: 2, fee_c: 10, fee_p: 5 },
    { date: "2026-11-28", profit: -40, n_pair: 1, fee_c: 0, fee_p: 8 },
    { date: "2026-10-31", profit: 20, n_pair: 1, fee_c: 1, fee_p: 1 },
  ];

  it("累计、日均、最好和最差", () => {
    const s = summarizeDays(days);
    expect(s.profit).toBe(80);
    expect(s.pairs).toBe(4);
    expect(s.avg).toBe(27);
    expect(s.best?.date).toBe("2026-11-27");
    expect(s.worst?.date).toBe("2026-11-28");
  });

  it("按月汇总并倒序", () => {
    const months = groupByMonth(days);
    expect(months.map((m) => m.month)).toEqual(["2026-11", "2026-10"]);
    expect(months[0]).toMatchObject({ days: 2, pairs: 3, fee: 23, profit: 60 });
  });
});
