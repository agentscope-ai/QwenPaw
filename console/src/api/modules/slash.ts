import { request } from "../request";

export type SlashItemType =
  | "command"
  | "skill"
  | "mcp_client"
  | "mcp_tool";

export interface SlashCatalogItem {
  id: string;
  type: SlashItemType;
  label: string;
  command: string;
  insertText: string;
  description: string;
  icon: string;
  group: string;
  enabled: boolean;
}

export const slashApi = {
  catalog: (agentId?: string) => {
    const opts: RequestInit = {};
    if (agentId) opts.headers = new Headers({ "X-Agent-Id": agentId });
    return request<SlashCatalogItem[]>("/slash/catalog", opts);
  },
};
