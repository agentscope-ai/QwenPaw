/**
 * routes.test.tsx — RouteRegistry behaviour.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { routeRegistry } from "../store";
import { auditStore } from "../audit";

const Base = () => <div data-testid="base">base</div>;
const PluginPage = () => <div data-testid="plugin">plugin</div>;

beforeEach(() => {
  routeRegistry.__resetForTests();
  auditStore.clear();
});

describe("routeRegistry.add", () => {
  it("keeps legacy routes without metadata compatible", () => {
    routeRegistry.add("core", { id: "r1", path: "/r1", component: Base });
    const snap = routeRegistry.snapshot();
    expect(snap.map((r) => r.id)).toContain("r1");
    expect(snap[0].meta).toBeUndefined();
  });

  it("keeps metadata on the resolved route", () => {
    routeRegistry.add("core", {
      id: "r1",
      path: "/r1",
      component: Base,
      meta: {
        domain: "workspace",
        title: "Files",
        scope: "agent",
        layout: "workbench",
        navigation: "context",
      },
    });

    expect(routeRegistry.snapshot()[0].meta).toEqual({
      domain: "workspace",
      title: "Files",
      scope: "agent",
      layout: "workbench",
      navigation: "context",
    });
  });

  it("rejects duplicate id with conflict audit", () => {
    routeRegistry.add("core", { id: "r1", path: "/a", component: Base });
    routeRegistry.add("p1", { id: "r1", path: "/b", component: Base });
    expect(routeRegistry.snapshot().filter((r) => r.id === "r1")).toHaveLength(
      1,
    );
    expect(
      auditStore.overrides().some((r) => r.kind === "route.conflict"),
    ).toBe(true);
  });

  it("rejects duplicate path with conflict audit", () => {
    routeRegistry.add("core", { id: "r1", path: "/x", component: Base });
    routeRegistry.add("p1", { id: "r2", path: "/x", component: Base });
    expect(routeRegistry.snapshot().map((r) => r.path)).toEqual(["/x"]);
    expect(
      auditStore
        .overrides()
        .some((r) => r.kind === "route.conflict" && r.targetId === "r2"),
    ).toBe(true);
  });
});

describe("routeRegistry.replace", () => {
  it("LIFO winner; rendered Component reflects override", () => {
    routeRegistry.add("core", { id: "p", path: "/p", component: Base });
    routeRegistry.replace("p1", "p", PluginPage);
    const Comp = routeRegistry.snapshot().find((r) => r.id === "p")?.Component!;
    expect(Comp).toBeTruthy();
    const { getByTestId } = render(<Comp />);
    expect(getByTestId("plugin")).toBeInTheDocument();
  });

  it("dispose restores base", () => {
    routeRegistry.add("core", { id: "p", path: "/p", component: Base });
    const d = routeRegistry.replace("p1", "p", PluginPage);
    d.dispose();
    const Comp = routeRegistry.snapshot().find((r) => r.id === "p")?.Component!;
    const { getByTestId } = render(<Comp />);
    expect(getByTestId("base")).toBeInTheDocument();
  });

  it("preserves base metadata when a plugin replaces the component", () => {
    const meta = {
      domain: "settings" as const,
      title: "Models",
      scope: "global" as const,
      layout: "standard" as const,
      navigation: "settings" as const,
    };
    routeRegistry.add("core", {
      id: "p",
      path: "/p",
      component: Base,
      meta,
    });

    routeRegistry.replace("p1", "p", PluginPage);

    expect(routeRegistry.snapshot()[0].meta).toBe(meta);
  });
});

describe("routeRegistry.wrap — onion composition", () => {
  it("later wrap is outermost", () => {
    routeRegistry.add("core", { id: "p", path: "/p", component: Base });
    routeRegistry.wrap("p1", "p", (Inner) => () => (
      <div data-testid="outer-p1">
        <Inner />
      </div>
    ));
    routeRegistry.wrap("p2", "p", (Inner) => () => (
      <div data-testid="outer-p2">
        <Inner />
      </div>
    ));
    const Comp = routeRegistry.snapshot().find((r) => r.id === "p")?.Component!;
    const { getByTestId, container } = render(<Comp />);
    // p2 should wrap p1 (p2 is last registered → outermost)
    const outerP2 = getByTestId("outer-p2");
    const outerP1 = getByTestId("outer-p1");
    expect(outerP2.contains(outerP1)).toBe(true);
    expect(container.querySelector("[data-testid='base']")).toBeInTheDocument();
  });

  it("replace + wrap: wrap sees the override, not the base", () => {
    routeRegistry.add("core", { id: "p", path: "/p", component: Base });
    routeRegistry.replace("p1", "p", PluginPage);
    routeRegistry.wrap("p2", "p", (Inner) => () => (
      <div data-testid="wrap">
        <Inner />
      </div>
    ));
    const Comp = routeRegistry.snapshot().find((r) => r.id === "p")?.Component!;
    const { queryByTestId } = render(<Comp />);
    expect(queryByTestId("wrap")).toBeInTheDocument();
    expect(queryByTestId("plugin")).toBeInTheDocument();
    expect(queryByTestId("base")).not.toBeInTheDocument();
  });

  it("disposing wrap removes it from chain", () => {
    routeRegistry.add("core", { id: "p", path: "/p", component: Base });
    const d = routeRegistry.wrap("p1", "p", (Inner) => () => (
      <div data-testid="wrap">
        <Inner />
      </div>
    ));
    d.dispose();
    const Comp = routeRegistry.snapshot().find((r) => r.id === "p")?.Component!;
    const { queryByTestId } = render(<Comp />);
    expect(queryByTestId("wrap")).not.toBeInTheDocument();
    expect(queryByTestId("base")).toBeInTheDocument();
  });

  it("preserves base metadata when plugins wrap the component", () => {
    const meta = {
      domain: "chat" as const,
      title: "Chat",
      scope: "session" as const,
      layout: "workbench" as const,
      navigation: "rail" as const,
    };
    routeRegistry.add("core", {
      id: "p",
      path: "/p",
      component: Base,
      meta,
    });

    routeRegistry.wrap("p1", "p", (Inner) => Inner);

    expect(routeRegistry.snapshot()[0].meta).toBe(meta);
  });
});

describe("routeRegistry.removeBySource", () => {
  it("removes base, replacement and wrapper registrations", () => {
    routeRegistry.add("plugin", {
      id: "plugin-page",
      path: "/plugin",
      component: PluginPage,
    });
    routeRegistry.add("core", { id: "core-page", path: "/", component: Base });
    routeRegistry.replace("plugin", "core-page", PluginPage);
    routeRegistry.wrap("plugin", "core-page", (Inner) => () => (
      <div data-testid="wrap">
        <Inner />
      </div>
    ));

    routeRegistry.removeBySource("plugin");

    expect(routeRegistry.snapshot().map((route) => route.id)).toEqual([
      "core-page",
    ]);
    const Component = routeRegistry.snapshot()[0].Component;
    const { queryByTestId } = render(<Component />);
    expect(queryByTestId("base")).toBeInTheDocument();
    expect(queryByTestId("plugin")).not.toBeInTheDocument();
    expect(queryByTestId("wrap")).not.toBeInTheDocument();
  });
});
