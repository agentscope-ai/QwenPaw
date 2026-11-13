import { describe, expect, it } from "vitest";

import en from "./en.json";
import id from "./id.json";
import ja from "./ja.json";
import ptBR from "./pt-BR.json";
import ru from "./ru.json";
import vi from "./vi.json";
import zh from "./zh.json";
// Keep the plugins' separate TypeScript dependency trees out of Console builds.
const pluginLocales = import.meta.glob<{
  localMessages(locale: string): Record<string, string>;
}>("../../../plugins/harness/*/frontend/src/locale.ts", { eager: true });
const [codexMessages, qoderMessages] = ["codex", "qoder"].map(
  (backend) =>
    pluginLocales[`../../../plugins/harness/${backend}/frontend/src/locale.ts`]
      .localMessages,
);

const locales = { en, id, ja, "pt-BR": ptBR, ru, vi, zh };

const requiredPaths = [
  "common.saving",
  "mcp.qwenpawManaged",
  "mcp.qwenpawManagedHint",
  "mcp.providerManaged",
  "mcp.providerManagedHint",
  "mcp.providerOnly",
  "mcp.readOnly",
  "skills.qwenpawManaged",
  "skills.qwenpawManagedHint",
  "skills.providerManaged",
  "skills.providerManagedHint",
  "skills.providerOnly",
  "skills.readOnly",
  "skills.noDescription",
  "skills.providerSkillDetails",
  "skills.providerManagedDetailHint",
  "skills.provider",
  "skills.source",
  "skills.scope",
  "skills.statusLabel",
  "skills.descriptionLabel",
  "agent.backend.column",
  "agent.backend.eyebrow",
  "agent.backend.typeTitle",
  "agent.backend.typeDescription",
  "agent.backend.nativeTitle",
  "agent.backend.nativeBadge",
  "agent.backend.nativeDescription",
  "agent.backend.thirdPartyTitle",
  "agent.backend.thirdPartyBadge",
  "agent.backend.thirdPartyDescription",
  "agent.backend.providerTitle",
  "agent.backend.providerDescription",
  "agent.backend.detect",
  "agent.backend.model",
  "agent.backend.modelDefault",
  "agent.backend.defaultBadge",
  "agent.backend.reasoningEffort",
  "agent.backend.reasoningDefault",
  "agent.backend.chatSettingsHint",
  "agent.backend.capabilityTitle",
  "agent.backend.inheritedSkills",
  "agent.backend.inheritedMcp",
  "agent.backend.runtimeInherited",
  "agent.backend.notSupported",
  "agent.backend.policyCompatibility",
  "agent.backend.toolAllowlistSupported",
  "agent.backend.policyLimited",
  "agent.backend.chatModelHint",
  "agent.backend.appliesNextTurn",
  "agent.backend.approvalMode",
  "chat.commands.agents.description",
  "chat.commands.review.description",
  "chat.commands.status.description",
] as const;

const thirdPartyAgentTerminologyPaths = [
  "skills.providerManaged",
  "skills.providerManagedHint",
  "skills.providerOnly",
  "skills.providerSkillDetails",
  "skills.providerManagedDetailHint",
  "skills.provider",
  "mcp.providerManagedHint",
  "mcp.providerOnly",
] as const;

function getTranslation(
  locale: Record<string, unknown>,
  path: string,
): unknown {
  return path.split(".").reduce<unknown>((value, key) => {
    if (typeof value !== "object" || value === null) {
      return undefined;
    }
    return (value as Record<string, unknown>)[key];
  }, locale);
}

describe("third-party agent locale coverage", () => {
  it.each(Object.entries(locales))(
    "%s includes every required translation",
    (_localeName, locale) => {
      for (const path of requiredPaths) {
        expect(getTranslation(locale, path), path).toBeTypeOf("string");
        expect(getTranslation(locale, path), path).not.toBe("");
      }
    },
  );

  it.each(Object.entries(locales))(
    "%s avoids model Provider terminology for third-party agents",
    (_localeName, locale) => {
      for (const path of thirdPartyAgentTerminologyPaths) {
        expect(String(getTranslation(locale, path)), path).not.toMatch(
          /\bprovider\b/i,
        );
      }
    },
  );

  it.each(Object.keys(locales))(
    "%s keeps vendor account and executable copy in each plugin",
    (localeName) => {
      for (const messages of [
        codexMessages(localeName),
        qoderMessages(localeName),
      ]) {
        for (const key of [
          "hint",
          "account",
          "binary",
          "binaryHelp",
          "binaryPlaceholder",
          "detected",
          "notFound",
          "authHint",
          "connect",
          "connected",
          "disconnected",
          "apiKeyAuthenticated",
          "cliAuthenticated",
        ] as const) {
          expect(messages[key], `${localeName}.${key}`).toBeTruthy();
        }
        expect(messages.cliAuthenticated).toContain("{{type}} CLI");
      }
    },
  );
});
