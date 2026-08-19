import { beforeEach, describe, expect, it } from "vitest";
import { useOsRoute } from "./osRouteStore";
import { useOsWindows } from "./osWindowStore";

function resetStores(): void {
  useOsRoute.setState({ targets: {} });
  useOsWindows.setState({
    windows: {},
    order: [],
    activeId: null,
    zCounter: 100,
    launcherOpen: false,
    spaceId: "default",
    saved: {},
    missionControlOpen: false,
  });
}

describe("osRouteStore", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", {
      value: 1440,
      configurable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      value: 900,
      configurable: true,
    });
    resetStores();
  });

  it("keeps the source window for normal cross-app navigation", () => {
    useOsWindows.getState().open("core.chat");

    useOsRoute.getState().navigateTo("core.inbox", "/inbox");

    expect(useOsWindows.getState().windows["core.chat"]).toBeDefined();
    expect(useOsWindows.getState().windows["core.inbox"]).toBeDefined();
  });
});
