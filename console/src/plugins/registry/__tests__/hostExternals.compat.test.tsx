/**
 * hostExternals.compat.test.tsx — back-compat shim for legacy registerRoutes.
 *
 * Verifies that a call shaped like CloudPaw's existing one:
 *   window.QwenPaw.registerRoutes("cloudpaw", [{ path: "/a2a", ... }])
 *
 * translates into both:
 *   - routeRegistry entry under id `legacy:cloudpaw:a2a`
 *   - menuRegistry entry under parentId `plugins-group` in primary.settings
 *
 * And that the synthesized `plugins-group` parent exists.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { installHostExternals, pluginSystem } from "../../hostExternals";
import { menuRegistry, routeRegistry } from "../store";
import { auditStore } from "../audit";

function freshInstall() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).QwenPaw = undefined;
  menuRegistry.__resetForTests();
  routeRegistry.__resetForTests();
  pluginSystem.__resetForTests();
  auditStore.clear();
  installHostExternals();
}

const Comp = () => null;

beforeEach(() => {
  freshInstall();
});

describe("legacy registerRoutes shim", () => {
  it("attaches window.QwenPaw.{menu, route, slot, audit}", () => {
    expect(typeof window.QwenPaw.menu?.add).toBe("function");
    expect(typeof window.QwenPaw.route?.add).toBe("function");
    expect(typeof window.QwenPaw.slot?.fill).toBe("function");
    expect(typeof window.QwenPaw.audit?.overrides).toBe("function");
  });

  it("translates CloudPaw-shape registerRoutes into menu+route", () => {
    window.QwenPaw.registerRoutes!("cloudpaw", [
      {
        path: "/a2a",
        component: Comp,
        label: "A2A",
        icon: "🔗",
        priority: 10,
      },
    ]);

    const route = routeRegistry
      .snapshot()
      .find((r) => r.id === "legacy:cloudpaw:a2a");
    expect(route?.path).toBe("/a2a");

    const settings = menuRegistry.snapshot("primary.settings");
    const pluginsGroup = settings.find((i) => i.id === "plugins-group") as
      | { __children?: Array<{ id: string }> }
      | undefined;
    expect(pluginsGroup).toBeTruthy();
    expect(pluginsGroup?.__children?.map((c) => c.id)).toContain(
      "legacy:cloudpaw:a2a",
    );
  });

  it("multiple legacy registers share the synthesized plugins-group", () => {
    window.QwenPaw.registerRoutes!("p1", [
      { path: "/p1", component: Comp, label: "P1", icon: "1" },
    ]);
    window.QwenPaw.registerRoutes!("p2", [
      { path: "/p2", component: Comp, label: "P2", icon: "2" },
    ]);

    const settings = menuRegistry.snapshot("primary.settings");
    const groups = settings.filter((i) => i.id === "plugins-group");
    expect(groups).toHaveLength(1);
    const kids = (groups[0] as { __children?: Array<{ id: string }> })
      .__children;
    expect(kids?.map((c) => c.id)).toEqual(
      expect.arrayContaining(["legacy:p1:p1", "legacy:p2:p2"]),
    );
  });

  it("new QwenPaw.menu.add coexists with legacy in plugins-group", () => {
    window.QwenPaw.registerRoutes!("cloudpaw", [
      { path: "/a2a", component: Comp, label: "A2A", icon: "🔗" },
    ]);
    window.QwenPaw.menu!.add("newPlugin", {
      id: "newPlugin.foo",
      location: "primary.agentScoped",
      parentId: "core.agent-group",
      label: "Foo",
    });

    const settings = menuRegistry.snapshot("primary.settings");
    const pluginsGroup = settings.find((i) => i.id === "plugins-group") as
      | { __children?: Array<{ id: string }> }
      | undefined;
    expect(pluginsGroup?.__children?.map((c) => c.id)).toContain(
      "legacy:cloudpaw:a2a",
    );
    // newPlugin lives in primary.agentScoped, not settings
    expect(settings.find((i) => i.id === "newPlugin.foo")).toBeUndefined();
  });

  it("legacy registerToolRender still writes to pluginSystem", () => {
    const RenderFC = () => null;
    window.QwenPaw.registerToolRender!("p1", { my_tool: RenderFC });
    expect(pluginSystem.getToolRenderConfig().my_tool).toBe(RenderFC);
  });
});

describe("registerCommandSuggestions", () => {
  it("attaches window.QwenPaw.registerCommandSuggestions", () => {
    expect(typeof window.QwenPaw.registerCommandSuggestions).toBe("function");
  });

  it("registers command suggestions to pluginSystem", () => {
    window.QwenPaw.registerCommandSuggestions!("cloudpaw", [
      { command: "/a2a", description: "Call remote A2A agents" },
      { command: "/status", description: "Check agent status" },
    ]);
    const suggestions = pluginSystem.getCommandSuggestions();
    expect(suggestions).toHaveLength(2);
    expect(suggestions[0].command).toBe("/a2a");
    expect(suggestions[1].command).toBe("/status");
  });

  it("replaces same command instead of duplicating (language switch)", () => {
    window.QwenPaw.registerCommandSuggestions!("cloudpaw", [
      { command: "/a2a", description: "查看远程 A2A Agent" },
    ]);
    // Simulate language change
    window.QwenPaw.registerCommandSuggestions!("cloudpaw", [
      { command: "/a2a", description: "View remote A2A agents" },
    ]);
    const suggestions = pluginSystem.getCommandSuggestions();
    expect(suggestions).toHaveLength(1);
    expect(suggestions[0].description).toBe("View remote A2A agents");
  });

  it("multiple plugins register independently without conflict", () => {
    window.QwenPaw.registerCommandSuggestions!("pluginA", [
      { command: "/cmd-a", description: "Plugin A command" },
    ]);
    window.QwenPaw.registerCommandSuggestions!("pluginB", [
      { command: "/cmd-b", description: "Plugin B command" },
    ]);
    const suggestions = pluginSystem.getCommandSuggestions();
    expect(suggestions).toHaveLength(2);
    expect(suggestions.map((s) => s.command)).toContain("/cmd-a");
    expect(suggestions.map((s) => s.command)).toContain("/cmd-b");
  });

  it("subscribe fires on suggestion change", () => {
    let notifyCount = 0;
    pluginSystem.subscribe(() => {
      notifyCount++;
    });
    window.QwenPaw.registerCommandSuggestions!("p1", [
      { command: "/test", description: "test" },
    ]);
    expect(notifyCount).toBe(1);
  });
});
