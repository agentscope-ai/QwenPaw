/**
 * chatExtensions.test.ts — pure registry behaviour (no React).
 */
import { describe, it, expect, beforeEach } from "vitest";
import { chatExtensions } from "./chatExtensions";
import { auditStore } from "./audit";

beforeEach(() => {
  chatExtensions.__resetForTests();
  auditStore.clear();
});

describe("chatExtensions.setScalar", () => {
  it("returns the most-recently-registered value", () => {
    chatExtensions.setScalar("p1", "welcome.greeting", "Hi from P1");
    expect(chatExtensions.getScalarSnapshot()["welcome.greeting"]).toEqual({
      pluginId: "p1",
      value: "Hi from P1",
    });
  });

  it("later writer wins and audit captures the supersede", () => {
    chatExtensions.setScalar("p1", "welcome.greeting", "Hi P1");
    chatExtensions.setScalar("p2", "welcome.greeting", "Hi P2");
    expect(
      chatExtensions.getScalarSnapshot()["welcome.greeting"]?.pluginId,
    ).toBe("p2");
    const records = auditStore.overrides();
    expect(
      records.some(
        (r) =>
          r.kind === "chat.scalar.superseded" &&
          r.pluginId === "p1" &&
          r.supersededPluginId === "p2",
      ),
    ).toBe(true);
  });

  it("disposing the winner falls back to the prior entry (LIFO)", () => {
    chatExtensions.setScalar("p1", "welcome.greeting", "Hi P1");
    const d2 = chatExtensions.setScalar("p2", "welcome.greeting", "Hi P2");
    d2.dispose();
    expect(
      chatExtensions.getScalarSnapshot()["welcome.greeting"]?.pluginId,
    ).toBe("p1");
  });

  it("disposing a non-winner does not affect the current winner", () => {
    const d1 = chatExtensions.setScalar("p1", "welcome.greeting", "Hi P1");
    chatExtensions.setScalar("p2", "welcome.greeting", "Hi P2");
    d1.dispose();
    expect(
      chatExtensions.getScalarSnapshot()["welcome.greeting"]?.pluginId,
    ).toBe("p2");
  });

  it("idempotent dispose() — second call is a no-op", () => {
    const d = chatExtensions.setScalar("p1", "welcome.greeting", "Hi");
    d.dispose();
    d.dispose();
    expect(
      chatExtensions.getScalarSnapshot()["welcome.greeting"],
    ).toBeUndefined();
  });
});

describe("chatExtensions additive lists", () => {
  it("addAction items appear in registration order", () => {
    chatExtensions.addAction("p1", {
      id: "p1.share",
      onClick: () => {},
    });
    chatExtensions.addAction("p2", {
      id: "p2.bookmark",
      onClick: () => {},
    });
    const snap = chatExtensions.getListSnapshot().actions;
    expect(snap.map((e) => e.item.id)).toEqual(["p1.share", "p2.bookmark"]);
  });

  it("dispose removes only the targeted entry", () => {
    chatExtensions.addAction("p1", { id: "a", onClick: () => {} });
    const d = chatExtensions.addAction("p2", {
      id: "b",
      onClick: () => {},
    });
    chatExtensions.addAction("p3", { id: "c", onClick: () => {} });
    d.dispose();
    const snap = chatExtensions.getListSnapshot().actions;
    expect(snap.map((e) => e.item.id)).toEqual(["a", "c"]);
  });

  it("addRightHeader items survive snapshot reads as stable references", () => {
    chatExtensions.addRightHeader("p1", { id: "p1.btn", node: "X" });
    const a = chatExtensions.getListSnapshot()["header.rightHeader"];
    const b = chatExtensions.getListSnapshot()["header.rightHeader"];
    expect(a).toBe(b);
  });
});

describe("chatExtensions.disposeAll", () => {
  it("removes every registration from a single plugin", () => {
    chatExtensions.setScalar("p1", "welcome.greeting", "Hi P1");
    chatExtensions.setScalar("p1", "welcome.nick", "P1");
    chatExtensions.setScalar("p2", "welcome.greeting", "Hi P2");
    chatExtensions.addAction("p1", {
      id: "p1.act",
      onClick: () => {},
    });
    chatExtensions.addAction("p2", {
      id: "p2.act",
      onClick: () => {},
    });

    chatExtensions.disposeAll("p1");

    const scalar = chatExtensions.getScalarSnapshot();
    expect(scalar["welcome.greeting"]?.pluginId).toBe("p2");
    expect(scalar["welcome.nick"]).toBeUndefined();

    const actions = chatExtensions
      .getListSnapshot()
      .actions.map((e) => e.item.id);
    expect(actions).toEqual(["p2.act"]);
  });
});

describe("chatExtensions subscriptions", () => {
  it("notifies subscribers on add and dispose", () => {
    let count = 0;
    const off = chatExtensions.subscribe(() => {
      count += 1;
    });
    const d = chatExtensions.setScalar("p", "welcome.greeting", "x");
    d.dispose();
    off();
    expect(count).toBeGreaterThanOrEqual(2);
  });
});

describe("audit store ring buffer", () => {
  it("returns a copy each call (no internal-mutation hazard)", () => {
    chatExtensions.setScalar("p", "welcome.greeting", "x");
    const a = auditStore.overrides();
    const b = auditStore.overrides();
    expect(a).not.toBe(b);
    expect(a).toEqual(b);
  });
});
