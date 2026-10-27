import { describe, expect, it } from "vitest";

import { isSafeCssColor, toChatThemeHex } from "./chatThemeColor";

describe("isSafeCssColor", () => {
  it("accepts the color syntaxes supported by the theme API", () => {
    expect(isSafeCssColor("#abc")).toBe(true);
    expect(isSafeCssColor("rgba(255, 127, 22, 0.1)")).toBe(true);
    expect(isSafeCssColor("hsl(30 100% 50% / 25%)")).toBe(true);
  });

  it("rejects incomplete values and external resource URLs", () => {
    expect(isSafeCssColor("#12345")).toBe(false);
    expect(isSafeCssColor("rgb(1")).toBe(false);
    expect(isSafeCssColor("url(https://example.com/image.png)")).toBe(false);
  });
});

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
