import { describe, expect, it } from "vitest";
import { withMentionPayload } from "./mentionPayload";

describe("withMentionPayload", () => {
  it("adds serializable mentions without mutating the original payload", () => {
    const payload = { input: [], stream: true };
    const result = withMentionPayload(payload, [
      { value: "src/app.ts", type: "file" },
    ]);

    expect(result).toEqual({
      input: [],
      stream: true,
      mentions: [{ value: "src/app.ts", type: "file" }],
    });
    expect(payload).toEqual({ input: [], stream: true });
  });

  it("does not add an empty mentions field", () => {
    expect(withMentionPayload({ stream: true }, [])).toEqual({ stream: true });
  });
});
