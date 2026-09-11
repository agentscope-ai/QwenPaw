import { describe, expect, it, vi } from "vitest";
import {
  handleRerankerFieldsChange,
  isRerankerDetailFieldError,
  rerankerDetailsHaveErrors,
  RERANKER_ENABLED_PATH,
} from "./rerankerVisibility";

const rerankerPath = (leaf: string) => [
  "reme_light_memory_config",
  "reranker_config",
  leaf,
];

/** Every leaf rendered inside #reranker-details. */
const detailLeaves = [
  "base_url",
  "model_name",
  "api_key",
  "candidate_multiplier",
  "timeout",
];

const fieldError = (leaf: string, errorCount = 1) => ({
  name: rerankerPath(leaf),
  errors: Array.from({ length: errorCount }, () => "invalid"),
});

describe("isRerankerDetailFieldError", () => {
  it("flags every reranker details field that has an error", () => {
    for (const leaf of detailLeaves) {
      expect(isRerankerDetailFieldError(fieldError(leaf)), leaf).toBe(true);
    }
  });

  it("ignores the enabled switch, which renders outside the details", () => {
    expect(isRerankerDetailFieldError(fieldError("enabled"))).toBe(false);
  });

  it("ignores reranker fields without errors", () => {
    expect(
      isRerankerDetailFieldError({ name: rerankerPath("timeout"), errors: [] }),
    ).toBe(false);
    expect(isRerankerDetailFieldError({ name: rerankerPath("timeout") })).toBe(
      false,
    );
  });

  it("keeps the enabled path pinned, since the handler reads it at runtime", () => {
    // The stub form below looks up fields by name[2], so a wrong path string
    // here would let the handler silently stop expanding with no test failing.
    expect(RERANKER_ENABLED_PATH).toEqual([
      "reme_light_memory_config",
      "reranker_config",
      "enabled",
    ]);
  });

  it("ignores fields outside the reranker config", () => {
    expect(
      isRerankerDetailFieldError({
        name: [
          "reme_light_memory_config",
          "embedding_model_config",
          "model_name",
        ],
        errors: ["missing"],
      }),
    ).toBe(false);
    expect(
      isRerankerDetailFieldError({
        name: ["loop", "max_tokens"],
        errors: ["missing"],
      }),
    ).toBe(false);
  });
});

describe("rerankerDetailsHaveErrors", () => {
  it("is true for each reranker details field", () => {
    for (const leaf of detailLeaves) {
      expect(rerankerDetailsHaveErrors([fieldError(leaf)], true), leaf).toBe(
        true,
      );
    }
  });

  it("is false when reranking is disabled, even with invalid details fields", () => {
    expect(
      rerankerDetailsHaveErrors([fieldError("candidate_multiplier")], false),
    ).toBe(false);
  });

  it("is false when only the enabled switch is invalid", () => {
    expect(rerankerDetailsHaveErrors([fieldError("enabled")], true)).toBe(
      false,
    );
  });

  it("is false when only other form sections are invalid", () => {
    expect(
      rerankerDetailsHaveErrors(
        [{ name: ["loop", "max_tokens"], errors: ["missing"] }],
        true,
      ),
    ).toBe(false);
  });

  it("is false with no errors at all", () => {
    expect(rerankerDetailsHaveErrors([], true)).toBe(false);
    expect(rerankerDetailsHaveErrors([], false)).toBe(false);
  });
});

describe("handleRerankerFieldsChange", () => {
  const formWith = (enabled: boolean) => ({
    getFieldValue: (name: readonly (string | number)[]) =>
      name[2] === "enabled" ? enabled : undefined,
  });

  it("expands on an invalid hidden numeric field", () => {
    for (const leaf of ["candidate_multiplier", "timeout"]) {
      const setExpanded = vi.fn();
      handleRerankerFieldsChange(formWith(true), setExpanded)(
        [],
        [fieldError(leaf)],
      );
      expect(setExpanded, leaf).toHaveBeenCalledWith(true);
    }
  });

  it("expands on invalid base_url and model_name", () => {
    for (const leaf of ["base_url", "model_name"]) {
      const setExpanded = vi.fn();
      handleRerankerFieldsChange(formWith(true), setExpanded)(
        [],
        [fieldError(leaf)],
      );
      expect(setExpanded, leaf).toHaveBeenCalledWith(true);
    }
  });

  it("does not expand when reranking is disabled", () => {
    const setExpanded = vi.fn();
    handleRerankerFieldsChange(formWith(false), setExpanded)(
      [],
      [fieldError("candidate_multiplier")],
    );
    expect(setExpanded).not.toHaveBeenCalled();
  });

  it("does not expand for the enabled switch or other sections", () => {
    const setExpanded = vi.fn();
    handleRerankerFieldsChange(formWith(true), setExpanded)(
      [],
      [
        fieldError("enabled"),
        { name: ["loop", "max_tokens"], errors: ["missing"] },
      ],
    );
    expect(setExpanded).not.toHaveBeenCalled();
  });
});
