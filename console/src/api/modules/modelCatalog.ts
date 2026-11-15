import { request } from "../request";
import { readModelMetadata, invalidateModelReads } from "../modelReads";
import type { ActiveModelsInfo, ModelSlotConfig } from "../types/provider";

export interface CatalogModel {
  id: string;
  provider_id: string;
  provider_name: string;
  model: string;
  name: string;
  supports_image: boolean | null;
  supports_video: boolean | null;
  max_input_length: number;
  available: boolean;
}
export interface ConversationModel extends ActiveModelsInfo {
  source: string;
  model_override: ModelSlotConfig | null;
  locked: boolean;
}
export const modelCatalogApi = {
  list: (agentId?: string) =>
    readModelMetadata<{ enforced: boolean; models: CatalogModel[] }>(
      `/model-catalog${
        agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ""
      }`,
      agentId,
    ),
  default: (agentId?: string) =>
    readModelMetadata<ConversationModel>(
      `/model-catalog/default${
        agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ""
      }`,
      agentId,
    ),
  current: (chatId: string) =>
    readModelMetadata<ConversationModel>(
      `/chats/${encodeURIComponent(chatId)}/model`,
    ),
  select: async (chatId: string, model: ModelSlotConfig | null) => {
    invalidateModelReads();
    try {
      return await request<ConversationModel>(
        `/chats/${encodeURIComponent(chatId)}/model`,
        {
          method: "PUT",
          body: JSON.stringify(model),
        },
      );
    } finally {
      invalidateModelReads();
    }
  },
};

export function createSelectionScope() {
  let key = "";
  let generation = 0;
  let selected: ModelSlotConfig | undefined;
  return {
    reset() {
      key = "";
      generation++;
      selected = undefined;
    },
    enter(user: string, agent: string, chat: string) {
      const next = JSON.stringify([user, agent, chat]);
      if (key !== next) {
        key = next;
        generation++;
        selected = undefined;
      }
      return generation;
    },
    current(token: number) {
      return token === generation;
    },
    setDraft(token: number, model?: ModelSlotConfig) {
      if (token === generation) selected = model;
    },
    draft(token: number) {
      return token === generation ? selected : undefined;
    },
  };
}
