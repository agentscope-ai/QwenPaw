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
import { installHostExternals } from "../../hostExternals";
import { menuRegistry, routeRegistry } from "../store";
import { auditStore } from "../audit";

function freshInstall() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).QwenPaw = undefined;
  menuRegistry.__resetForTests();
  routeRegistry.__resetForTests();
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

  it("legacy registerToolRender still writes to pluginSystem", async () => {
    const { pluginSystem } = await import("../../hostExternals");
    const RenderFC = () => null;
    window.QwenPaw.registerToolRender!("p1", { my_tool: RenderFC });
    expect(pluginSystem.getToolRenderConfig().my_tool).toBe(RenderFC);
  });
});

describe("localized legacy route declarations", () => {
  it("uses live Console locale for labels even when browser locale differs", async () => {
    const { default: i18n } = await import("../../../i18n");
    const { resolveLabel } = await import("../../../layouts/registry/adapter");
    const { render, screen, act } = await import("@testing-library/react");
    const { useTranslation } = await import("react-i18next");
    const browserLocale = Object.getOwnPropertyDescriptor(
      navigator,
      "language",
    );
    Object.defineProperty(navigator, "language", {
      configurable: true,
      value: "zh-CN",
    });
    await i18n.changeLanguage("en");
    window.QwenPaw.registerRoutes!("locale-author", [
      {
        path: "/plugin/locale-author/workspace",
        component: Comp,
        label: (locale) => (locale.startsWith("zh") ? "工作区" : "Workspace"),
      },
    ]);
    const group = menuRegistry
      .snapshot("primary.settings")
      .find(
        (item) => item.id === "plugins-group",
      ) as import("../types").MenuItem & {
      __children: import("../types").MenuItem[];
    };
    const item = group.__children.find(
      (entry) =>
        entry.id === "legacy:locale-author:plugin/locale-author/workspace",
    )!;
    const firstSnapshot = routeRegistry.snapshot();
    function Consumer() {
      useTranslation();
      return (
        <div data-testid="plugin-menu-label">{resolveLabel(item.label)}</div>
      );
    }
    const view = render(<Consumer />);
    try {
      expect(screen.getByTestId("plugin-menu-label").textContent).toBe(
        "Workspace",
      );
      await act(async () => {
        await i18n.changeLanguage("zh");
      });
      expect(screen.getByTestId("plugin-menu-label").textContent).toBe(
        "工作区",
      );
      await act(async () => {
        await i18n.changeLanguage("en");
      });
      expect(screen.getByTestId("plugin-menu-label").textContent).toBe(
        "Workspace",
      );
      expect(routeRegistry.snapshot()).toEqual(firstSnapshot);
    } finally {
      view.unmount();
      if (browserLocale)
        Object.defineProperty(navigator, "language", browserLocale);
      else Reflect.deleteProperty(navigator, "language");
    }
  });

  it("passes localized titles to the real route title and document consumers", async () => {
    const { default: i18n } = await import("../../../i18n");
    const { getRouteTitle } = await import(
      "../../../layouts/MainLayout/routeTitle"
    );
    const { RouteDocumentTitle } = await import(
      "../../../layouts/MainLayout/RouteDocumentTitle"
    );
    const { render, screen, act } = await import("@testing-library/react");
    const { useTranslation } = await import("react-i18next");
    await i18n.changeLanguage("en");
    window.QwenPaw.registerRoutes!("locale-author", [
      {
        path: "/plugin/locale-author/workspace",
        component: Comp,
        label: "Static menu",
        title: (locale) =>
          locale.startsWith("zh") ? "作者工作区" : "Author workspace",
      },
    ]);
    const route = routeRegistry
      .snapshot()
      .find(
        (entry) =>
          entry.id === "legacy:locale-author:plugin/locale-author/workspace",
      )!;
    function Consumer() {
      const { i18n: current } = useTranslation();
      const title = getRouteTitle(route, current.language);
      return (
        <>
          <h1>{title}</h1>
          <RouteDocumentTitle title={title} />
        </>
      );
    }
    const view = render(<Consumer />);
    try {
      expect(screen.getByRole("heading").textContent).toBe("Author workspace");
      expect(document.title).toBe("Author workspace · QwenPaw");
      await act(async () => {
        await i18n.changeLanguage("zh");
      });
      expect(screen.getByRole("heading").textContent).toBe("作者工作区");
      expect(document.title).toBe("作者工作区 · QwenPaw");
    } finally {
      view.unmount();
      await i18n.changeLanguage("en");
    }
  });

  it("preserves old string labels and absent-title route fallback", async () => {
    const { default: i18n } = await import("../../../i18n");
    const { resolveLabel } = await import("../../../layouts/registry/adapter");
    const { getRouteTitle } = await import(
      "../../../layouts/MainLayout/routeTitle"
    );
    window.QwenPaw.registerRoutes!("old-author", [
      {
        path: "/plugin/old-author/audit-log",
        component: Comp,
        label: "Original label",
      },
    ]);
    const route = routeRegistry
      .snapshot()
      .find(
        (entry) => entry.id === "legacy:old-author:plugin/old-author/audit-log",
      )!;
    const group = menuRegistry
      .snapshot("primary.settings")
      .find(
        (item) => item.id === "plugins-group",
      ) as import("../types").MenuItem & {
      __children: import("../types").MenuItem[];
    };
    const item = group.__children.find((entry) => entry.id === route.id)!;
    expect(route.meta).toBeUndefined();
    for (const locale of ["en", "zh"]) {
      await i18n.changeLanguage(locale);
      expect(item.label).toBe("Original label");
      expect(resolveLabel(item.label)).toBe("Original label");
      expect(getRouteTitle(route, locale)).toBe("Audit Log");
    }
    await i18n.changeLanguage("en");
  });
});
