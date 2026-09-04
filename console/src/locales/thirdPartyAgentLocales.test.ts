import { describe, expect, it } from "vitest";

import en from "./en.json";
import id from "./id.json";
import ja from "./ja.json";
import ptBR from "./pt-BR.json";
import ru from "./ru.json";
import vi from "./vi.json";
import zh from "./zh.json";

const locales = { en, id, ja, "pt-BR": ptBR, ru, vi, zh };

const requiredPaths = [
  "common.saving",
  "harnesses.connected",
  "harnesses.disconnected",
  "harnesses.notConnected",
  "harnesses.comingSoon",
  "harnesses.connect",
  "harnesses.disconnect",
  "harnesses.apiKeyAuthenticated",
  "harnesses.chatGptAuthenticated",
  "harnesses.cliAuthenticated",
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
  "agent.backend.codexHint",
  "agent.backend.qoderHint",
  "agent.backend.account",
  "agent.backend.qoderAccount",
  "agent.backend.binary",
  "agent.backend.binaryHelp",
  "agent.backend.binaryPlaceholder",
  "agent.backend.qoderBinary",
  "agent.backend.qoderBinaryHelp",
  "agent.backend.qoderBinaryPlaceholder",
  "agent.backend.detect",
  "agent.backend.detectedBinary",
  "agent.backend.qoderDetectedBinary",
  "agent.backend.apiKeyLoginHint",
  "agent.backend.qoderAuthHint",
  "agent.backend.qoderConnect",
  "agent.backend.model",
  "agent.backend.modelDefault",
  "agent.backend.defaultBadge",
  "agent.backend.reasoningEffort",
  "agent.backend.reasoningDefault",
  "agent.backend.codexNotFound",
  "agent.backend.qoderNotFound",
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
  "agent.backend.approvalPresets.ask.name",
  "agent.backend.approvalPresets.ask.description",
  "agent.backend.approvalPresets.read-only.name",
  "agent.backend.approvalPresets.read-only.description",
  "agent.backend.approvalPresets.workspace.name",
  "agent.backend.approvalPresets.workspace.description",
  "agent.backend.approvalPresets.accept-edits.name",
  "agent.backend.approvalPresets.accept-edits.description",
  "agent.backend.approvalPresets.plan.name",
  "agent.backend.approvalPresets.plan.description",
  "agent.backend.approvalPresets.auto.name",
  "agent.backend.approvalPresets.auto.description",
  "agent.backend.approvalPresets.full-access.name",
  "agent.backend.approvalPresets.full-access.description",
  "chat.commands.agents.description",
  "chat.commands.review.description",
  "chat.commands.status.description",
  "agentConfig.powercontextMemoryTitle",
  "agentConfig.powercontextConfig.title",
  "agentConfig.powercontextConfig.baseUrl",
  "agentConfig.powercontextConfig.token",
  "agentConfig.powercontextConfig.scopeId",
  "agentConfig.powercontextConfig.scopeIdPlaceholder",
  "agentConfig.powercontextConfig.scopeIdInvalid",
  "agentConfig.powercontextConfig.timeout",
  "agentConfig.powercontextConfig.maxContextBytes",
  "agentConfig.powercontextConfig.maxContextBytesTooltip",
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

  it.each(Object.entries(locales))(
    "%s derives the authenticated CLI name from the agent type",
    (_localeName, locale) => {
      expect(
        String(getTranslation(locale, "harnesses.cliAuthenticated")),
      ).toContain("{{type}} CLI");
    },
  );
});
