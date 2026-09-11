import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { useOsWindows } from "./osWindowStore";
import { useOsAppLauncher } from "./useOsAppLauncher";

function Harness() {
  const launchApp = useOsAppLauncher();
  return (
    <button type="button" onClick={() => void launchApp("plugin.kanban")}>
      Open Kanban
    </button>
  );
}

describe("useOsAppLauncher", () => {
  beforeEach(() => {
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
    Object.defineProperty(window, "innerWidth", {
      value: 1440,
      configurable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      value: 900,
      configurable: true,
    });
  });

  it("opens a PawApp window", () => {
    renderWithProviders(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Open Kanban" }));

    expect(useOsWindows.getState().windows["plugin.kanban"]).toBeDefined();
  });
});
