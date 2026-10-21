/**
 * parseErrorDetail extracts structured error details from request.ts
 * formatted errors ("message - {json}") and from raw JSON messages,
 * so the UI can show server-provided details instead of opaque text.
 */
import { describe, it, expect } from "vitest";
import { parseErrorDetail, summarizeValidationDetail } from "./error";

describe("parseErrorDetail", () => {
  it("returns null for non-Error values", () => {
    expect(parseErrorDetail("just a string")).toBeNull();
    expect(parseErrorDetail(42)).toBeNull();
    expect(parseErrorDetail(null)).toBeNull();
    expect(parseErrorDetail(undefined)).toBeNull();
  });

  it("returns null for a plain-text error message", () => {
    expect(parseErrorDetail(new Error("network is down"))).toBeNull();
  });

  it("parses JSON after the ' - ' separator used by request.ts", () => {
    const error = new Error('Request failed - {"detail": "quota exceeded"}');
    // The detail key is unwrapped so callers get the server message directly
    expect(parseErrorDetail(error)).toBe("quota exceeded");
  });

  it("unwraps the detail key when present", () => {
    const error = new Error('400 Bad Request - {"detail": "invalid key"}');
    expect(parseErrorDetail(error)).toBe("invalid key");
  });

  it("returns the parsed object when there is no detail key", () => {
    const error = new Error('500 - {"code": "internal"}');
    expect(parseErrorDetail(error)).toEqual({ code: "internal" });
  });

  it("falls back to parsing the whole message when no separator", () => {
    const error = new Error('{"detail": "rate limited"}');
    expect(parseErrorDetail(error)).toBe("rate limited");
  });

  it("returns null when the separator payload is not valid JSON", () => {
    const error = new Error("failed - not json at all");
    expect(parseErrorDetail(error)).toBeNull();
  });

  it("returns null when the whole message is not JSON", () => {
    const error = new Error("{broken json");
    expect(parseErrorDetail(error)).toBeNull();
  });

  it("returns null when the whole message parses to a non-object", () => {
    const error = new Error("42");
    expect(parseErrorDetail(error)).toBeNull();
  });
});

describe("summarizeValidationDetail", () => {
  it("names the field a schema rejection came from", () => {
    expect(
      summarizeValidationDetail([
        {
          type: "int_type",
          loc: ["body", "reme_light_memory_config", "proactive_max_items"],
          msg: "Input should be a valid integer",
          input: null,
        },
      ]),
    ).toBe(
      "reme_light_memory_config.proactive_max_items: Input should be a valid integer",
    );
  });

  it("joins every failure and skips unreadable entries", () => {
    expect(
      summarizeValidationDetail([
        { loc: ["body", "a"], msg: "too small" },
        { loc: ["query"], msg: "missing" },
        null,
        "junk",
        {},
      ]),
    ).toBe("a: too small; query: missing");
  });

  it("returns null when there is nothing to show", () => {
    expect(summarizeValidationDetail(null)).toBeNull();
    expect(summarizeValidationDetail([])).toBeNull();
    expect(summarizeValidationDetail("already a string")).toBeNull();
    expect(summarizeValidationDetail({ nested: { a: 1 } })).toBeNull();
  });

  it("reads the object detail of a semantic rejection", () => {
    expect(
      summarizeValidationDetail({
        backend: "remelight",
        reason: "plugin_not_installed",
      }),
    ).toBe("backend: remelight; reason: plugin_not_installed");
    expect(summarizeValidationDetail({ nested: { a: 1 } })).toBeNull();
  });
});
