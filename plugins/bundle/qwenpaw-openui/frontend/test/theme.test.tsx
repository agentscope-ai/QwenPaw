import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ThemeProvider, useTheme } from "@openuidev/react-ui";
import { useOpenUITheme } from "../src/theme";
import { OpenUIBlock } from "../src/OpenUIBlock";

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("style");
  vi.restoreAllMocks();
});

function FontProbe() {
  const { theme } = useTheme();
  return <output>{theme.textLabelXs}</output>;
}

function ThemeProbe() {
  const themes = useOpenUITheme();
  return (
    <ThemeProvider {...themes} cssSelector=".qwenpaw-openui">
      <FontProbe />
    </ThemeProvider>
  );
}

it("updates both CSS and chart measurement fonts for all blocks through one shared observer", async () => {
  const observe = vi.spyOn(MutationObserver.prototype, "observe");
  const disconnect = vi.spyOn(MutationObserver.prototype, "disconnect");
  const first = render(<ThemeProbe />);
  const second = render(<ThemeProbe />);
  expect(observe).toHaveBeenCalledTimes(1);
  await act(async () => {
    document.documentElement.style.setProperty("--app-font-scale", "1.429");
  });
  for (const output of screen.getAllByRole("status")) {
    expect(output.textContent).toContain("17.148px/1.25 system-ui");
  }
  for (const style of document.querySelectorAll("style[data-openui-theme]")) {
    expect(style.textContent).toContain(
      "--openui-text-label-xs: 400 17.148px/1.25 system-ui",
    );
    expect(style.textContent).toContain("var(--app-surface,");
    expect(style.textContent).toContain(".openui-theme-portal-");
    expect(style.textContent).not.toContain('"Inter"');
  }
  first.unmount();
  expect(disconnect).not.toHaveBeenCalled();
  second.unmount();
  expect(disconnect).toHaveBeenCalledTimes(1);
  expect(document.querySelector("style[data-openui-theme]")).toBeNull();
  expect(document.querySelector("style[data-qwenpaw-openui-font]")).toBeNull();
});

it("preserves input, focus and node identity through mode, accent, font and streaming changes", async () => {
  let mode = "light";
  const submit = vi.fn();
  Object.assign(window, {
    QwenPaw: {
      host: {
        useTheme: () => mode,
        useLocale: () => "en",
      },
      chat: { submit },
    },
  });
  const source =
    'root = Stack([input, later])\ninput = Input("name", "Your name")\n';
  const props = {
    source,
    isStreaming: true,
    language: "openui-lang",
    messageId: "m",
    blockId: "m:0",
    agentId: "a",
    sessionId: "s",
    fallback: () => null,
  };
  const view = render(<OpenUIBlock {...props} />);
  const input = screen.getByPlaceholderText("Your name") as HTMLInputElement;
  fireEvent.change(input, { target: { value: "Ada" } });
  expect(input.disabled).toBe(true);
  mode = "dark";
  await act(async () => {
    document.documentElement.style.setProperty("--app-font-scale", "1.25");
    document.documentElement.style.setProperty("--app-accent", "#007766");
  });
  view.rerender(
    <OpenUIBlock
      {...props}
      source={source + 'later = TextContent("Ready")'}
      isStreaming={false}
    />,
  );
  await waitFor(() => {
    expect(
      document.querySelector("style[data-openui-theme]")?.textContent,
    ).toContain("400 17.5px/1.5 system-ui");
  });
  expect(screen.getByPlaceholderText("Your name")).toBe(input);
  expect(input.value).toBe("Ada");
  input.focus();
  await act(async () => {
    document.documentElement.style.setProperty("--app-font-scale", "1");
  });
  expect(document.activeElement).toBe(input);
  expect(submit).not.toHaveBeenCalled();
});
