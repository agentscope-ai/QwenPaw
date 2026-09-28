import { request } from "../request";
import type { HeartbeatConfig } from "../types/heartbeat";

export const heartbeatApi = {
  getHeartbeatConfig: () => request<HeartbeatConfig>("/config/heartbeat"),

  updateHeartbeatConfig: (body: HeartbeatConfig, agentId?: string) =>
    request<HeartbeatConfig>("/config/heartbeat", {
      method: "PUT",
      ...(agentId ? { headers: { "X-Agent-Id": agentId } } : {}),
      body: JSON.stringify(body),
    }),

  runHeartbeatNow: () =>
    request<{ started: boolean }>("/config/heartbeat/run", {
      method: "POST",
    }),
};
