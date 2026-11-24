// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { pickSelectedKey } from "./routeSelection";

const EmptyPage = () => null;

describe("pickSelectedKey", () => {
  it("uses React Router precedence for a plugin route under /settings", () => {
    const routes = [
      {
        id: "core.settings-center",
        path: "/settings/*",
        source: "core",
        Component: EmptyPage,
      },
      {
        id: "plugin.account-settings",
        path: "/settings/account",
        source: "plugin",
        Component: EmptyPage,
      },
    ];

    expect(pickSelectedKey("/settings/account", routes)).toBe(
      "plugin.account-settings",
    );
    expect(pickSelectedKey("/settings/general", routes)).toBe(
      "core.settings-center",
    );
  });

  it("falls back to chat when no registered route matches", () => {
    expect(pickSelectedKey("/missing", [])).toBe("core.chat");
  });

  it("honors case-sensitive route metadata", () => {
    const routes = [
      {
        id: "core.acp",
        path: "/acp",
        caseSensitive: true,
      },
      {
        id: "core.acp-alias",
        path: "/ACP",
      },
    ];

    expect(pickSelectedKey("/acp", routes)).toBe("core.acp");
    expect(pickSelectedKey("/ACP", routes)).toBe("core.acp-alias");
  });
});
