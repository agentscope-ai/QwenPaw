import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RouteDocumentTitle } from "./RouteDocumentTitle";
import { getRouteTitle } from "./routeTitle";

describe("RouteDocumentTitle", () => {
  it("updates the browser title when the active route changes", () => {
    const { rerender } = render(<RouteDocumentTitle title="Chat" />);
    expect(document.title).toBe("Chat · QwenPaw");

    rerender(<RouteDocumentTitle title="Models" />);
    expect(document.title).toBe("Models · QwenPaw");
  });
});

describe("getRouteTitle", () => {
  it("resolves localized route metadata", () => {
    expect(
      getRouteTitle(
        {
          id: "plugin.page",
          path: "/plugin",
          meta: {
            domain: "extensions",
            title: (locale) => (locale === "zh" ? "插件" : "Plugin"),
            scope: "global",
            layout: "standard",
            navigation: "context",
          },
        },
        "zh",
      ),
    ).toBe("插件");
  });

  it("uses a safe title for legacy plugin routes", () => {
    expect(
      getRouteTitle({ id: "plugin.audit-log", path: "/audit-log" }, "en"),
    ).toBe("Audit Log");
  });
});
