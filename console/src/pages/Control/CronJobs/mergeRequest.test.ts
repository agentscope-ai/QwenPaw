import { describe, expect, it } from "vitest";
import { mergeCronJobRequest } from "./mergeRequest";

describe("mergeCronJobRequest", () => {
  it("preserves request extensions while applying submitted fields", () => {
    const existing = {
      input: ["old"],
      model_slot_override: {
        provider_id: "openai",
        model: "gpt-4o-mini",
      },
      request_context: { source: "cli" },
    };
    const submitted = { input: ["new"] };

    const merged = mergeCronJobRequest(existing, submitted);

    expect(merged).toEqual({
      input: ["new"],
      model_slot_override: {
        provider_id: "openai",
        model: "gpt-4o-mini",
      },
      request_context: { source: "cli" },
    });
    expect(existing.input).toEqual(["old"]);
    expect(submitted.input).toEqual(["new"]);
  });

  it("supports creating a request without an existing job", () => {
    expect(mergeCronJobRequest(undefined, { input: [] })).toEqual({
      input: [],
    });
  });
});
