import { describe, it, expect } from "vitest";
import { groupUsage, usageFields } from "./usageAnalytics";
import type { UsageDetailRow } from "../../../api/modules/hubGovernance";

/**
 * groupUsage is a pure aggregator, so every case builds plain rows and asserts
 * the returned group objects: totals, labels, distinct member/model counts and
 * the ordering contract.
 */

function row(over: Partial<UsageDetailRow> = {}): UsageDetailRow {
  return {
    date: "2026-03-01",
    user_id: "u-1",
    username: "alice",
    model_id: "m-1",
    model_name: "qwen-max",
    requests: 1,
    charged: 10,
    actual: 8,
    reserved: 2,
    conservative: 1,
    failures: 0,
    ...over,
  };
}

describe("usageFields", () => {
  it("lists exactly the six aggregated numeric fields", () => {
    expect([...usageFields]).toEqual([
      "requests",
      "charged",
      "actual",
      "reserved",
      "conservative",
      "failures",
    ]);
  });
});

describe("groupUsage — empty and single row input", () => {
  it("returns no groups for an empty row list", () => {
    expect(groupUsage([], "user_id")).toEqual([]);
  });

  it("returns one group per single row", () => {
    const groups = groupUsage([row()], "user_id");
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({
      key: "u-1",
      label: "alice",
      members: 1,
      models: 1,
    });
  });

  it("starts every usage field at zero before accumulating", () => {
    const groups = groupUsage(
      [
        row({
          requests: 0,
          charged: 0,
          actual: 0,
          reserved: 0,
          conservative: 0,
          failures: 0,
        }),
      ],
      "user_id",
    );
    for (const field of usageFields) {
      expect(groups[0][field]).toBe(0);
    }
  });
});

describe("groupUsage — accumulation", () => {
  it("sums all six usage fields across rows of the same user", () => {
    const groups = groupUsage(
      [
        row({
          requests: 3,
          charged: 10,
          actual: 4,
          reserved: 5,
          conservative: 1,
          failures: 2,
        }),
        row({
          requests: 7,
          charged: 20,
          actual: 6,
          reserved: 9,
          conservative: 3,
          failures: 1,
        }),
      ],
      "user_id",
    );
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({
      requests: 10,
      charged: 30,
      actual: 10,
      reserved: 14,
      conservative: 4,
      failures: 3,
    });
  });

  it("counts distinct models but not distinct rows in the models field", () => {
    const groups = groupUsage(
      [
        row({ model_id: "m-1" }),
        row({ model_id: "m-1" }),
        row({ model_id: "m-2" }),
      ],
      "user_id",
    );
    expect(groups[0].models).toBe(2);
  });

  it("counts distinct users within one model group", () => {
    const groups = groupUsage(
      [
        row({ user_id: "u-1", username: "alice" }),
        row({ user_id: "u-2", username: "bob" }),
        row({ user_id: "u-1", username: "alice" }),
      ],
      "model_id",
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].members).toBe(2);
    // The model group has exactly one model, no matter how many rows feed it.
    expect(groups[0].models).toBe(1);
  });

  it("keeps one member for a single user seen across several dates", () => {
    const groups = groupUsage(
      [row({ date: "2026-03-01" }), row({ date: "2026-03-02" })],
      "user_id",
    );
    expect(groups[0].members).toBe(1);
  });

  it("leaves the input rows untouched", () => {
    const rows = [row(), row({ charged: 99 })];
    const snapshot = JSON.parse(JSON.stringify(rows));
    groupUsage(rows, "user_id");
    expect(rows).toEqual(snapshot);
  });
});

describe("groupUsage — label per dimension", () => {
  it("labels user groups with the username", () => {
    const groups = groupUsage(
      [row({ user_id: "u-9", username: "carol", model_name: "ignored" })],
      "user_id",
    );
    expect(groups[0]).toMatchObject({ key: "u-9", label: "carol" });
  });

  it("labels model groups with the model name", () => {
    const groups = groupUsage(
      [row({ model_id: "m-7", model_name: "qwen-plus", username: "ignored" })],
      "model_id",
    );
    expect(groups[0]).toMatchObject({ key: "m-7", label: "qwen-plus" });
  });

  it("labels date groups with the date itself", () => {
    const groups = groupUsage([row({ date: "2026-03-05" })], "date");
    expect(groups[0]).toMatchObject({ key: "2026-03-05", label: "2026-03-05" });
  });

  it("keeps the label of the first row when later rows differ", () => {
    // The label is written once at group creation, so a renamed user does not
    // rewrite the group label mid aggregation.
    const groups = groupUsage(
      [
        row({ user_id: "u-1", username: "alice" }),
        row({ user_id: "u-1", username: "alice-renamed" }),
      ],
      "user_id",
    );
    expect(groups[0].label).toBe("alice");
  });

  it("splits rows into separate groups per date", () => {
    const groups = groupUsage(
      [row({ date: "2026-03-01" }), row({ date: "2026-03-02" })],
      "date",
    );
    expect(groups.map((g) => g.key).sort()).toEqual([
      "2026-03-01",
      "2026-03-02",
    ]);
  });
});

