import { describe, expect, it } from "vitest";

import { toChatThemeHex } from "./chatThemeColor";

describe("toChatThemeHex", () => {
  it("keeps six-digit hex values", () => {
    expect(toChatThemeHex("#0b57d0", "#ff7f16")).toBe("#0b57d0");
  });

  it("expands short hex values and drops alpha", () => {
    expect(toChatThemeHex("#abc", "#ff7f16")).toBe("#aabbcc");
    expect(toChatThemeHex("#abcd", "#ff7f16")).toBe("#aabbcc");
    expect(toChatThemeHex("#11223380", "#ff7f16")).toBe("#112233");
  });

  it("converts rgb and hsl values", () => {
    expect(toChatThemeHex("rgb(11, 87, 208)", "#ff7f16")).toBe("#0b57d0");
    expect(toChatThemeHex("hsl(0, 100%, 50%)", "#ff7f16")).toBe("#ff0000");
  });

  it("falls back for CSS variables and invalid colors", () => {
    expect(toChatThemeHex("var(--app-accent)", "#ff7f16")).toBe("#ff7f16");
    expect(toChatThemeHex("url(javascript:alert(1))", "#ff7f16")).toBe(
      "#ff7f16",
    );
  });
});
