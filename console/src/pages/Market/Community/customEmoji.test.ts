import { describe, it, expect } from "vitest";
import {
  CUSTOM_EMOJI_URLS,
  isCustomEmoji,
  markdownWithCustomEmoji,
} from "./customEmoji";
describe("Platform comment emoji", () => {
  it("converts every supported custom emoji and preserves Unicode and text", () => {
    const input = `Hello 😎 ${CUSTOM_EMOJI_URLS.map(
      (url) => `[emoji:${url}]`,
    ).join(" ")} bye`;
    const result = markdownWithCustomEmoji(input);
    expect(result.match(/!\[emoji\]/g)).toHaveLength(CUSTOM_EMOJI_URLS.length);
    expect(result).toContain("Hello 😎");
    expect(result).toContain("bye");
    expect(result).not.toContain("[emoji:https:");
  });
  it("does not convert unknown or unsafe image sources", () => {
    for (const url of [
      "javascript:alert(1)",
      "https://example.com/a.png",
      "https://img.alicdn.com/unlisted.png",
    ]) {
      expect(markdownWithCustomEmoji(`[emoji:${url}]`)).toBe(`[emoji:${url}]`);
      expect(isCustomEmoji(url)).toBe(false);
    }
  });
});
