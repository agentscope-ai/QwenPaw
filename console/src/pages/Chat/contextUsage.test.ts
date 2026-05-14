import { describe, expect, it } from "vitest";
import {
  contextUsageLevel,
  formatContextTokens,
  parseContextUsage,
} from "./contextUsage";

describe("context usage helpers", () => {
  it("parses structured context usage payloads", () => {
    expect(
      parseContextUsage({
        context_usage: {
          total_tokens: 3200,
          max_input_length: 128000,
          pct: 2.5,
          total_messages: 7,
        },
      }),
    ).toEqual({
      totalTokens: 3200,
      maxInputLength: 128000,
      pct: 2.5,
      totalMessages: 7,
    });
  });

  it("ignores incomplete payloads", () => {
    expect(
      parseContextUsage({ context_usage: { total_tokens: 1 } }),
    ).toBeNull();
    expect(parseContextUsage({})).toBeNull();
  });

  it("formats token counts and classifies usage levels", () => {
    expect(formatContextTokens(999)).toBe("999");
    expect(formatContextTokens(3200)).toBe("3.2k");
    expect(contextUsageLevel(20)).toBe("normal");
    expect(contextUsageLevel(50)).toBe("warning");
    expect(contextUsageLevel(70)).toBe("danger");
  });
});
