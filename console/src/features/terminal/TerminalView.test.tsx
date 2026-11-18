import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TerminalView from "./TerminalView";
import type { TerminalApi } from "./terminalApi";
import styles from "./TerminalDock.module.less";

const state = vi.hoisted(() => ({
  input: undefined as ((data: string) => void) | undefined,
  write: vi.fn(),
  dispose: vi.fn(),
  reset: vi.fn(),
  construct: vi.fn(),
  open: vi.fn(),
  t: (_key: string, fallback: string) => fallback,
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: state.t }) }));
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    fit() {}
  },
}));
vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    options = {};
    rows = 24;
    cols = 80;
    parser = { registerOscHandler: () => ({ dispose() {} }) };
    constructor() {
      state.construct();
    }
    loadAddon() {}
    open = state.open;
    focus() {}
    reset = state.reset;
    write = state.write;
    dispose = state.dispose;
    onData(callback: (data: string) => void) {
      state.input = callback;
      return { dispose() {} };
    }
  },
}));
const terminal = {
  id: "pty",
  title: "sh",
  cwd: "/repo",
  exited: false,
  exit_code: null,
};
let api: TerminalApi;
beforeEach(() => {
  vi.clearAllMocks();
  state.write.mockImplementation((_data: string, callback: () => void) =>
    callback(),
  );
  api = {
    list: vi.fn(),
    create: vi.fn(),
    close: vi.fn(),
    rename: vi.fn(),
    input: vi.fn().mockResolvedValue({}),
    resize: vi.fn().mockResolvedValue({}),
    output: vi.fn().mockImplementation(() => new Promise(() => {})),
  };
});
afterEach(cleanup);

describe("PTY output and input lifecycle", () => {
  it("mounts xterm inside a separate host so padding is excluded from fit", () => {
    render(<TerminalView api={api} terminal={terminal} isDark={false} />);
    const host = state.open.mock.calls[0][0] as HTMLElement;
    expect(host).toHaveClass(styles.terminalHost);
    expect(host.parentElement).toHaveClass(styles.screen);
    expect(host).not.toHaveClass(styles.screen);
  });
  it("delivers accepted input even when the user switches tabs immediately", async () => {
    let finishFirst: (() => void) | undefined;
    vi.mocked(api.input).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFirst = () => resolve({});
        }),
    );
    const { unmount } = render(
      <TerminalView api={api} terminal={terminal} isDark={false} />,
    );
    act(() => state.input?.("a".repeat(5000)));
    await waitFor(() => expect(api.input).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => finishFirst?.());
    await waitFor(() => expect(api.input).toHaveBeenCalledTimes(2));
    expect(
      vi
        .mocked(api.input)
        .mock.calls.map((call) => call[1])
        .join(""),
    ).toHaveLength(5000);
  });
  it("waits for rendering before requesting more output and cancels on unmount", async () => {
    vi.mocked(api.output).mockResolvedValueOnce({
      data: "abc",
      cursor: 3,
      reset: true,
      exited: false,
      exit_code: null,
    });
    let written: (() => void) | undefined;
    state.write.mockImplementation((_data: string, callback: () => void) => {
      written = callback;
    });
    const { unmount } = render(
      <TerminalView api={api} terminal={terminal} isDark={false} />,
    );
    await waitFor(() => expect(state.write).toHaveBeenCalled());
    expect(api.output).toHaveBeenCalledTimes(1);
    expect(state.reset).toHaveBeenCalledTimes(1);
    await act(async () => written?.());
    expect(api.output).toHaveBeenLastCalledWith(
      "pty",
      3,
      expect.any(AbortSignal),
    );
    const signal = vi.mocked(api.output).mock.calls[1][2];
    unmount();
    expect(signal.aborted).toBe(true);
    expect(state.dispose).toHaveBeenCalledTimes(1);
  });

  it("reports process exit without waiting for a tab refresh", async () => {
    vi.mocked(api.output).mockResolvedValueOnce({
      data: "done",
      cursor: 4,
      reset: false,
      exited: true,
      exit_code: 7,
    });
    const onExit = vi.fn();

    render(
      <TerminalView
        api={api}
        terminal={terminal}
        isDark={false}
        onExit={onExit}
      />,
    );

    await waitFor(() => expect(onExit).toHaveBeenCalledWith("pty", 7));
    expect(api.output).toHaveBeenCalledTimes(1);
  });

  it("preserves paste order and changes theme without restarting the PTY view", async () => {
    const { rerender } = render(
      <TerminalView api={api} terminal={terminal} isDark={false} />,
    );
    const text = "a".repeat(4095) + "𠮷";
    act(() => state.input?.(text));
    await waitFor(() => expect(api.input).toHaveBeenCalledTimes(2));
    expect(
      vi
        .mocked(api.input)
        .mock.calls.map((call) => call[1])
        .join(""),
    ).toBe(text);
    rerender(<TerminalView api={api} terminal={terminal} isDark />);
    expect(state.construct).toHaveBeenCalledTimes(1);
    expect(api.close).not.toHaveBeenCalled();
  });
});
