import { describe, expect, it } from "vitest";

import { resolveLocalizedText } from "./resolveLocalizedText";

describe("resolveLocalizedText", () => {
  const dict = {
    en: "English",
    "zh-CN": "中文",
  };

  it("returns empty for nullish", () => {
    expect(resolveLocalizedText(null, "zh")).toBe("");
    expect(resolveLocalizedText(undefined, "en")).toBe("");
  });

  it("returns plain strings as-is", () => {
    expect(resolveLocalizedText("plain", "zh")).toBe("plain");
  });

  it("matches short UI lang to long dict key", () => {
    expect(resolveLocalizedText(dict, "zh")).toBe("中文");
  });

  it("matches exact locale", () => {
    expect(resolveLocalizedText(dict, "zh-CN")).toBe("中文");
    expect(resolveLocalizedText(dict, "en")).toBe("English");
  });

  it("falls back to English when locale missing", () => {
    expect(resolveLocalizedText(dict, "ja")).toBe("English");
  });
});
