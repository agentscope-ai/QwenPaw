import { describe, it, expect } from "vitest";
import { extractText } from "./useChatMessages";
import type { MessageContent } from "../types";

describe("extractText", () => {
  it("extracts text from text content blocks", () => {
    const content: MessageContent[] = [
      { type: "text", text: "Hello" },
      { type: "text", text: "World" },
    ];
    expect(extractText(content)).toBe("Hello\nWorld");
  });

  it("ignores non-text content blocks", () => {
    const content: MessageContent[] = [
      { type: "text", text: "Hello" },
      { type: "image", url: "http://example.com/img.png" },
      { type: "text", text: "World" },
    ];
    expect(extractText(content)).toBe("Hello\nWorld");
  });

  it("returns empty string for empty array", () => {
    expect(extractText([])).toBe("");
  });

  it("returns empty string when no text content exists", () => {
    const content: MessageContent[] = [
      { type: "image", url: "http://example.com/img.png" },
      { type: "video", url: "http://example.com/video.mp4" },
    ];
    expect(extractText(content)).toBe("");
  });
});
