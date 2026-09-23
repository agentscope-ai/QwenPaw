import { describe, expect, it } from "vitest";
import en from "./en.json";
import zh from "./zh.json";
import ja from "./ja.json";
import ru from "./ru.json";
import pt from "./pt-BR.json";
import id from "./id.json";
import vi from "./vi.json";

function leaves(value: object, prefix = ""): Record<string, string> {
  return Object.fromEntries(
    Object.entries(value).flatMap(([key, item]) => {
      const path = `${prefix}${key}`;
      return typeof item === "string"
        ? [[path, item]]
        : Object.entries(leaves(item, `${path}.`));
    }),
  );
}

describe("tool page translations", () => {
  const reference = leaves(en.tools);
  for (const [language, resource] of Object.entries({
    zh,
    ja,
    ru,
    pt,
    id,
    vi,
  })) {
    it(`${language} covers all tool strings and preserves placeholders`, () => {
      const translated = leaves(resource.tools);
      expect(Object.keys(translated).sort()).toEqual(
        Object.keys(reference).sort(),
      );
      for (const [key, value] of Object.entries(reference)) {
        expect(translated[key].trim(), key).not.toBe("");
        expect(
          translated[key].match(/\{\{.*?\}\}/g)?.sort() ?? [],
          key,
        ).toEqual(value.match(/\{\{.*?\}\}/g)?.sort() ?? []);
      }
      for (const [key, value] of Object.entries(resource.tools.catalog)) {
        expect(value.name, key).not.toBe(
          en.tools.catalog[key as keyof typeof en.tools.catalog].name,
        );
        expect(value.description, key).not.toBe(
          en.tools.catalog[key as keyof typeof en.tools.catalog].description,
        );
      }
    });
  }
});
