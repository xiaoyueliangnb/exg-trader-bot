const BAD = /异常|失败|错误|Traceback|Error|退出 code/;
const WARN = /验证码|暂停|重连|重新连接/;
const GOOD = /上架成功|已挂|本轮已提交|结算/;
const DIM = /后重新登录|秒后再/;
const TRADE = /上架|报价|分档|盘口|利润|已挂|维持|不挂/;

export type LogKind = "bad" | "warn" | "good" | "dim" | "";
export type LogFilter = "all" | "trade" | "issue";

export function classifyLog(line: string): LogKind {
  if (BAD.test(line)) return "bad";
  if (WARN.test(line)) return "warn";
  if (GOOD.test(line)) return "good";
  if (DIM.test(line)) return "dim";
  return "";
}

export function logClass(line: string): string {
  const kind = classifyLog(line);
  return kind ? `l-${kind}` : "";
}

export function matchLogFilter(line: string, filter: LogFilter): boolean {
  if (filter === "trade") return TRADE.test(line);
  if (filter === "issue") {
    const kind = classifyLog(line);
    return kind === "bad" || kind === "warn";
  }
  return true;
}
