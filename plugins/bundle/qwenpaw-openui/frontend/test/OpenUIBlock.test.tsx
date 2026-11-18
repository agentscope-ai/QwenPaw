import React from "react";
import { readFileSync } from "node:fs";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createParser } from "@openuidev/react-lang";
import { openuiLibrary } from "@openuidev/react-ui";
import { OpenUIBlock } from "../src/OpenUIBlock";
import { streamingLibrary } from "../src/library";
import { actionMessage, dispatchAction } from "../src/actions";
import type { QwenPawWindowNamespace } from "../src/qwenpaw-host";

const source = readFileSync("../examples/seeds.openui", "utf8");
let mode: "light" | "dark" = "light";
const submit = vi.fn(async () => {});
const openExternalLink = vi.fn();
const api = {
  chat: { submit },
  host: { useTheme: () => mode, useLocale: () => "en", openExternalLink },
} as unknown as QwenPawWindowNamespace;
const scope = { agentId: "agent-a", sessionId: "session-a" };
const props = {
  source,
  isStreaming: false,
  language: "openui-lang",
  messageId: "m",
  blockId: "m:0",
  ...scope,
  fallback: () => <pre data-testid="fallback">{source}</pre>,
};
beforeEach(() => {
  Object.assign(window, { QwenPaw: api });
  submit.mockClear();
  openExternalLink.mockClear();
  mode = "light";
});
afterEach(cleanup);

