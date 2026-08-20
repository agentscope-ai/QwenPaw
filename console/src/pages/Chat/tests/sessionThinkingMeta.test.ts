import { describe, expect, it } from "vitest";

import sessionApi from "../sessionApi";

describe("SessionApi thinking metadata", () => {
  it("rejects unsupported thinking levels", async () => {
    await expect(
      sessionApi.updateSessionMeta("chat-1", {
        thinking_level: "invalid",
      }),
    ).rejects.toThrow("Invalid session thinking level");
  });
});
