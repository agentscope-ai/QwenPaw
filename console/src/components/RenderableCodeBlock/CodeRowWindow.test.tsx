import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RenderableCodeBlock } from "./RenderableCodeBlock";
import { CODE_ROW_LIMIT } from "./CodeRowWindow";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../MermaidCodeBlock", () => ({ MermaidCodeBlock: () => null }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("bounds mounted lines, preserves multiline tokens and copies the full source", async () => {
  const frames: FrameRequestCallback[] = [];
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) => {
    frames.push(fn);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  let top = 0;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      return {
        top: this.hasAttribute("data-code-row-window") ? -top : 0,
        bottom: 800,
        height: 800,
        width: 900,
        left: 0,
        right: 900,
        x: 0,
        y: 0,
        toJSON() {},
      };
    },
  );
  const source =
    "/*\n" +
    Array.from(
      { length: 2400 },
      (_, i) => `line ${i}: this is a multiline comment`,
    ).join("\n") +
    "\n*/\nconst finalValue = 42;\n";
  const view = render(
    <div data-history-message-window>
      <RenderableCodeBlock block lang="javascript" virtualize>
        {source}
      </RenderableCodeBlock>
    </div>,
  );
  await waitFor(() =>
    expect(view.container.querySelectorAll("[data-code-line]")).toHaveLength(
      CODE_ROW_LIMIT,
    ),
  );
  expect(
    view.container.querySelector(
      '[data-code-line="2"] [style*="font-style: italic"]',
    ),
  ).not.toBeNull();
  top = 2400 * 21.45;
  fireEvent.scroll(view.container.firstElementChild!);
  act(() => {
    frames.splice(0).forEach((fn) => fn(0));
  });
  expect(view.container.querySelectorAll("[data-code-line]")).toHaveLength(
    CODE_ROW_LIMIT,
  );
  expect(view.container.textContent).toContain("const finalValue = 42;");
  expect(
    view.container.querySelector(
      '[data-code-line="2401"] [style*="font-style: italic"]',
    ),
  ).not.toBeNull();
  const copy = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(window, "isSecureContext", {
    configurable: true,
    value: true,
  });
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: copy },
  });
  await act(async () =>
    fireEvent.click(view.getByRole("button", { name: "common.copy" })),
  );
  expect(copy).toHaveBeenCalledWith(source);
});
