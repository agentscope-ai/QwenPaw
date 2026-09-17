import {
  createSelectionScope,
  modelCatalogApi,
  type ConversationModel,
} from "@/api/modules/modelCatalog";
import type { ModelSlotConfig } from "@/api/types/provider";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import sessionApi from "./sessionApi";

const scope = createSelectionScope();
export function resetConversationModelScope() {
  scope.reset();
}
export function currentModelContext(pathname = window.location.pathname) {
  const user = useAuthStore.getState().user?.id ?? "legacy";
  const agent = useAgentStore.getState().selectedAgent;
  const segment = pathname.match(/^\/chat\/([^/]+)/)?.[1];
  const localId = segment ? decodeURIComponent(segment) : undefined;
  const chat = localId
    ? sessionApi.getRealIdForSession(localId) ||
      (/^[0-9a-f-]{36}$/i.test(localId) ? localId : undefined)
    : undefined;
  const token = scope.enter(user, agent, chat ?? localId ?? "draft");
  return { user, agent, chat, token };
}
export function isCurrentModelContext(
  context: ReturnType<typeof currentModelContext>,
) {
  const current = currentModelContext();
  return current.token === context.token && scope.current(context.token);
}
export function draftModel() {
  const context = currentModelContext();
  return !context.chat ? scope.draft(context.token) : undefined;
}

function isMissingConversation(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  return (
    message.includes("chat not found") ||
    message.includes("conversation_not_found")
  );
}

export async function loadConversationModel(): Promise<ConversationModel> {
  const context = currentModelContext();
  const draft = scope.draft(context.token);
  if (!context.chat && draft) {
    const catalog = await modelCatalogApi.list(context.agent);
    const row = catalog.models.find(
      (m) => m.provider_id === draft.provider_id && m.model === draft.model,
    );
    if (!row) throw new Error("model_unavailable_or_forbidden");
    return {
      active_llm: draft,
      source: "draft",
      model_override: draft,
      locked: false,
      effective_max_input_length: row.max_input_length,
    };
  }
  if (!context.chat) return modelCatalogApi.default(context.agent);
  try {
    return await modelCatalogApi.current(context.chat);
  } catch (error) {
    // Agent switching updates the ownership scope synchronously, while the
    // router may still contain the previous Agent's chat UUID for one render.
    // Treat only that authoritative 404 as a draft for the newly selected
    // Agent; permission and catalog failures must remain visible.
    if (isMissingConversation(error)) {
      return modelCatalogApi.default(context.agent);
    }
    throw error;
  }
}
export async function chooseConversationModel(model: ModelSlotConfig | null) {
  const context = currentModelContext();
  let result: ConversationModel;
  if (context.chat) result = await modelCatalogApi.select(context.chat, model);
  else {
    scope.setDraft(context.token, model ?? undefined);
    result = await loadConversationModel();
  }
  if (isCurrentModelContext(context))
    window.dispatchEvent(
      new CustomEvent("model-switched", {
        detail: { maxInputLength: result.effective_max_input_length },
      }),
    );
  return result;
}
