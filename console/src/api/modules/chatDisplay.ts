import { request } from "../request";

import type { AssistantMessageDisplayPreference } from "../../utils/chatDisplayPreference";

export interface ChatDisplayConfig {
  assistant_message_display_mode?: AssistantMessageDisplayPreference;
}

export const chatDisplayApi = {
  get: () => request<ChatDisplayConfig>("/config/chat-display"),

  update: (chatDisplay: ChatDisplayConfig) =>
    request<ChatDisplayConfig>("/config/chat-display", {
      method: "PUT",
      body: JSON.stringify(chatDisplay),
    }),

  reset: () => request<void>("/config/chat-display", { method: "DELETE" }),
};
