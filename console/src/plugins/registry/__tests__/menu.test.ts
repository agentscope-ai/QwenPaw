/**
 * menu.test.ts — MenuRegistry behaviour.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { menuRegistry } from "../store";
import { auditStore } from "../audit";

beforeEach(() => {
  menuRegistry.__resetForTests();
  auditStore.clear();
});

describe("menuRegistry.add", () => {
  it("adds an item that appears in snapshot", () => {
    menuRegistry.add("p1", {
      id: "p1.foo",
      location: "primary.settings",
      label: "Foo",
    });
    const items = menuRegistry.snapshot("primary.settings");
    expect(items.map((i) => i.id)).toContain("p1.foo");
  });

  it("default location is primary.settings", () => {
    menuRegistry.add("p1", { id: "p1.bar", label: "Bar" });
    expect(
      menuRegistry.snapshot("primary.settings").map((i) => i.id),
    ).toContain("p1.bar");
  });

  it("duplicate id is rejected with conflict audit", () => {
    menuRegistry.add("p1", { id: "x", label: "A" });
    menuRegistry.add("p2", { id: "x", label: "B" });
    const items = menuRegistry.snapshot("primary.settings");
    expect(items.filter((i) => i.id === "x")).toHaveLength(1);
    expect(
      auditStore
        .overrides()
        .some((r) => r.kind === "menu.conflict" && r.pluginId === "p2"),
    ).toBe(true);
  });

  it("filters items where visible() returns false", () => {
    menuRegistry.add("p1", {
      id: "shown",
      label: "S",
      visible: () => true,
    });
    menuRegistry.add("p1", {
      id: "hidden",
      label: "H",
      visible: () => false,
    });
    const items = menuRegistry.snapshot("primary.settings").map((i) => i.id);
    expect(items).toContain("shown");
    expect(items).not.toContain("hidden");
  });

  it("recomputes visible() after refresh", () => {
    let visible = false;
    menuRegistry.add("p1", {
      id: "refreshable",
      label: "R",
      visible: () => visible,
    });
    expect(
      menuRegistry.snapshot("primary.settings").map((i) => i.id),
    ).not.toContain("refreshable");

    visible = true;
    expect(
      menuRegistry.snapshot("primary.settings").map((i) => i.id),
    ).not.toContain("refreshable");

    menuRegistry.refresh();
    expect(
      menuRegistry.snapshot("primary.settings").map((i) => i.id),
    ).toContain("refreshable");
  });
});

describe("menuRegistry.replace", () => {
  it("later writer wins, audit records supersede", () => {
    menuRegistry.add("p1", { id: "x", label: "from P1" });
    menuRegistry.replace("p2", "x", { id: "x", label: "from P2" });
    const item = menuRegistry
      .snapshot("primary.settings")
      .find((i) => i.id === "x");
    expect(item?.label).toBe("from P2");
    expect(
      auditStore
        .overrides()
        .some(
          (r) =>
            r.kind === "menu.replace" &&
            r.pluginId === "p2" &&
            r.supersededPluginId === "p1",
        ),
    ).toBe(true);
  });

  it("disposing winner falls back to prior (LIFO)", () => {
    menuRegistry.add("p1", { id: "x", label: "P1" });
    const d = menuRegistry.replace("p2", "x", { id: "x", label: "P2" });
    d.dispose();
    const item = menuRegistry
      .snapshot("primary.settings")
      .find((i) => i.id === "x");
    expect(item?.label).toBe("P1");
  });
});

describe("menuRegistry topology (before/after/order)", () => {
  it("respects before/after constraints", () => {
    menuRegistry.add("core", { id: "a", label: "A", order: 10 });
    menuRegistry.add("core", { id: "b", label: "B", order: 20 });
    menuRegistry.add("p1", { id: "c", label: "C", before: "b" });
    const ids = menuRegistry.snapshot("primary.settings").map((i) => i.id);
    const a = ids.indexOf("a"),
      b = ids.indexOf("b"),
      c = ids.indexOf("c");
    expect(c).toBeLessThan(b);
    expect(a).toBeLessThan(b);
  });

  it("falls back to order on a cycle", () => {
    menuRegistry.add("core", { id: "a", label: "A", before: "b", order: 1 });
    menuRegistry.add("core", { id: "b", label: "B", before: "a", order: 2 });
    const ids = menuRegistry.snapshot("primary.settings").map((i) => i.id);
    expect(ids).toContain("a");
    expect(ids).toContain("b");
  });

  it("builds parent/child tree via parentId", () => {
    menuRegistry.add("core", {
      id: "g",
      label: "Group",
      isGroup: true,
    });
    menuRegistry.add("core", {
      id: "child1",
      label: "C1",
      parentId: "g",
    });
    menuRegistry.add("core", {
      id: "child2",
      label: "C2",
      parentId: "g",
    });
    const items = menuRegistry.snapshot("primary.settings");
    const group = items.find((i) => i.id === "g") as MenuItem & {
      __children?: MenuItem[];
    };
    expect(group?.__children?.map((c) => c.id)).toEqual(["child1", "child2"]);
    // children should NOT also appear at top level
    expect(items.map((i) => i.id)).not.toContain("child1");
  });
});

describe("menuRegistry locations", () => {
  it("separates agentScoped vs settings buckets", () => {
    menuRegistry.add("core", {
      id: "a",
      location: "primary.agentScoped",
      label: "A",
    });
    menuRegistry.add("core", {
      id: "s",
      location: "primary.settings",
      label: "S",
    });
    expect(
      menuRegistry.snapshot("primary.agentScoped").map((i) => i.id),
    ).toEqual(["a"]);
    expect(menuRegistry.snapshot("primary.settings").map((i) => i.id)).toEqual([
      "s",
    ]);
  });
});

describe("menuRegistry href support", () => {
  it("item with href appears in snapshot", () => {
    menuRegistry.add("p1", {
      id: "ext-link",
      label: "External",
      href: "https://example.com",
    });
    const items = menuRegistry.snapshot("primary.settings");
    const item = items.find((i) => i.id === "ext-link");
    expect(item).toBeDefined();
    expect(item?.href).toBe("https://example.com");
  });

  it("href and route can coexist", () => {
    menuRegistry.add("p1", {
      id: "dual",
      label: "Dual",
      route: "core.chat",
      href: "https://example.com",
    });
    const items = menuRegistry.snapshot("primary.settings");
    const item = items.find((i) => i.id === "dual");
    expect(item?.route).toBe("core.chat");
    expect(item?.href).toBe("https://example.com");
  });
});

import type { MenuItem } from "../types";
