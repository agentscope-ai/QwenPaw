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
  it("falls back to the zh key when only zh is present", () => {
    // Neither en-US nor en exists, so the English fallback arm is skipped and
    // the Chinese fallback must reach its second operand (dict.zh).
    const zhOnly = { zh: "\u4e2d\u6587", fr: "Bonjour" };
    expect(resolveLocalizedText(zhOnly, "ja")).toBe("\u4e2d\u6587");
  });

  it("falls back to zh-CN when only the long Chinese key is present", () => {
    const zhLong = { "zh-CN": "\u4e2d\u6587", fr: "Bonjour" };
    expect(resolveLocalizedText(zhLong, "ja")).toBe("\u4e2d\u6587");
  });

  it("falls back to the first non-empty value when no locale matches", () => {
    // No exact, short, prefix, English or Chinese candidate at all, so the
    // last-resort scan over the values decides.
    expect(resolveLocalizedText({ fr: "Bonjour" }, "ja")).toBe("Bonjour");
  });

  it("skips a prefix-matching key whose value is empty", () => {
    // The prefix scan requires a truthy value, so the empty zh-CN entry must
    // not win over the populated zh entry.
    const withEmpty = { "zh-CN": "", zh: "\u5907\u7528" };
    expect(resolveLocalizedText(withEmpty, "zh-TW")).toBe("\u5907\u7528");
  });

  it("returns empty when every value is empty", () => {
    expect(resolveLocalizedText({ fr: "", de: "" }, "ja")).toBe("");
  });

  it("returns empty for an empty dictionary", () => {
    expect(resolveLocalizedText({}, "ja")).toBe("");
  });
});

describe("resolveLocalizedText - non-dictionary inputs", () => {
  it("coerces a number to its string form", () => {
    expect(resolveLocalizedText(42, "zh")).toBe("42");
  });

  it("coerces a boolean to its string form", () => {
    expect(resolveLocalizedText(true, "zh")).toBe("true");
  });

  it("coerces zero instead of treating it as nullish", () => {
    // Only null and undefined short-circuit to the empty string; zero must go
    // through String(value).
    expect(resolveLocalizedText(0, "zh")).toBe("0");
  });

  it("keeps the empty string input as the empty string", () => {
    expect(resolveLocalizedText("", "zh")).toBe("");
  });

  it("defaults to English when the UI lang is an empty string", () => {
    // The locale defaults to en, so the exact match on the en key wins and the
    // later fallbacks are never consulted.
    expect(
      resolveLocalizedText({ en: "English", "zh-CN": "\u4e2d\u6587" }, ""),
    ).toBe("English");
  });

  it("defaults to English for an empty lang when there is no en key", () => {
    // Locale becomes en but nothing matches it, so the Chinese fallback still
    // has to carry the result.
    expect(resolveLocalizedText({ "zh-CN": "\u4e2d\u6587" }, "")).toBe(
      "\u4e2d\u6587",
    );
  });
});
