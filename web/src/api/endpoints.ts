import { api } from "./client";
import type { Analysis, AuthResp, BotActionResp, LogsResp, Overview } from "./types";

export function getAuth(token: string): Promise<AuthResp> {
  return fetch("/api/auth", { headers: { "X-Token": token } }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<AuthResp>;
  });
}

export const getOverview = () => api<Overview>("/api/overview");
export const getLogs = (since: number) => api<LogsResp>(`/api/logs?since=${since}`);
export const getAnalysis = (days: number) => api<Analysis>(`/api/analysis?days=${days}`);
export const startBot = () => api<BotActionResp>("/api/bot/start", { method: "POST" });
export const stopBot = () => api<BotActionResp>("/api/bot/stop", { method: "POST" });
