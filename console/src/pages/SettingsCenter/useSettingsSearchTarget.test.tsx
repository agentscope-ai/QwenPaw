import { useRef, useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { createPortal } from "react-dom";
import { useSettingsSearchTarget } from "./useSettingsSearchTarget";

function SearchFixture() {
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  useSettingsSearchTarget(
    root,
    { page: "runtime", label: "Cache size" },
    "runtime",
  );
  return (
    <div ref={root}>
      <div className="ant-collapse-item">
        <div role="button" aria-expanded="false">
          Unrelated section
        </div>
        <span>Other setting</span>
      </div>
      <div className="ant-collapse-item">
        <div role="button" aria-expanded={open} onClick={() => setOpen(true)}>
          Cache
        </div>
        <div hidden={!open}>
          <label>Cache size</label>
          <input aria-label="Cache size" />
        </div>
      </div>
    </div>
  );
}

describe("settings search disclosure targeting", () => {
  beforeEach(() =>
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    }),
  );
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("highlights an accessible switch without changing its value", async () => {
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      {},
    ] as unknown as DOMRectList);
    const change = vi.fn();
    function Fixture() {
      const root = useRef<HTMLDivElement>(null);
      useSettingsSearchTarget(
        root,
        { page: "heartbeat", label: "Enable heartbeat" },
        "heartbeat",
      );
      return (
        <div ref={root}>
          <button
            role="switch"
            aria-label="Enable heartbeat"
            aria-checked="false"
            onClick={change}
          />
        </div>
      );
    }
    render(<Fixture />);
    await waitFor(() =>
      expect(screen.getByRole("switch")).toHaveAttribute(
        "data-search-highlight",
        "true",
      ),
    );
    expect(change).not.toHaveBeenCalled();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });

  it("locates a card title rendered as a div", async () => {
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      {},
    ] as unknown as DOMRectList);
    function Fixture() {
      const root = useRef<HTMLDivElement>(null);
      useSettingsSearchTarget(
        root,
        { page: "usage", label: "By model" },
        "usage",
      );
      return (
        <div ref={root}>
          <div className="qwenpaw-spark-title">By model</div>
        </div>
      );
    }
    render(<Fixture />);
    await waitFor(() =>
      expect(screen.getByText("By model")).toHaveAttribute(
        "data-search-highlight",
        "true",
      ),
    );
  });

  it("highlights a selected tab whose title is rendered without a span", async () => {
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      {},
    ] as unknown as DOMRectList);
    function Fixture() {
      const root = useRef<HTMLDivElement>(null);
      useSettingsSearchTarget(
        root,
        { page: "plugins", label: "Official plugins", tab: "Official plugins" },
        "plugins",
      );
      return (
        <div ref={root}>
          <div role="tab" aria-selected="true">
            Official plugins
          </div>
        </div>
      );
    }
    render(<Fixture />);
    await waitFor(() =>
      expect(screen.getByRole("tab")).toHaveAttribute(
        "data-search-highlight",
        "true",
      ),
    );
  });

  it("retargets a field that is replaced after its editor finishes loading", async () => {
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      {},
    ] as unknown as DOMRectList);
    const target = {
      page: "model",
      label: "Context length",
      targetId: "model.context",
      surface: "model",
    };
    function Fixture() {
      const root = useRef<HTMLDivElement>(null);
      const [revision, setRevision] = useState(0);
      useSettingsSearchTarget(root, target, "model");
      return (
        <div ref={root}>
          <button onClick={() => setRevision(revision + 1)}>
            Reload field
          </button>
          <label key={revision} data-settings-target="model.context">
            Context length
          </label>
        </div>
      );
    }
    render(<Fixture />);
    const first = screen.getByText("Context length");
    await waitFor(() =>
      expect(first).toHaveAttribute("data-search-highlight", "true"),
    );
    fireEvent.click(screen.getByText("Reload field"));
    await waitFor(() =>
      expect(screen.getByText("Context length")).toHaveAttribute(
        "data-search-highlight",
        "true",
      ),
    );
    expect(screen.getByText("Context length")).not.toBe(first);
  });

  it("keeps a pending target when the user opens its editor after five seconds", async () => {
    vi.useFakeTimers();
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      {},
    ] as unknown as DOMRectList);
    const target = {
      page: "model",
      label: "Context length",
      targetId: "model.context",
      surface: "model",
    };
    function Fixture() {
      const root = useRef<HTMLDivElement>(null);
      const [open, setOpen] = useState(false);
      useSettingsSearchTarget(root, target, "model");
      return (
        <div ref={root}>
          <button onClick={() => setOpen(true)}>Edit model</button>
          {open &&
            createPortal(
              <label data-settings-target="model.context">
                Context length
              </label>,
              document.body,
            )}
        </div>
      );
    }
    render(<Fixture />);
    await vi.advanceTimersByTimeAsync(6000);
    fireEvent.click(screen.getByText("Edit model"));
    await vi.advanceTimersByTimeAsync(100);
    expect(screen.getByText("Context length")).toHaveAttribute(
      "data-search-highlight",
      "true",
    );
  });

  it("opens an explicitly registered settings surface whose field is already mounted but hidden", async () => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      {},
    ] as unknown as DOMRectList);
    const save = vi.fn();
    const target = {
      page: "plugin",
      label: "Timeout",
      targetId: "plugin.timeout",
      surface: "plugin.advanced",
    };
    function SurfaceFixture() {
      const root = useRef<HTMLDivElement>(null);
      const [open, setOpen] = useState(false);
      useSettingsSearchTarget(root, target, "plugin");
      return (
        <div ref={root}>
          <button
            data-settings-open="plugin.advanced"
            aria-expanded={open}
            onClick={() => setOpen(true)}
          >
            Advanced settings
          </button>
          <div hidden={!open}>
            <label
              data-testid="hidden-field"
              data-settings-target="plugin.timeout"
            >
              Timeout
            </label>
            <button onClick={save}>Save</button>
          </div>
        </div>
      );
    }
    render(<SurfaceFixture />);
    await waitFor(() =>
      expect(screen.getByTestId("hidden-field")).toHaveAttribute(
        "data-search-highlight",
        "true",
      ),
    );
    expect(
      screen.getByRole("button", { name: "Advanced settings" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(save).not.toHaveBeenCalled();
  });

  it("waits for a portalled stable target instead of highlighting a search result with the same label", async () => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      {},
    ] as unknown as DOMRectList);
    function PortalFixture() {
      const root = useRef<HTMLDivElement>(null);
      const [open, setOpen] = useState(false);
      useSettingsSearchTarget(
        root,
        { page: "cron", label: "Execution model", targetId: "execution-model" },
        "cron",
      );
      return (
        <div ref={root}>
          <span data-testid="search-result">Execution model</span>
          <button onClick={() => setOpen(true)}>Edit task</button>
          {open &&
            createPortal(
              <div data-testid="field" data-settings-target="execution-model">
                <label>Execution model</label>
              </div>,
              document.body,
            )}
        </div>
      );
    }
    render(<PortalFixture />);
    expect(screen.getByTestId("search-result")).not.toHaveAttribute(
      "data-search-highlight",
    );
    screen.getByRole("button", { name: "Edit task" }).click();
    await waitFor(() =>
      expect(screen.getByTestId("field")).toHaveAttribute(
        "data-search-highlight",
        "true",
      ),
    );
  });
  it("opens the disclosure containing a matched field without opening unrelated sections", async () => {
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      {},
    ] as unknown as DOMRectList);
    render(<SearchFixture />);
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Cache" })
          .getAttribute("aria-expanded"),
      ).toBe("true"),
    );
    expect(
      screen
        .getByRole("button", { name: "Unrelated section" })
        .getAttribute("aria-expanded"),
    ).toBe("false");
    expect(screen.getByRole("textbox", { name: "Cache size" })).toBeTruthy();
  });
});
