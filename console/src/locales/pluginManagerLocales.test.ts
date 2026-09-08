import { describe, expect, it } from "vitest";

import en from "./en.json";
import id from "./id.json";
import ja from "./ja.json";
import ptBR from "./pt-BR.json";
import ru from "./ru.json";
import vi from "./vi.json";
import zh from "./zh.json";

const locales = { en, id, ja, "pt-BR": ptBR, ru, vi, zh };

const requiredKeys = [
  "update",
  "updateAll",
  "updateSuccess",
  "updateAllSuccess",
  "updateAllResult",
  "updateFailed",
  "checkingUpdates",
  "catalogVersion",
  "catalogCurrentVersion",
] as const;

function interpolationKeys(value: string): string[] {
  return Array.from(value.matchAll(/{{(\w+)}}/g), (match) => match[1]).sort();
}

describe("plugin manager locale coverage", () => {
  it.each(Object.entries(locales))(
    "%s contains every update message",
    (_language, locale) => {
      for (const key of requiredKeys) {
        expect(locale.pluginManager[key], key).toBeTruthy();
      }
    },
  );

  it.each(Object.entries(locales))(
    "%s keeps batch-result interpolation consistent",
    (_language, locale) => {
      expect(interpolationKeys(locale.pluginManager.updateAllResult)).toEqual(
        interpolationKeys(en.pluginManager.updateAllResult),
      );
    },
  );
});
