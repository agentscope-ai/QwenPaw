import { describe, expect, it } from "vitest";

import en from "./en.json";
import id from "./id.json";
import ja from "./ja.json";
import ptBR from "./pt-BR.json";
import ru from "./ru.json";
import vi from "./vi.json";
import zh from "./zh.json";

const locales = { en, id, ja, "pt-BR": ptBR, ru, vi, zh };

function leafPaths(value: unknown, prefix = ""): string[] {
  if (typeof value === "string") {
    return [prefix];
  }
  if (typeof value !== "object" || value === null) {
    return [];
  }
  return Object.entries(value).flatMap(([key, child]) =>
    leafPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

function getTranslation(value: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, key) => {
    if (typeof current !== "object" || current === null) {
      return undefined;
    }
    return (current as Record<string, unknown>)[key];
  }, value);
}

function interpolationKeys(value: string): string[] {
  return Array.from(value.matchAll(/{{(\w+)}}/g), (match) => match[1]).sort();
}

describe("Hub locale coverage", () => {
  const requiredPaths = leafPaths(en.hub).sort();

  it.each(Object.entries(locales))(
    "%s includes every Hub translation",
    (_localeName, locale) => {
      expect(leafPaths(locale.hub).sort()).toEqual(requiredPaths);
    },
  );

  it.each(Object.entries(locales))(
    "%s keeps Hub interpolation variables",
    (_localeName, locale) => {
      for (const path of requiredPaths) {
        const source = String(getTranslation(en.hub, path));
        const translation = String(getTranslation(locale.hub, path));

        expect(interpolationKeys(translation), path).toEqual(
          interpolationKeys(source),
        );
      }
    },
  );
});
