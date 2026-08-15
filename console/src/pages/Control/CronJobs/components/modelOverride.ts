import type { ProviderInfo } from "../../../../api/types";

export type ModelOverrideOption = { value: string; label: string };

/**
 * The backend accepts `request.model_slot_override` on cron jobs either as a
 * `{provider_id, model}` dict or as a "<provider_id>:<model>" string. The
 * model name itself may contain ":" (only the first one separates), so the
 * string form is unambiguous and is what this UI uses.
 */
export function buildModelOverrideOptions(
  providers: ProviderInfo[] | null | undefined,
): ModelOverrideOption[] {
  const options: ModelOverrideOption[] = [];
  for (const provider of providers || []) {
    if (!provider?.id) continue;
    const seen = new Set<string>();
    const models = [
      ...(provider.models || []),
      ...(provider.extra_models || []),
    ];
    for (const model of models) {
      if (!model?.id || seen.has(model.id)) continue;
      seen.add(model.id);
      options.push({
        value: `${provider.id}:${model.id}`,
        label: `${provider.name || provider.id} / ${model.name || model.id}`,
      });
    }
  }
  return options.sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * Normalize the form value of `request.model_slot_override` before submit.
 * Mutates `request` in place: writes a trimmed "<provider_id>:<model>"
 * string, or removes the key entirely when empty (meaning: follow the
 * agent's active model).
 */
export function applyModelOverrideToRequest(
  request: Record<string, unknown> | undefined,
  value: unknown,
): void {
  if (!request) return;
  const normalized = modelOverrideToFormValue(value);
  if (normalized) {
    request.model_slot_override = normalized;
  } else {
    delete request.model_slot_override;
  }
}

/**
 * Normalize a persisted `model_slot_override` (string or dict) into the
 * "<provider_id>:<model>" string used by the form select. Returns undefined
 * when there is no usable override.
 */
export function modelOverrideToFormValue(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (value && typeof value === "object") {
    const dict = value as { provider_id?: unknown; model?: unknown };
    if (
      typeof dict.provider_id === "string" &&
      dict.provider_id.trim() &&
      typeof dict.model === "string" &&
      dict.model.trim()
    ) {
      return `${dict.provider_id.trim()}:${dict.model.trim()}`;
    }
  }
  return undefined;
}
