import { describe, expect, it } from "vitest";
import {
  resolveLocale,
  t,
  type MessageKey,
  type DecisionKey,
} from "../../../../plugins/bundle/computer-use/frontend/src/locale";

const keys: (MessageKey | DecisionKey)[] = [
  "routeLabel",
  "title",
  "ready",
  "unavailable",
  "refresh",
  "stop",
  "feature",
  "enabledMsg",
  "disabledMsg",
  "application",
  "applicationId",
  "revoke",
  "revokeConfirm",
  "revokeHint",
  "cancel",
  "empty",
  "approvalTitle",
  "unknownApplication",
  "risk",
  "deny",
  "allowSession",
  "allowAlways",
  "approvalHint",
  "persistentHint",
  "submitting",
  "waiting",
  "expired",
  "unavailableRequest",
  "submitUnconfirmed",
  "submitRejected",
  "failed",
  "accessManagement",
  "version",
  "decision.deny",
  "decision.session",
  "decision.always",
];

describe("computer-use translations", () => {
  it.each([
    ["en-US", "en"],
    ["zh-CN", "zh"],
    ["zh-TW", "zh"],
    ["ja-JP", "ja"],
    ["ru-RU", "ru"],
    ["pt-BR", "pt-BR"],
    ["PT-br", "pt-BR"],
    ["pt", "pt-BR"],
    ["id-ID", "id"],
    ["vi-VN", "vi"],
    ["unknown", "en"],
    [null, "en"],
    [undefined, "en"],
  ])("resolves %s to %s", (input, expected) => {
    expect(resolveLocale(input)).toBe(expected);
  });

  it.each(["en", "zh", "ja", "ru", "pt-BR", "id", "vi"])(
    "provides every plugin string in %s without fallback",
    (language) => {
      const selected = resolveLocale(language);
      for (const key of keys) {
        const value = t(selected, key);
        expect(typeof value, `${language}: ${key}`).toBe("string");
        expect(value.trim(), `${language}: ${key}`).not.toBe("");
        if (selected !== "en") {
          expect(value, `${language}: ${key}`).not.toBe(t("en", key));
        }
      }
    },
  );
});
