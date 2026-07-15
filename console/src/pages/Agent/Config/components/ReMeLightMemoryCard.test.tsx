import { describe, expect, it } from "vitest";

import { isEmbeddingEnabled } from "./ReMeLightMemoryCard";

describe("isEmbeddingEnabled", () => {
  it("requires model name for every backend", () => {
    expect(isEmbeddingEnabled("openai", "", "key")).toBe(false);
    expect(isEmbeddingEnabled("ollama", "   ", undefined)).toBe(false);
  });

  it("requires api key for OpenAI-compatible backends", () => {
    expect(isEmbeddingEnabled("openai", "text-embedding-3-small", "")).toBe(
      false,
    );
    expect(isEmbeddingEnabled("dashscope", "text-embedding-v3", "key")).toBe(
      true,
    );
    expect(
      isEmbeddingEnabled("dashscope_multimodal", "multimodal-embedding", "key"),
    ).toBe(true);
  });

  it("requires api key for gemini", () => {
    expect(isEmbeddingEnabled("gemini", "gemini-embedding-001", "")).toBe(
      false,
    );
    expect(isEmbeddingEnabled("gemini", "gemini-embedding-001", "key")).toBe(
      true,
    );
  });

  it("enables ollama with a model name and no api key", () => {
    expect(isEmbeddingEnabled("ollama", "nomic-embed-text", undefined)).toBe(
      true,
    );
  });

  it("disables unknown backends", () => {
    expect(isEmbeddingEnabled("unknown", "embedding-model", "key")).toBe(false);
  });
});
