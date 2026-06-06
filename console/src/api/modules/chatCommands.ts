import { request } from "../request";

export interface AvailableCommand {
  command: string;
  display: string;
  category: string;
  has_args: boolean;
}

export interface ChatCommandsResponse {
  commands: string[];
}

export const chatCommandsApi = {
  getAvailable: () => request<AvailableCommand[]>("/chat-commands/available"),

  get: () => request<ChatCommandsResponse>("/chat-commands"),

  update: (commands: string[]) =>
    request<ChatCommandsResponse>("/chat-commands", {
      method: "PUT",
      body: JSON.stringify({ commands }),
    }),
};
