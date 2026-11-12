import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { setConsoleTitlePreference } from "@/utils/consoleTitlePreference";
import { RouteDocumentTitle } from "./RouteDocumentTitle";
import { getRouteTitle } from "./routeTitle";

describe("RouteDocumentTitle", () => {
  beforeEach(() => {
    localStorage.removeItem("qwenpaw_console_title");
  });

  it("updates the browser title when the active route changes", () => {
    const { rerender } = render(<RouteDocumentTitle title="Chat" />);
    expect(document.title).toBe("Chat · QwenPaw");

    rerender(<RouteDocumentTitle title="Models" />);
    expect(document.title).toBe("Models · QwenPaw");
  });

  it("uses the browser-local title across route changes and restores route titles when cleared", () => {
    localStorage.setItem("qwenpaw_console_title", "Project Alpha");
    const { rerender } = render(<RouteDocumentTitle title="Chat" />);
    expect(document.title).toBe("Project Alpha");

    rerender(<RouteDocumentTitle title="Models" />);
    expect(document.title).toBe("Project Alpha");

    act(() => setConsoleTitlePreference("Project Beta"));
    expect(document.title).toBe("Project Beta");

    act(() => setConsoleTitlePreference(""));
    expect(document.title).toBe("Models · QwenPaw");
  });

  it("synchronizes another tab's title update and clearing", () => {
    render(<RouteDocumentTitle title="Chat" />);

    act(() => {
      localStorage.setItem("qwenpaw_console_title", "Other Tab");
      window.dispatchEvent(
        Object.assign(new Event("storage"), {
          key: "qwenpaw_console_title",
          storageArea: localStorage,
        }),
      );
    });
    expect(document.title).toBe("Other Tab");

    act(() => {
      localStorage.clear();
      window.dispatchEvent(
        Object.assign(new Event("storage"), {
          key: null,
          storageArea: localStorage,
        }),
      );
    });
    expect(document.title).toBe("Chat · QwenPaw");
  });

  it("falls back to the route title when browser storage is unavailable", () => {
    const getItem = localStorage.getItem;
    localStorage.getItem = () => {
      throw new DOMException("Storage blocked", "SecurityError");
    };
    try {
      render(<RouteDocumentTitle title="Chat" />);
      expect(document.title).toBe("Chat · QwenPaw");
    } finally {
      localStorage.getItem = getItem;
    }
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
