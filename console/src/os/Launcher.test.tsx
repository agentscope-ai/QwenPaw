import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppWindow } from "lucide-react";
import { renderWithProviders } from "@/test/common_setup";
import { useOsWindows } from "./osWindowStore";
import Launcher from "./Launcher";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

const APPS = [
  {
    routeId: "core.first",
    labelKey: "first",
    fallback: "First App",
    Icon: AppWindow,
    accent: "#ff7f16",
    defaultW: 820,
    defaultH: 580,
  },
  {
    routeId: "core.second",
    labelKey: "second",
    fallback: "Second App",
    Icon: AppWindow,
    accent: "#3b82f6",
    defaultW: 820,
    defaultH: 580,
  },
];

describe("Launcher", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", {
      value: 1440,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      value: 900,
      configurable: true,
      writable: true,
    });
    useOsWindows.setState({
      windows: {},
      order: [],
      activeId: null,
      zCounter: 100,
      launcherOpen: true,
      spaceId: "default",
      saved: {},
      missionControlOpen: false,
    });
  });

  it("opens the first filtered app when Enter is pressed in search", () => {
    renderWithProviders(<Launcher apps={APPS} />);

    const search = screen.getByRole("textbox", { name: "Search apps..." });
    fireEvent.change(search, { target: { value: "second" } });
    fireEvent.keyDown(search, { key: "Enter" });

    expect(useOsWindows.getState().windows["core.second"]).toBeDefined();
    expect(useOsWindows.getState().launcherOpen).toBe(false);
  });

  it("closes without opening an app when Escape is pressed", () => {
    renderWithProviders(<Launcher apps={APPS} />);

    fireEvent.keyDown(window, { key: "Escape" });

    expect(useOsWindows.getState().launcherOpen).toBe(false);
    expect(useOsWindows.getState().order).toEqual([]);
  });
});
