import { describe, expect, it } from "vitest";
import { summarizeCheckItems } from "./scanSummary";
import { isVisibleCheckItem } from "./detailMessages";

describe("scanSummary", () => {
  it("counts attention items", () => {
    const summary = summarizeCheckItems([
      {
        id: "a",
        group: "config",
        status: "ok",
        detail: "",
        risk: "",
        recommendation: "",
        deep_only: false,
      },
      {
        id: "b",
        group: "config",
        status: "risk",
        detail: "",
        risk: "",
        recommendation: "",
        deep_only: false,
      },
      {
        id: "c",
        group: "config",
        status: "suggestion",
        detail: "",
        risk: "",
        recommendation: "",
        deep_only: false,
      },
    ]);
    expect(summary).toEqual({
      total: 3,
      ok: 1,
      risk: 1,
      suggestion: 1,
      skipped: 0,
      attention: 2,
    });
  });
});

describe("detailMessages visibility", () => {
  it("hides web-authentication placeholder", () => {
    expect(
      isVisibleCheckItem({
        id: "web-authentication",
        group: "web-authentication",
        status: "ok",
        detail: "",
        risk: "",
        recommendation: "",
        deep_only: false,
      }),
    ).toBe(false);
  });
});
