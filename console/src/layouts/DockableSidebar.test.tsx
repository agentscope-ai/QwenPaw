import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useEffect } from "react";
import DockableSidebar from "./DockableSidebar";
import { constrainSidebar } from "./sidebarPlacement";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (_key: string, fallback: string) => fallback }),
}));
const preference = vi.hoisted(() => ({ reduced: false }));
vi.mock("motion/react", async (original) => ({
  ...(await original<typeof import("motion/react")>()),
  useReducedMotion: () => preference.reduced,
}));
const handleName = "Drag sidebar to float; Enter to toggle docking";
const placement = () => document.querySelector("[data-sidebar-placement]");
class TestPointerEvent extends MouseEvent {
  pointerId: number;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}
beforeEach(() => {
  preference.reduced = false;
  vi.stubGlobal("PointerEvent", TestPointerEvent);
  vi.stubGlobal("innerWidth", 1280);
  vi.stubGlobal("innerHeight", 900);
  HTMLElement.prototype.setPointerCapture = vi.fn();
  HTMLElement.prototype.releasePointerCapture = vi.fn();
  HTMLElement.prototype.hasPointerCapture = vi.fn(() => true);
});
afterEach(() => vi.unstubAllGlobals());
function drag(dx: number, dy: number, end = true) {
  const handle = screen.getByRole("button", { name: handleName });
  fireEvent.pointerDown(handle, {
    pointerId: 1,
    button: 0,
    clientX: 140,
    clientY: 12,
  });
  fireEvent.pointerMove(handle, {
    pointerId: 1,
    clientX: 140 + dx,
    clientY: 12 + dy,
  });
  if (end)
    fireEvent.pointerUp(handle, {
      pointerId: 1,
      clientX: 140 + dx,
      clientY: 12 + dy,
    });
  return handle;
}
describe("DockableSidebar", () => {
  it("keeps the mobile rail width and dismisses its overlay", () => {
    const close = vi.fn();
    render(
      <DockableSidebar width={240} mobile onMobileDismiss={close}>
        <span>Sidebar</span>
      </DockableSidebar>,
    );
    expect(placement()).toHaveStyle({ width: "56px" });
    fireEvent.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(close).toHaveBeenCalledOnce();
  });
  it("bounds a floating panel inside the available viewport", () => {
    expect(
      constrainSidebar(
        { x: 2000, y: -100 },
        { width: 280, height: 720 },
        { width: 1280, height: 900 },
      ),
    ).toEqual({ x: 988, y: 12 });
    expect(
      constrainSidebar(
        { x: 100, y: 100 },
        { width: 280, height: 720 },
        { width: 300, height: 500 },
      ),
    ).toEqual({ x: 12, y: 12 });
  });
  it("ignores clicks and short moves, detaches on deliberate drag and docks at the edge", async () => {
    render(
      <DockableSidebar width={280} mobile={false}>
        <input aria-label="Plugin state" />
      </DockableSidebar>,
    );
    drag(3, 2);
    expect(placement()).toHaveAttribute("data-sidebar-placement", "docked");
    drag(240, 90);
    expect(placement()).toHaveAttribute("data-sidebar-placement", "floating");
    const handle = screen.getByRole("button", { name: handleName });
    fireEvent.pointerDown(handle, {
      pointerId: 1,
      button: 0,
      clientX: 380,
      clientY: 102,
    });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 15, clientY: 110 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 15, clientY: 110 });
    expect(placement()).toHaveAttribute("data-sidebar-landing", "true");
    await waitFor(
      () =>
        expect(placement()).toHaveAttribute("data-sidebar-placement", "docked"),
      { timeout: 2000 },
    );
  });
  it("returns immediately when reduced motion is requested", () => {
    preference.reduced = true;
    render(
      <DockableSidebar width={280} mobile={false}>
        <span>Sidebar</span>
      </DockableSidebar>,
    );
    const handle = screen.getByRole("button", { name: handleName });
    fireEvent.keyDown(handle, { key: "Enter" });
    expect(placement()).toHaveAttribute("data-sidebar-placement", "floating");
    fireEvent.keyDown(handle, { key: "Enter" });
    expect(placement()).toHaveAttribute("data-sidebar-placement", "docked");
    expect(placement()).not.toHaveAttribute("data-sidebar-landing");
  });
  it("can grab a landing panel again without completing the old return", async () => {
    render(
      <DockableSidebar width={280} mobile={false}>
        <input aria-label="Plugin state" />
      </DockableSidebar>,
    );
    const handle = screen.getByRole("button", { name: handleName });
    fireEvent.keyDown(handle, { key: "Enter" });
    fireEvent.click(
      screen.getByRole("button", { name: "Return sidebar to left edge" }),
    );
    expect(placement()).toHaveAttribute("data-sidebar-landing", "true");
    drag(200, 50);
    expect(placement()).not.toHaveAttribute("data-sidebar-landing");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 800));
    });
    expect(placement()).toHaveAttribute("data-sidebar-placement", "floating");
    fireEvent.click(
      screen.getByRole("button", { name: "Return sidebar to left edge" }),
    );
    await waitFor(
      () =>
        expect(placement()).toHaveAttribute("data-sidebar-placement", "docked"),
      { timeout: 2000 },
    );
  });
  it("preserves plugin instances and input on detach/return", () => {
    const mount = vi.fn(),
      unmount = vi.fn();
    function Plugin() {
      useEffect(() => {
        mount();
        return unmount;
      }, []);
      return <input aria-label="Plugin state" />;
    }
    render(
      <DockableSidebar width={280} mobile={false}>
        <Plugin />
      </DockableSidebar>,
    );
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "unsaved" } });
    drag(230, 60);
    fireEvent.click(
      screen.getByRole("button", { name: "Return sidebar to left edge" }),
    );
    expect(screen.getByRole("textbox")).toBe(input);
    expect(input).toHaveValue("unsaved");
    expect(mount).toHaveBeenCalledTimes(1);
    expect(unmount).not.toHaveBeenCalled();
  });
  it("cancels an unfinished drag with Escape or pointer cancellation", () => {
    render(
      <DockableSidebar width={280} mobile={false}>
        <span>Sidebar</span>
      </DockableSidebar>,
    );
    drag(200, 70, false);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(placement()).toHaveAttribute("data-sidebar-placement", "docked");
    const handle = drag(160, 50, false);
    fireEvent.pointerCancel(handle, { pointerId: 1 });
    expect(placement()).toHaveAttribute("data-sidebar-placement", "docked");
  });
  it("supports keyboard positioning, clamps on resize and docks on mobile", async () => {
    const view = render(
      <DockableSidebar width={280} mobile={false}>
        <span>Sidebar</span>
      </DockableSidebar>,
    );
    const handle = screen.getByRole("button", { name: handleName });
    fireEvent.keyDown(handle, { key: "Enter" });
    fireEvent.keyDown(handle, { key: "ArrowRight", shiftKey: true });
    expect(placement()).toHaveAttribute("data-sidebar-placement", "floating");
    act(() => {
      vi.stubGlobal("innerWidth", 800);
      vi.stubGlobal("innerHeight", 500);
      window.dispatchEvent(new Event("resize"));
    });
    await waitFor(() =>
      expect(placement()?.getAttribute("style")).toContain("12px"),
    );
    view.rerender(
      <DockableSidebar width={240} mobile>
        <span>Sidebar</span>
      </DockableSidebar>,
    );
    expect(placement()).toHaveAttribute("data-sidebar-placement", "docked");
    expect(
      screen.queryByRole("button", { name: handleName }),
    ).not.toBeInTheDocument();
  });
});
