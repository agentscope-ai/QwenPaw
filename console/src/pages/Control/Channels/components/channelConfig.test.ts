import { describe, expect, it } from "vitest";
import { keepConsoleEnabled } from "./channelConfig";

describe("keepConsoleEnabled", () => {
  it("forces the console channel to stay enabled", () => {
    expect(keepConsoleEnabled("console", { enabled: false })).toEqual({
      enabled: true,
    });
  });

  it("leaves other channel configs unchanged", () => {
    const config = { enabled: false };

    expect(keepConsoleEnabled("discord", config)).toBe(config);
  });
});
