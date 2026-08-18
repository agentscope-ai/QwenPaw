import { describe, expect, it } from "vitest";

import en from "./en.json";
import zh from "./zh.json";

type LocaleSection = Record<string, unknown>;

function leafPaths(section: LocaleSection, prefix = ""): string[] {
  return Object.entries(section).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") {
      return [path];
    }
    if (typeof value === "object" && value !== null) {
      return leafPaths(value as LocaleSection, path);
    }
    return [];
  });
}

function getTranslation(section: LocaleSection, path: string): string {
  const value = path.split(".").reduce<unknown>((current, key) => {
    if (typeof current !== "object" || current === null) {
      return undefined;
    }
    return (current as LocaleSection)[key];
  }, section);
  return typeof value === "string" ? value : "";
}

function interpolationKeys(value: string): string[] {
  return Array.from(value.matchAll(/{{(\w+)}}/g), (match) => match[1]).sort();
}

describe("Pro locale coverage", () => {
  const english = en.pro as LocaleSection;
  const chinese = zh.pro as LocaleSection;
  const paths = leafPaths(english).sort();

  it("keeps English and Chinese translation keys aligned", () => {
    expect(leafPaths(chinese).sort()).toEqual(paths);
  });

  it.each(paths)(
    "provides Chinese text and interpolation parity for %s",
    (path) => {
      const englishValue = getTranslation(english, path);
      const chineseValue = getTranslation(chinese, path);

      expect(chineseValue).not.toBe("");
      expect(interpolationKeys(chineseValue)).toEqual(
        interpolationKeys(englishValue),
      );
    },
  );

  it.each(["returnToSignIn", "createAccount"])("localizes login.%s", (key) => {
    expect(en.login[key as keyof typeof en.login]).not.toBe("");
    expect(zh.login[key as keyof typeof zh.login]).not.toBe("");
  });
});
