import { describe, expect, it } from "vitest";

import en from "./en.json";
import zh from "./zh.json";

const requiredPaths = [
  "chat.modelFallbackNotice",
  "models.addAllDiscoveredModels",
  "models.discoveredModelsAdded",
  "models.discoveredModelsAddFailed",
] as const;

function getTranslation(locale: Record<string, unknown>, path: string): string {
  const value = path.split(".").reduce<unknown>((current, key) => {
    if (typeof current !== "object" || current === null) {
      return undefined;
    }
    return (current as Record<string, unknown>)[key];
  }, locale);
  return typeof value === "string" ? value : "";
}

function interpolationKeys(value: string): string[] {
  return Array.from(value.matchAll(/{{(\w+)}}/g), (match) => match[1]).sort();
}

describe("provider platform locale coverage", () => {
  it.each(requiredPaths)("provides Chinese text for %s", (path) => {
    const translation = getTranslation(zh, path);

    expect(translation).not.toBe("");
    expect(translation).toMatch(/[\u3400-\u9fff]/u);
  });

  it.each(requiredPaths)("keeps interpolation parity for %s", (path) => {
    expect(interpolationKeys(getTranslation(zh, path))).toEqual(
      interpolationKeys(getTranslation(en, path)),
    );
  });
});
