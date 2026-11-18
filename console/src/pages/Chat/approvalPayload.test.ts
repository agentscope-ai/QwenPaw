import { describe, expect, it } from "vitest";
import type { ToolExecutionLevel } from "../../utils/approval";
import { applyApprovalLevelToRequestBody } from "./approvalPayload";

const STRICT: ToolExecutionLevel = "STRICT";
const SMART: ToolExecutionLevel = "SMART";
const AUTO: ToolExecutionLevel = "AUTO";
const OFF: ToolExecutionLevel = "OFF";

describe("applyApprovalLevelToRequestBody", () => {
  it("prefers the session level over the running-config level", () => {
    const body: Record<string, unknown> = {};
    applyApprovalLevelToRequestBody(body, STRICT, AUTO);
    expect(body.request_context).toEqual({ approval_level: "STRICT" });
  });

  it("falls back to the running-config level when the session level is null", () => {
    const body: Record<string, unknown> = {};
    applyApprovalLevelToRequestBody(body, null, SMART);
    expect(body.request_context).toEqual({ approval_level: "SMART" });
  });

  it("keeps a session level of OFF instead of falling back to the running config", () => {
    // OFF means "no approval prompts" - a deliberate choice, so it must win
    // over the running-config default. (Note: every ToolExecutionLevel is a
    // non-empty string, hence truthy, so `??` and `||` are equivalent here; the
    // only falsy sessionLevel is null, covered above.)
    const body: Record<string, unknown> = {};
    applyApprovalLevelToRequestBody(body, OFF, STRICT);
    expect(body.request_context).toEqual({ approval_level: "OFF" });
  });

  it("preserves the other fields of an existing request_context", () => {
    const body: Record<string, unknown> = {
      request_context: { foo: "bar", nested: { a: 1 } },
    };
    applyApprovalLevelToRequestBody(body, OFF, AUTO);
    expect(body.request_context).toEqual({
      foo: "bar",
      nested: { a: 1 },
      approval_level: "OFF",
    });
  });

  it("copies rather than mutates the original request_context object", () => {
    const original = { foo: "bar" };
    const body: Record<string, unknown> = { request_context: original };
    applyApprovalLevelToRequestBody(body, STRICT, AUTO);
    expect(original).toEqual({ foo: "bar" });
    expect(body.request_context).not.toBe(original);
  });

  it("replaces a non-object request_context with a fresh one", () => {
    const body: Record<string, unknown> = { request_context: "garbage" };
    applyApprovalLevelToRequestBody(body, AUTO, AUTO);
    expect(body.request_context).toEqual({ approval_level: "AUTO" });
  });

  it("replaces an array request_context with a fresh one", () => {
    const body: Record<string, unknown> = { request_context: [1, 2] };
    applyApprovalLevelToRequestBody(body, STRICT, AUTO);
    expect(body.request_context).toEqual({ approval_level: "STRICT" });
  });

  it("replaces a null request_context with a fresh one", () => {
    const body: Record<string, unknown> = { request_context: null };
    applyApprovalLevelToRequestBody(body, SMART, AUTO);
    expect(body.request_context).toEqual({ approval_level: "SMART" });
  });

  it("creates request_context when the body has none, leaving siblings intact", () => {
    const body: Record<string, unknown> = { other: 1 };
    applyApprovalLevelToRequestBody(body, OFF, AUTO);
    expect(body.request_context).toEqual({ approval_level: "OFF" });
    expect(body.other).toBe(1);
  });

  it("mutates the body in place and returns nothing", () => {
    const body: Record<string, unknown> = {};
    expect(applyApprovalLevelToRequestBody(body, AUTO, AUTO)).toBeUndefined();
    expect(body).toHaveProperty("request_context");
  });
});
