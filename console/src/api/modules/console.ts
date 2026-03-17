import { request } from "../request";

export interface PushMessage {
  id: string;
  text: string;
}

export interface AuthDebugEventPayload {
  event: "login" | "register";
  stage: "start" | "success" | "failed";
  phone?: string;
  countryCode?: string;
  userId?: string | number | null;
  status?: string | boolean | null;
  error?: string;
}

export const consoleApi = {
  getPushMessages: () =>
    request<{ messages: PushMessage[] }>("/console/push-messages"),
  reportAuthDebugEvent: (payload: AuthDebugEventPayload) =>
    request<{ ok: boolean }>("/console/auth-debug-events", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
