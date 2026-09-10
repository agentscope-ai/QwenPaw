import type {
  LoopModeInfo,
  ModelInfo,
  ProviderInfo,
} from "../../api/types";

export const DEFAULT_LOOP_MODE: LoopModeInfo = {
  id: "default",
  name: "默认",
  slash_command: "",
  description: "生成一轮回复后停止。",
  source: "builtin",
};

export interface SelectableProvider {
  id: string;
  name: string;
  models: ModelInfo[];
}

export function selectableProviders(
  providers: ProviderInfo[],
): SelectableProvider[] {
  return providers.flatMap((provider) => {
    const hidden = new Set(provider.hidden_model_ids ?? []);
    const availableModels = [
      ...(provider.models ?? []),
      ...(provider.extra_models ?? []),
    ]
      .filter((model, index, all) =>
        !hidden.has(model.id) &&
        all.findIndex((candidate) => candidate.id === model.id) === index)
      .filter((model) => model.id);
    const hasBaseUrl = Boolean(provider.base_url?.trim());
    const configured = provider.is_custom || provider.is_local ||
      provider.require_api_key === false
      ? hasBaseUrl
      : Boolean(provider.api_key) || Boolean(provider.oauth_connected);
    const models = configured ? availableModels : [];
    if (models.length === 0) return [];
    return [{ id: provider.id, name: provider.name, models }];
  });
}

export function normalizeLoopModes(modes: LoopModeInfo[]): LoopModeInfo[] {
  const values = modes.some((mode) => mode.id === DEFAULT_LOOP_MODE.id)
    ? modes
    : [DEFAULT_LOOP_MODE, ...modes];
  const seen = new Set<string>();
  return values.filter((mode) => {
    if (!mode.id || seen.has(mode.id)) return false;
    seen.add(mode.id);
    return true;
  });
}

export function applyLoopModeCommand(text: string, mode: LoopModeInfo): string {
  const command = mode.slash_command.trim();
  if (!command) return text;
  const trimmed = text.trimStart();
  if (trimmed.startsWith("/")) return text;
  return `/${command} ${text}`;
}
