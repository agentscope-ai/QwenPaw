import type {
  MCPCredentialUpdates,
  MCPSecretAction,
} from "../../../api/types";

export type CredentialDraftAction = MCPSecretAction["action"];
export interface CredentialDraftField {
  action: CredentialDraftAction;
  value: string;
}
export interface CredentialDraft {
  headers: Record<string, CredentialDraftField>;
  env: Record<string, CredentialDraftField>;
}

export function createCredentialDraft(fields?: {
  headers: string[];
  env: string[];
}): CredentialDraft {
  const entries = (names: string[]) =>
    Object.fromEntries(
      names.map((name) => [name, { action: "keep" as const, value: "" }]),
    );
  return {
    headers: entries(fields?.headers ?? []),
    env: entries(fields?.env ?? []),
  };
}

export function buildCredentialUpdates(
  draft: CredentialDraft,
): MCPCredentialUpdates {
  const build = (fields: Record<string, CredentialDraftField>) =>
    Object.fromEntries(
      Object.entries(fields).map(([name, field]) => {
        if (field.action === "replace") {
          if (!field.value) {
            throw new Error("credential replacement requires a value");
          }
          return [name, { action: "replace" as const, value: field.value }];
        }
        return [name, { action: field.action }];
      }),
    );
  return { headers: build(draft.headers), env: build(draft.env) };
}
