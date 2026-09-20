import {
  useEffect,
  useState,
  type ReactNode,
  type ComponentProps,
} from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Dock from "./TerminalDock";
import ChatActionGroup from "../../pages/Chat/components/ChatActionGroup";
import { message } from "antd";

function TerminalDock(
  props: Omit<ComponentProps<typeof Dock>, "open" | "setOpen">,
) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <ChatActionGroup
        terminalEnabled
        onToggleTerminal={() => setOpen(!open)}
        terminalOpen={open}
        onToggleWorkspace={() => {}}
      />
      <Dock {...props} open={open} setOpen={setOpen} />
    </>
  );
}

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  close: vi.fn(),
  resize: vi.fn(),
  collapse: vi.fn(),
  panel: vi.fn(),
  mount: vi.fn(),
  unmount: vi.fn(),
}));
vi.mock("./terminalApi", () => ({ terminalApi: () => mocks }));
vi.mock("./TerminalView", () => ({
  default: ({ terminal }: { terminal: { id: string } }) => (
    <div data-testid="terminal-view">{terminal.id}</div>
  ),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) =>
      fallback ?? (key === "terminal.title" ? "Terminal" : key),
  }),
}));
vi.mock("react-resizable-panels", () => ({
  Group: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Panel: (props: { children: ReactNode; id: string }) => {
    if (props.id === "terminal") mocks.panel(props);
    return <div>{props.children}</div>;
  },
  Separator: () => <div />,
  usePanelRef: () => ({
    current: { resize: mocks.resize, collapse: mocks.collapse },
  }),
}));
function Chat() {
  useEffect(() => {
    mocks.mount();
    return () => mocks.unmount();
  }, []);
  return <input aria-label="Chat input" defaultValue="draft" />;
}
const scope = { kind: "session" as const, agentId: "agent", sessionId: "new" };
const tab = (id: string) => ({
  id,
  title: "zsh",
  cwd: "/project",
  exited: false,
  exit_code: null,
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.list.mockResolvedValue([]);
  mocks.create.mockResolvedValue(tab("first"));
  mocks.close.mockResolvedValue({});
});
afterEach(cleanup);

