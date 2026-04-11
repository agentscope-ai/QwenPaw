import { request } from "../request";

export interface TimeAwarenessConfig {
  enabled: boolean;
  format: string | null;
}

export const timeAwarenessApi = {
  getTimeAwareness: () =>
    request<TimeAwarenessConfig>("/config/time-awareness"),

  updateTimeAwareness: (config: Partial<TimeAwarenessConfig>) =>
    request<TimeAwarenessConfig>("/config/time-awareness", {
      method: "PUT",
      body: JSON.stringify(config),
    }),
};
