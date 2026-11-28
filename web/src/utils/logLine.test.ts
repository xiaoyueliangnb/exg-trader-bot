import { describe, expect, it } from "vitest";
import { classifyLog, matchLogFilter } from "./logLine";

describe("classifyLog", () => {
  it("错误优先于其它颜色", () => {
    expect(classifyLog("本轮异常：连接失败")).toBe("bad");
    expect(classifyLog("验证码错误，请重试")).toBe("bad");
    expect(classifyLog("需要验证码，暂停 10 分钟")).toBe("warn");
    expect(classifyLog("卖积分结果：上架成功 6040积分")).toBe("good");
    expect(classifyLog("1800 秒（30 分钟）后重新登录")).toBe("dim");
    expect(classifyLog("打开：积分商城")).toBe("");
  });
});

describe("matchLogFilter", () => {
  it("交易和异常分开筛", () => {
    expect(matchLogFilter("盘口最低 604", "trade")).toBe(true);
    expect(matchLogFilter("打开：积分商城", "trade")).toBe(false);
    expect(matchLogFilter("需要验证码", "issue")).toBe(true);
    expect(matchLogFilter("上架成功", "issue")).toBe(false);
    expect(matchLogFilter("随便一行", "all")).toBe(true);
  });
});
