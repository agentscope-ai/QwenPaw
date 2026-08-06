import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { useOsDock } from "./osDockStore";
import { useOsWindows } from "./osWindowStore";
import Dock from "./Dock";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", {
    value: 1440,
    configurable: true,
  });
  Object.defineProperty(window, "innerHeight", {
    value: 900,
    configurable: true,
  });
  useOsDock.setState({ pinned: ["core.chat", "core.inbox", "os.store"] });
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
  Object.defineProperty(document, "elementFromPoint", {
    value: vi.fn(() => null),
    configurable: true,
  });
  Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
    value: vi.fn(),
    configurable: true,
  });
  Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", {
    value: vi.fn(),
    configurable: true,
  });
});

describe("Dock drag cancellation", () => {
  it("does not suppress the next click after pointercancel", () => {
    renderWithProviders(<Dock />);
    const appStore = screen.getByRole("button", { name: "App Store" });

    fireEvent.pointerDown(appStore, { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(appStore, {
      pointerId: 1,
      clientX: 30,
      clientY: 10,
    });
    fireEvent.pointerCancel(appStore, {
      pointerId: 1,
      clientX: 30,
      clientY: 10,
    });
    fireEvent.click(appStore);

    expect(useOsWindows.getState().windows["os.store"]).toBeDefined();
  });

  it("cleans drag state when pointer capture is lost", () => {
    renderWithProviders(<Dock />);
    const appStore = screen.getByRole("button", { name: "App Store" });

    fireEvent.pointerDown(appStore, { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(appStore, {
      pointerId: 1,
      clientX: 30,
      clientY: 10,
    });
    fireEvent.lostPointerCapture(appStore, {
      pointerId: 1,
      clientX: 30,
      clientY: 10,
    });
    fireEvent.click(appStore);

    expect(useOsWindows.getState().windows["os.store"]).toBeDefined();
  });

  it("suppresses only the compatibility click after a completed drag", () => {
    renderWithProviders(<Dock />);
    const appStore = screen.getByRole("button", { name: "App Store" });

    fireEvent.pointerDown(appStore, { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(appStore, {
      pointerId: 1,
      clientX: 30,
      clientY: 10,
    });
    fireEvent.pointerUp(appStore, {
      pointerId: 1,
      clientX: 30,
      clientY: 10,
    });
    fireEvent.click(appStore);
    expect(useOsWindows.getState().windows["os.store"]).toBeUndefined();

    fireEvent.click(appStore);
    expect(useOsWindows.getState().windows["os.store"]).toBeDefined();
  });
});
