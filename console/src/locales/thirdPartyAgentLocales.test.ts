import { describe, expect, it } from "vitest";

import id from "./id.json";
import ja from "./ja.json";
import ptBR from "./pt-BR.json";
import ru from "./ru.json";
import vi from "./vi.json";

const locales = { id, ja, "pt-BR": ptBR, ru, vi };

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
});