describe("official OpenUI runtime", () => {
  it("preserves the official component catalog and model instructions", () => {
    expect(streamingLibrary.toJSONSchema()).toEqual(
      openuiLibrary.toJSONSchema(),
    );
    expect(streamingLibrary.prompt()).toBe(openuiLibrary.prompt());
  });

  it("updates a real slider locally, retains state across updates, and submits current values once", async () => {
    const view = render(<OpenUIBlock {...props} />);
    expect(screen.getByText("Total Runs: 35")).toBeTruthy();
    const slider = screen.getByRole("slider");
    for (let i = 0; i < 3; i++)
      fireEvent.keyDown(slider, { key: "ArrowRight" });
    await waitFor(() =>
      expect(screen.getByText("Total Runs: 56")).toBeTruthy(),
    );
    expect(submit).not.toHaveBeenCalled();
    mode = "dark";
    view.rerender(
      <OpenUIBlock
        {...props}
        source={source + '\nextra = TextContent("later")\n'}
      />,
    );
    expect(screen.getByText("Total Runs: 56")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continue analysis" }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit).toHaveBeenCalledWith("qwenpaw-openui", {
      ...scope,
      query: "Continue the analysis using 8 seeds",
    });
    view.unmount();
    expect(
      document.querySelector('style[data-qwenpaw-plugin="qwenpaw-openui"]'),
    ).toBeNull();
    render(<OpenUIBlock {...props} />);
    expect(screen.getByText("Total Runs: 35")).toBeTruthy();
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("renders components before completion without revealing source or replacing earlier controls", () => {
    const parser = createParser(openuiLibrary.toJSONSchema());
    for (let i = 0; i <= source.length; i++)
      expect(() => parser.parse(source.slice(0, i))).not.toThrow();
    const result = parser.parse(source);
    expect(result.meta.errors).toEqual([]);
    expect(result.meta.incomplete).toBe(false);
    const view = render(<OpenUIBlock {...props} source="" isStreaming />);
    const progress = screen.getByRole("status");
    let slider: HTMLElement | null = null;
    let appearedAt = source.length;
    for (let i = 0; i <= source.length; i++) {
      view.rerender(
        <OpenUIBlock {...props} source={source.slice(0, i)} isStreaming />,
      );
      expect(screen.getByRole("status")).toBe(progress);
      const current = screen.queryByRole("slider");
      if (slider)
        expect(
          current,
          `Prefix ${i}: ${source.slice(Math.max(0, i - 80), i)}`,
        ).toBe(slider);
      else if (current) {
        slider = current;
        appearedAt = i;
      }
      expect(view.container.textContent).not.toContain("root =");
      expect(screen.queryByTestId("fallback")).toBeNull();
      expect(screen.queryByRole("alert")).toBeNull();
    }
    expect(appearedAt).toBeLessThan(source.indexOf("next ="));
    expect(screen.getByText("Total Runs: 35")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continue analysis" }));
    expect(submit).not.toHaveBeenCalled();
    view.rerender(<OpenUIBlock {...props} />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText("Total Runs: 35")).toBeTruthy();
    expect(screen.getByRole("slider")).toBe(slider);
    fireEvent.keyDown(slider!, { key: "ArrowRight" });
    view.rerender(<OpenUIBlock {...props} />);
    expect(screen.getByRole("slider")).toBe(slider);
    expect(screen.getByText("Total Runs: 42")).toBeTruthy();
    expect(submit).not.toHaveBeenCalled();
  });

  it("shows a friendly error at completion without exposing unfinished source", async () => {
    const invalid = 'root = TextContent("unfinished';
    const view = render(
      <OpenUIBlock {...props} source={invalid} isStreaming />,
    );
    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.queryByTestId("fallback")).toBeNull();
    view.rerender(<OpenUIBlock {...props} source={invalid} />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByTestId("fallback")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it.each([
    'root = EvilComponent("x")',
    "root = Stack([missing])",
    'root = Stack([TextContent("unterminated',
    "root = Stack([TextContent(window.location.href)])",
    'root = Stack([TextContent(data)])\ndata = Query("fetch", {})',
  ])(
    "hides unsupported or invalid programs without exposing source: %s",
    async (invalid) => {
      const network = vi.spyOn(globalThis, "fetch");
      render(<OpenUIBlock {...props} source={invalid} />);
      await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
      expect(screen.queryByTestId("fallback")).toBeNull();
      expect(network).not.toHaveBeenCalled();
      expect(submit).not.toHaveBeenCalled();
      network.mockRestore();
    },
  );

  it("suppresses duplicate clicks while queue admission is pending", async () => {
    let accept!: () => void;
    submit.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          accept = resolve;
        }),
    );
    render(<OpenUIBlock {...props} />);
    const button = screen.getByRole("button", { name: "Continue analysis" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toBe("Submitting…");
    await act(async () => accept());
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows rejected queue admission and allows retry", async () => {
    submit.mockRejectedValueOnce(new Error("Queue full"));
    render(<OpenUIBlock {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Continue analysis" }));
    expect(await screen.findByText("Queue full")).toBeTruthy();
    await act(async () =>
      fireEvent.click(
        screen.getByRole("button", { name: "Continue analysis" }),
      ),
    );
    expect(submit).toHaveBeenCalledTimes(2);
  });
});

describe("host actions", () => {
  it("includes explicitly submitted context and form values in visible text", () => {
    const message = actionMessage({
      type: "continue_conversation",
      humanFriendlyMessage: "Compare",
      params: { context: { seeds: 8 } },
      formName: "choices",
      formState: {
        choices: { choice: { value: "B", componentType: "select" } },
        $unsubmitted: "private",
      },
    });
    expect(message).toContain('"seeds": 8');
    expect(message).toContain('"choice": "B"');
    expect(message).not.toContain("private");
    expect(message).not.toContain("componentType");
  });
  it("opens only HTTP(S) links without invoking the model", async () => {
    await dispatchAction(api, scope, {
      type: "open_url",
      params: { url: "https://example.com/" },
      humanFriendlyMessage: "Open",
    });
    expect(openExternalLink).toHaveBeenCalledWith("https://example.com/");
    for (const url of [
      "javascript:alert(1)",
      "data:text/html,bad",
      "file:///tmp/test",
      "/relative",
    ]) {
      await expect(
        dispatchAction(api, scope, {
          type: "open_url",
          params: { url },
          humanFriendlyMessage: "Open",
        }),
      ).rejects.toThrow();
    }
    await expect(
      dispatchAction(api, scope, {
        type: "invented",
        params: {},
        humanFriendlyMessage: "x",
      }),
    ).rejects.toThrow("Unsupported");
    expect(submit).not.toHaveBeenCalled();
  });
});
