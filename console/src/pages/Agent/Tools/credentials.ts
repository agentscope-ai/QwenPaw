import type {
  ToolConfigField,
  ToolConfigUpdate,
  ToolCredentialAction,
} from "../../../api/modules/tools";

export type CredentialActionKind = "keep" | "replace" | "delete";

export function buildToolConfigUpdate(
  fields: ToolConfigField[],
  values: Record<string, unknown>,
  actions: Record<string, CredentialActionKind>,
  replacements: Record<string, string>,
): ToolConfigUpdate {
  const config: Record<string, unknown> = {};
  const credential_updates: Record<string, ToolCredentialAction> = {};

  for (const field of fields) {
    if (field.type !== "password") {
      if (values[field.name] !== undefined)
        config[field.name] = values[field.name];
      continue;
    }
    const action = actions[field.name] ?? "keep";
    if (action === "replace") {
      const value = replacements[field.name]?.trim();
      if (!value) throw new Error(field.name);
      credential_updates[field.name] = { action, value };
    } else {
      credential_updates[field.name] = { action };
    }
  }
  return { config, credential_updates };
}
