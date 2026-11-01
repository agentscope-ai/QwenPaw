/**
 * sdk.test.ts — public plugin API factory contract.
 *
 * The four build*Namespace() factories are thin delegators over the shared
 * registries. Each case below asserts the delegation contract that plugins
 * actually rely on: which registry received the call, with which arguments, and
 * what comes back. Registry internals are already covered by menu.test.ts /
 * routes.test.tsx / slot.test.ts, so nothing here re-tests their behaviour.
 *
 * Registries are module-level singletons, hence the explicit reset per test.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { render } from "@testing-library/react";
import {
  buildMenuNamespace,
  buildRouteNamespace,
  buildSlotNamespace,
  buildAuditNamespace,
} from "../sdk";
import { menuRegistry, routeRegistry, slotRegistry } from "../store";
import { auditStore } from "../audit";
import type { MenuItem } from "../types";

const Base = () => React.createElement("div", null, "base");
const Replacement = () => React.createElement("div", null, "replacement");

const menuItem = (id: string, extra: Partial<MenuItem> = {}): MenuItem => ({
  id,
  label: id,
  ...extra,
});

beforeEach(() => {
  menuRegistry.__resetForTests();
  routeRegistry.__resetForTests();
  slotRegistry.__resetForTests();
  auditStore.clear();
});

describe("buildMenuNamespace", () => {
  it("add accepts a single item and returns a working disposable", () => {
    const menu = buildMenuNamespace();
    const d = menu.add("p1", menuItem("p1.single"));

    expect(menuRegistry.snapshot("primary.settings").map((i) => i.id)).toEqual([
      "p1.single",
    ]);

    d.dispose();
    expect(
      menuRegistry.snapshot("primary.settings").map((i) => i.id),
    ).not.toContain("p1.single");
  });

  it("add accepts an array and one disposable releases every entry", () => {
    const menu = buildMenuNamespace();
    const d = menu.add("p1", [menuItem("p1.a"), menuItem("p1.b")]);

    expect(menuRegistry.snapshot("primary.settings").map((i) => i.id)).toEqual([
      "p1.a",
      "p1.b",
    ]);

    d.dispose();
    expect(menuRegistry.snapshot("primary.settings")).toHaveLength(0);
  });

  it("replace records a conflict and falls back to add when target is absent", () => {
    const menu = buildMenuNamespace();

    menu.replace("p1", "ghost", menuItem("ghost", { label: "L" }));

    expect(
      menuRegistry.snapshot("primary.settings").map((i) => i.id),
    ).toContain("ghost");
    expect(
      auditStore
        .overrides()
        .some((r) => r.kind === "menu.conflict" && r.targetId === "ghost"),
    ).toBe(true);
  });

  it("replace returns a disposable that restores the previous winner", () => {
    const menu = buildMenuNamespace();
    menu.add("core", menuItem("core.target", { label: "original" }));

    const d = menu.replace(
      "p1",
      "core.target",
      menuItem("x", { label: "new" }),
    );
    expect(menuRegistry.snapshot("primary.settings")).toHaveLength(1);
    expect(menuRegistry.snapshot("primary.settings")[0]).toMatchObject({
      id: "core.target",
      label: "new",
    });

    d.dispose();
    expect(menuRegistry.snapshot("primary.settings")[0].label).toBe("original");
  });

  it("remove drops the entry by id", () => {
    const menu = buildMenuNamespace();
    menu.add("p1", menuItem("p1.gone"));

    menu.remove("p1.gone");

    expect(menuRegistry.snapshot("primary.settings")).toHaveLength(0);
  });

  it("remove of an unknown id is a no-op and does not throw", () => {
    const menu = buildMenuNamespace();
    menu.add("p1", menuItem("p1.keep"));

    expect(() => menu.remove("never.registered")).not.toThrow();
    expect(menuRegistry.snapshot("primary.settings").map((i) => i.id)).toEqual([
      "p1.keep",
    ]);
  });

  it("snapshot forwards the location filter", () => {
    const menu = buildMenuNamespace();
    menu.add("p1", menuItem("p1.settings"));
    menu.add("p1", menuItem("p1.user", { location: "userMenu" }));

    expect(menu.snapshot("primary.settings").map((i) => i.id)).toEqual([
      "p1.settings",
    ]);
    expect(menu.snapshot("userMenu").map((i) => i.id)).toEqual(["p1.user"]);
    expect(
      menu
        .snapshot()
        .map((i) => i.id)
        .sort(),
    ).toEqual(["p1.settings", "p1.user"]);
  });
});

describe("buildRouteNamespace", () => {
  it("add registers a single route and its disposable unregisters it", () => {
    const route = buildRouteNamespace();

    const d = route.add("p1", { id: "r1", path: "/r1", component: Base });
    expect(routeRegistry.snapshot().map((r) => r.id)).toEqual(["r1"]);

    d.dispose();
    expect(routeRegistry.snapshot()).toHaveLength(0);
  });

  it("add registers every route of an array under the same plugin id", () => {
    const route = buildRouteNamespace();

    const d = route.add("p1", [
      { id: "r1", path: "/r1", component: Base },
      { id: "r2", path: "/r2", component: Base },
    ]);

    expect(routeRegistry.snapshot().map((r) => r.id)).toEqual(["r1", "r2"]);
    expect(routeRegistry.snapshot().every((r) => r.source === "p1")).toBe(true);

    d.dispose();
    expect(routeRegistry.snapshot()).toHaveLength(0);
  });

  it("add of an empty array yields a disposable that changes nothing", () => {
    const route = buildRouteNamespace();

    const d = route.add("p1", []);
    expect(routeRegistry.snapshot()).toHaveLength(0);
    expect(() => d.dispose()).not.toThrow();
  });

  it("replace returns a disposable that restores the base component", () => {
    const route = buildRouteNamespace();
    route.add("core", { id: "p", path: "/p", component: Base });

    const d = route.replace("p1", "p", Replacement);
    expect(routeRegistry.snapshot().find((r) => r.id === "p")?.Component).toBe(
      Replacement,
    );
    d.dispose();

    const resolved = routeRegistry.snapshot().find((r) => r.id === "p");
    expect(resolved?.Component).toBe(Base);
  });

  it("wrap composes around the resolved component", () => {
    const route = buildRouteNamespace();
    route.add("core", { id: "p", path: "/p", component: Base });

    const wrapper = vi.fn(
      (Inner: React.ComponentType<object>) => () =>
        React.createElement("section", null, React.createElement(Inner)),
    );
    const d = route.wrap("p1", "p", wrapper);

    const resolved = routeRegistry.snapshot().find((r) => r.id === "p");
    const { container } = render(React.createElement(resolved!.Component));
    expect(container.querySelector("section")).not.toBeNull();
    expect(container.textContent).toBe("base");
    expect(wrapper).toHaveBeenCalled();
    d.dispose();
    expect(routeRegistry.snapshot().find((r) => r.id === "p")?.Component).toBe(
      Base,
    );
  });

  it("remove drops a registered route by id", () => {
    const route = buildRouteNamespace();
    route.add("p1", { id: "r1", path: "/r1", component: Base });

    route.remove("r1");

    expect(routeRegistry.snapshot()).toHaveLength(0);
  });

  it("remove of an unknown id leaves the registry untouched", () => {
    const route = buildRouteNamespace();
    route.add("p1", { id: "r1", path: "/r1", component: Base });

    expect(() => route.remove("nope")).not.toThrow();
    expect(routeRegistry.snapshot().map((r) => r.id)).toEqual(["r1"]);
  });
});

describe("buildSlotNamespace", () => {
  it("fill registers a renderer under the given slot name", () => {
    const slot = buildSlotNamespace();

    const d = slot.fill("p1", "header.left", () => null, { id: "a" });

    expect(slotRegistry.snapshot("header.left").map((e) => e.opts.id)).toEqual([
      "a",
    ]);

    d.dispose();
    expect(slotRegistry.snapshot("header.left")).toHaveLength(0);
  });

  it("fill works without opts and still returns a disposable", () => {
    const slot = buildSlotNamespace();

    const d = slot.fill("p1", "header.left", () => null);

    expect(slotRegistry.snapshot("header.left")).toHaveLength(1);
    expect(() => d.dispose()).not.toThrow();
  });

  it("replace returns a disposable that gives the slot back to the filler", () => {
    const slot = buildSlotNamespace();
    slot.fill("p1", "sider.bottom", () => null, { id: "fill" });

    const d = slot.replace("p2", "sider.bottom", () => null, { id: "winner" });
    expect(slotRegistry.snapshot("sider.bottom")).toHaveLength(1);
    expect(slotRegistry.snapshot("sider.bottom")[0]).toMatchObject({
      kind: "replace",
      opts: { id: "winner" },
    });
    d.dispose();

    const entries = slotRegistry.snapshot("sider.bottom");
    expect(entries.map((e) => e.opts.id)).toEqual(["fill"]);
    expect(entries[0].kind).toBe("fill");
  });

  it("snapshot lists every registered slot across names", () => {
    const slot = buildSlotNamespace();
    slot.fill("p1", "header.left", () => null, { id: "a", order: 5 });
    slot.replace("p2", "sider.bottom", () => null, { id: "b" });

    const all = slot.snapshot();

    expect(all).toHaveLength(2);
    expect(all.map((s) => s.name).sort()).toEqual([
      "header.left",
      "sider.bottom",
    ]);
    const left = all.find((s) => s.name === "header.left");
    expect(left).toMatchObject({
      kind: "fill",
      source: "p1",
      id: "a",
      order: 5,
    });
    const bottom = all.find((s) => s.name === "sider.bottom");
    expect(bottom).toMatchObject({
      kind: "replace",
      source: "p2",
      id: "b",
    });
  });

  it("snapshot of an empty registry is an empty list", () => {
    const slot = buildSlotNamespace();

    expect(slot.snapshot()).toEqual([]);
  });
});

describe("buildAuditNamespace", () => {
  it("overrides exposes the shared audit log", () => {
    const audit = buildAuditNamespace();
    expect(audit.overrides()).toEqual([]);
    const menu = buildMenuNamespace();
    menu.add("core", menuItem("core.target"));
    menu.replace("p1", "core.target", menuItem("x"));

    const records = audit.overrides();

    expect(records.length).toBeGreaterThan(0);
    expect(records.some((r) => r.pluginId === "p1")).toBe(true);
  });

  it("overrides returns a copy, so callers cannot mutate the log", () => {
    const audit = buildAuditNamespace();
    buildMenuNamespace().add("core", menuItem("core.target"));

    const first = audit.overrides();
    first.length = 0;

    expect(audit.overrides().length).toBeGreaterThan(0);
  });
});
