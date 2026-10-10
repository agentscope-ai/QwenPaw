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
  "liveSettings",
  "customSettings",
  "readonlySettings",
  "readonlyReason.startup",
  "readonlyReason.initial_default",
  "variableDescriptions.QWENPAW_LLM_STREAM_FIRST_CONTENT_TIMEOUT",
  "variableDescriptions.QWENPAW_LLM_STREAM_IDLE_TIMEOUT",
];

function readPath(value: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, segment) => {
    if (typeof current !== "object" || current === null) return undefined;
    return (current as Record<string, unknown>)[segment];
  }, value);
}

describe("environment page locales", () => {
  it.each(Object.entries(locales))(
    "%s contains every environment-management message",
    (_language, locale) => {
      for (const path of requiredPaths) {
        expect(readPath(locale.environments, path), path).toBeTruthy();
      }
    },
  );
});
