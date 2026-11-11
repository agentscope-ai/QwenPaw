import { describe, it, expect } from "vitest";
import {
  CUSTOM_ANIMATED_EMOJI_URLS,
  CUSTOM_EMOJI_URLS,
  customEmojiSrc,
  isAnimatedEmoji,
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
  it("renders any alicdn emoji, static PNG or animated GIF", () => {
    const gif = CUSTOM_ANIMATED_EMOJI_URLS[0];
    expect(isCustomEmoji(gif)).toBe(true);
    expect(isAnimatedEmoji(gif)).toBe(true);
    expect(customEmojiSrc(gif)).toBe(gif);
    expect(markdownWithCustomEmoji(`[emoji:${gif}]`)).toBe(
      `![emoji](<${gif}>)`,
    );
    // Static PNG stickers stay non-animated (rendered at the smaller size).
    expect(isAnimatedEmoji(CUSTOM_EMOJI_URLS[0])).toBe(false);
  });
  it("accepts unlisted alicdn stickers so future Platform emoji render", () => {
    const unlisted =
      "https://img.alicdn.com/imgextra/i1/O1CN01ABCDEFGHIJ1234567890_!!6000000000000-2-tps-150-150.png";
    expect(customEmojiSrc(unlisted)).toBe(unlisted);
    expect(customEmojiSrc("https://img.alicdn.com/whatever.gif")).toBe(
      "https://img.alicdn.com/whatever.gif",
    );
  });
  it("does not convert unknown or unsafe image sources", () => {
    for (const url of [
      "javascript:alert(1)",
      "https://example.com/a.png",
      // Host-prefix lookalikes must not slip through the alicdn check.
      "https://img.alicdn.com.evil.com/a.png",
      "https://img.alicdn.com@evil.com/a.png",
    ]) {
      expect(markdownWithCustomEmoji(`[emoji:${url}]`)).toBe(`[emoji:${url}]`);
      expect(isCustomEmoji(url)).toBe(false);
      expect(customEmojiSrc(url)).toBeNull();
    }
  });
  it("rejects alicdn tokens that could escape the markdown image wrapper", () => {
    const injection =
      "https://img.alicdn.com/x.png> free gift https://evil.example.com";
    expect(customEmojiSrc(injection)).toBeNull();
    expect(markdownWithCustomEmoji(`[emoji:${injection}]`)).toBe(
      `[emoji:${injection}]`,
    );
    expect(customEmojiSrc("https://img.alicdn.com/a b.png")).toBeNull();
    expect(customEmojiSrc("https://img.alicdn.com/a(b).png")).toBeNull();
  });
  it("offers picker animated GIFs that all render as large emoji", () => {
    expect(CUSTOM_ANIMATED_EMOJI_URLS).toHaveLength(16);
    for (const gif of CUSTOM_ANIMATED_EMOJI_URLS) {
      expect(customEmojiSrc(gif)).toBe(gif);
      expect(isCustomEmoji(gif)).toBe(true);
      expect(isAnimatedEmoji(gif)).toBe(true);
      expect(markdownWithCustomEmoji(`[emoji:${gif}]`)).toBe(
        `![emoji](<${gif}>)`,
      );
    }
  });
});