describe("conversation terminal dock", () => {
  it("collapses after dragging without changing the panel constraints", async () => {
    mocks.list.mockResolvedValue([tab("first")]);
    render(
      <TerminalDock scope={scope} isDark={false}>
        <Chat />
      </TerminalDock>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    await screen.findByRole("tab", { name: "zsh 1" });
    const props = mocks.panel.mock.lastCall![0];
    props.onResize({ inPixels: 340 }, "terminal", { inPixels: 250 });
    fireEvent.click(
      screen.getByRole("button", { name: "Hide terminal panel" }),
    );
    expect(mocks.collapse).toHaveBeenCalled();
    expect(screen.queryByTestId("terminal-view")).not.toBeInTheDocument();
    for (const [panel] of mocks.panel.mock.calls) {
      expect(panel).toMatchObject({
        defaultSize: 0,
        collapsedSize: 0,
        collapsible: true,
        minSize: 130,
        maxSize: "65%",
      });
    }
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    expect(mocks.resize).toHaveBeenLastCalledWith(340);
    expect(mocks.mount).toHaveBeenCalledTimes(1);
    expect(mocks.unmount).not.toHaveBeenCalled();
  });
  it("keeps the launcher and explains authentication without opening a terminal", () => {
    const toggle = vi.fn();
    const info = vi
      .spyOn(message, "info")
      .mockImplementation(() => (() => {}) as ReturnType<typeof message.info>);
    render(
      <ChatActionGroup onToggleTerminal={toggle} terminalEnabled={false} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    expect(info).toHaveBeenCalledWith("terminal.authRequired");
    expect(toggle).not.toHaveBeenCalled();
    expect(mocks.create).not.toHaveBeenCalled();
    info.mockRestore();
  });
  it("hides the terminal launcher when access is unavailable", () => {
    render(<ChatActionGroup onToggleWorkspace={() => {}} />);
    expect(
      screen.queryByRole("button", { name: "Terminal" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "files.openWorkspace" }),
    ).toBeInTheDocument();
  });
  it.each([
    ["Close terminal", ["second"], 2],
    ["Close other terminals", ["first", "third"], 1],
    ["Close all terminals", ["first", "second", "third"], 0],
  ] as const)(
    "context menu: %s targets the clicked tab",
    async (label, ids, remaining) => {
      mocks.list.mockResolvedValue([tab("first"), tab("second"), tab("third")]);
      render(
        <TerminalDock scope={scope} isDark={false}>
          <Chat />
        </TerminalDock>,
      );
      fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
      fireEvent.contextMenu(await screen.findByRole("tab", { name: "zsh 2" }));
      fireEvent.click(await screen.findByRole("menuitem", { name: label }));
      await waitFor(() =>
        expect(screen.queryAllByRole("tab")).toHaveLength(remaining),
      );
      expect(mocks.close.mock.calls.map(([id]) => id)).toEqual(ids);
      expect(mocks.create).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Terminal" })).toHaveAttribute(
        "aria-expanded",
        String(remaining > 0),
      );
      if (label === "Close other terminals")
        expect(screen.getByTestId("terminal-view")).toHaveTextContent("second");
    },
  );

  it("keeps failed and unprocessed tabs when a bulk close fails", async () => {
    mocks.list.mockResolvedValue([tab("first"), tab("second"), tab("third")]);
    mocks.close
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error("Close failed"));
    render(
      <TerminalDock scope={scope} isDark={false}>
        <Chat />
      </TerminalDock>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    fireEvent.contextMenu(await screen.findByRole("tab", { name: "zsh 1" }));
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Close all terminals" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Close failed");
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(mocks.close.mock.calls.map(([id]) => id)).toEqual([
      "first",
      "second",
    ]);
  });

  it("adds and switches independent tabs, and collapses without terminating", async () => {
    render(
      <TerminalDock scope={scope} isDark={false}>
        <Chat />
      </TerminalDock>,
    );
    expect(
      screen.queryByRole("button", { name: "chat.newTask" }),
    ).not.toBeInTheDocument();
    expect(
      screen
        .getAllByRole("button")
        .map((button) => button.getAttribute("aria-label")),
    ).toEqual(["Terminal", "files.openWorkspace"]);
    expect(
      screen.queryByRole("button", { name: "New terminal" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    await waitFor(() =>
      expect(screen.getByTestId("terminal-view")).toHaveTextContent("first"),
    );
    expect(mocks.create).toHaveBeenCalledTimes(1);
    mocks.create.mockResolvedValue(tab("second"));
    fireEvent.click(screen.getByRole("button", { name: "New terminal" }));
    await waitFor(() =>
      expect(screen.getByTestId("terminal-view")).toHaveTextContent("second"),
    );
    fireEvent.click(screen.getByRole("tab", { name: "zsh 1" }));
    expect(screen.getByTestId("terminal-view")).toHaveTextContent("first");
    expect(
      screen.queryByRole("button", { name: "Restart terminal" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Hide terminal panel" }),
    );
    expect(screen.queryByTestId("terminal-view")).not.toBeInTheDocument();
    expect(mocks.close).not.toHaveBeenCalled();
    expect(mocks.mount).toHaveBeenCalledTimes(1);
    expect(mocks.unmount).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Terminal" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    mocks.list.mockResolvedValue([tab("first"), tab("second")]);
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    await screen.findByRole("tab", { name: "zsh 2" });
    expect(mocks.create).toHaveBeenCalledTimes(2);
  });

  it("does not remount the chat SDK or show another conversation's tabs", async () => {
    mocks.list.mockResolvedValue([tab("first")]);
    const { rerender } = render(
      <TerminalDock scope={scope} isDark={false}>
        <Chat />
      </TerminalDock>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    await screen.findByRole("tab", { name: "zsh 1" });
    expect(mocks.create).not.toHaveBeenCalled();
    mocks.list.mockResolvedValue([]);
    rerender(
      <TerminalDock
        scope={{ ...scope, sessionId: "other", chatId: "other" }}
        isDark={false}
      >
        <Chat />
      </TerminalDock>,
    );
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(mocks.unmount).not.toHaveBeenCalled();
    expect(mocks.close).not.toHaveBeenCalled();
  });

  it("closes the selected process only when its close button is pressed", async () => {
    mocks.list.mockResolvedValue([tab("first"), tab("second")]);
    render(
      <TerminalDock scope={scope} isDark={false}>
        <Chat />
      </TerminalDock>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    await screen.findByRole("button", { name: "Close terminal 1" });
    fireEvent.click(screen.getByRole("button", { name: "Close terminal 1" }));
    await waitFor(() => expect(mocks.close).toHaveBeenCalledWith("first"));
    await waitFor(() => expect(screen.getAllByRole("tab")).toHaveLength(1));
    expect(screen.getByTestId("terminal-view")).toHaveTextContent("second");
  });

  it.each(["button", "Close terminal", "Close all terminals"])(
    "collapses after closing the last tab via %s and creates on reopening",
    async (action) => {
      mocks.list.mockResolvedValueOnce([tab("first")]);
      render(
        <TerminalDock scope={scope} isDark={false}>
          <Chat />
        </TerminalDock>,
      );
      const launcher = screen.getByRole("button", { name: "Terminal" });
      fireEvent.click(launcher);
      const first = await screen.findByRole("tab", { name: "zsh 1" });
      mocks.collapse.mockClear();
      if (action === "button") {
        fireEvent.click(
          screen.getByRole("button", { name: "Close terminal 1" }),
        );
      } else {
        fireEvent.contextMenu(first);
        fireEvent.click(await screen.findByRole("menuitem", { name: action }));
      }
      await waitFor(() =>
        expect(launcher).toHaveAttribute("aria-expanded", "false"),
      );
      expect(mocks.close).toHaveBeenCalledWith("first");
      expect(mocks.collapse).toHaveBeenCalled();
      expect(
        screen.queryByRole("button", { name: "New terminal" }),
      ).not.toBeInTheDocument();
      expect(mocks.create).not.toHaveBeenCalled();
      expect(mocks.unmount).not.toHaveBeenCalled();
      fireEvent.click(launcher);
      await screen.findByRole("tab", { name: "zsh 1" });
      expect(mocks.create).toHaveBeenCalledTimes(1);
      expect(launcher).toHaveAttribute("aria-expanded", "true");
    },
  );

  it("keeps the last tab visible when closing fails", async () => {
    mocks.list.mockResolvedValue([tab("first")]);
    mocks.close.mockRejectedValueOnce(new Error("Close failed"));
    render(
      <TerminalDock scope={scope} isDark={false}>
        <Chat />
      </TerminalDock>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Close terminal 1" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Close failed");
    expect(screen.getByRole("tab", { name: "zsh 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Terminal" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});