describe("groupUsage — ordering", () => {
  it("orders groups by charged descending", () => {
    const groups = groupUsage(
      [
        row({ user_id: "u-low", username: "low", charged: 5 }),
        row({ user_id: "u-high", username: "high", charged: 500 }),
        row({ user_id: "u-mid", username: "mid", charged: 50 }),
      ],
      "user_id",
    );
    expect(groups.map((g) => g.key)).toEqual(["u-high", "u-mid", "u-low"]);
  });

  it("breaks a charged tie by ascending key", () => {
    const groups = groupUsage(
      [
        row({ user_id: "u-zeta", username: "zeta", charged: 10 }),
        row({ user_id: "u-alpha", username: "alpha", charged: 10 }),
      ],
      "user_id",
    );
    expect(groups.map((g) => g.key)).toEqual(["u-alpha", "u-zeta"]);
  });

  it("applies the tie break independently of insertion order", () => {
    const ascending = groupUsage(
      [
        row({ user_id: "u-a", username: "a", charged: 1 }),
        row({ user_id: "u-b", username: "b", charged: 1 }),
      ],
      "user_id",
    );
    const descending = groupUsage(
      [
        row({ user_id: "u-b", username: "b", charged: 1 }),
        row({ user_id: "u-a", username: "a", charged: 1 }),
      ],
      "user_id",
    );
    expect(ascending.map((g) => g.key)).toEqual(["u-a", "u-b"]);
    expect(descending.map((g) => g.key)).toEqual(ascending.map((g) => g.key));
  });

  it("ranks charged above requests when they disagree", () => {
    const groups = groupUsage(
      [
        row({
          user_id: "u-many-requests",
          username: "r",
          requests: 999,
          charged: 1,
        }),
        row({
          user_id: "u-few-requests",
          username: "f",
          requests: 1,
          charged: 999,
        }),
      ],
      "user_id",
    );
    expect(groups[0].key).toBe("u-few-requests");
  });

  it("keeps zero charged groups ordered by key", () => {
    const groups = groupUsage(
      [
        row({ user_id: "u-b", username: "b", charged: 0 }),
        row({ user_id: "u-a", username: "a", charged: 0 }),
      ],
      "user_id",
    );
    expect(groups.map((g) => g.key)).toEqual(["u-a", "u-b"]);
  });
});

describe("groupUsage — mixed populations", () => {
  it("groups a two by two matrix into two user groups", () => {
    const groups = groupUsage(
      [
        row({
          user_id: "u-1",
          username: "alice",
          model_id: "m-1",
          charged: 10,
        }),
        row({
          user_id: "u-1",
          username: "alice",
          model_id: "m-2",
          charged: 20,
        }),
        row({ user_id: "u-2", username: "bob", model_id: "m-1", charged: 30 }),
        row({ user_id: "u-2", username: "bob", model_id: "m-2", charged: 40 }),
      ],
      "user_id",
    );
    expect(groups).toHaveLength(2);
    expect(groups.map((g) => g.key)).toEqual(["u-2", "u-1"]);
    expect(groups.map((g) => g.charged)).toEqual([70, 30]);
    expect(groups.every((g) => g.members === 1 && g.models === 2)).toBe(true);
  });

  it("groups the same matrix into two model groups", () => {
    const groups = groupUsage(
      [
        row({
          user_id: "u-1",
          model_id: "m-1",
          model_name: "one",
          charged: 10,
        }),
        row({
          user_id: "u-1",
          model_id: "m-2",
          model_name: "two",
          charged: 20,
        }),
        row({
          user_id: "u-2",
          model_id: "m-1",
          model_name: "one",
          charged: 30,
        }),
        row({
          user_id: "u-2",
          model_id: "m-2",
          model_name: "two",
          charged: 40,
        }),
      ],
      "model_id",
    );
    expect(groups).toHaveLength(2);
    expect(groups.map((g) => g.key)).toEqual(["m-2", "m-1"]);
    expect(groups.every((g) => g.members === 2 && g.models === 1)).toBe(true);
  });

  it("accumulates fractional charged amounts without drift", () => {
    const groups = groupUsage(
      [row({ charged: 0.5 }), row({ charged: 0.25 })],
      "user_id",
    );
    expect(groups[0].charged).toBeCloseTo(0.75, 10);
  });
});
