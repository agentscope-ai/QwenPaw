import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CloseWindowPrompt from "../tauri/CloseWindowPrompt";

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
  onClose: undefined as (() => void) | undefined,
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: mocks.listen }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

async function requestClose() {
  render(<CloseWindowPrompt />);
  await waitFor(() => expect(mocks.onClose).toBeDefined());
  act(() => mocks.onClose?.());
  expect(mocks.invoke).toHaveBeenCalledWith("ack_close");
}

describe("native close window actions", () => {
  beforeEach(() => {
    mocks.onClose = undefined;
    mocks.invoke.mockReset().mockResolvedValue(undefined);
    mocks.listen.mockReset().mockImplementation(async (_, callback) => {
      mocks.onClose = callback;
      return () => undefined;
    });
    Object.defineProperties(HTMLDialogElement.prototype, {
      showModal: {
        configurable: true,
        value: function (this: HTMLDialogElement) {
          this.open = true;
        },
      },
      close: {
        configurable: true,
        value: function (this: HTMLDialogElement) {
          this.open = false;
        },
      },
    });
  });

  afterEach(() => {
    Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
    Reflect.deleteProperty(HTMLDialogElement.prototype, "close");
    vi.restoreAllMocks();
  });

  it("keeps the desktop shell alive when background running is chosen", async () => {
    await requestClose();
    fireEvent.click(
      screen.getByRole("button", { name: "desktop.closeWindow.keepRunning" }),
    );
    await waitFor(() =>
      expect(mocks.invoke).toHaveBeenCalledWith("minimize_to_tray"),
    );
    expect(mocks.invoke).not.toHaveBeenCalledWith("quit_app");
    expect(mocks.invoke).not.toHaveBeenCalledWith("stop_service");
  });

  it("remembers background running as the tray action", async () => {
    await requestClose();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(
      screen.getByRole("button", { name: "desktop.closeWindow.keepRunning" }),
    );
    await waitFor(() =>
      expect(mocks.invoke).toHaveBeenCalledWith("minimize_to_tray"),
    );
    expect(mocks.invoke).toHaveBeenCalledWith("set_close_action", {
      action: "minimize-to-tray",
    });
    expect(mocks.invoke).not.toHaveBeenCalledWith("quit_app");
  });

  it("stops the service before quitting completely", async () => {
    await requestClose();
    fireEvent.click(
      screen.getByRole("button", { name: "desktop.closeWindow.stopService" }),
    );
    await waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith("quit_app"));
    const commands = mocks.invoke.mock.calls.map(([command]) => command);
    expect(commands.indexOf("stop_service")).toBeLessThan(
      commands.indexOf("quit_app"),
    );
    expect(commands).not.toContain("minimize_to_tray");
  });

  it("keeps the window open if stopping the shared service fails", async () => {
    mocks.invoke.mockImplementation(async (command) => {
      if (command === "stop_service")
        throw new Error("Other clients are active");
    });
    await requestClose();
    fireEvent.click(
      screen.getByRole("button", { name: "desktop.closeWindow.stopService" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Other clients are active",
    );
    expect(mocks.invoke).not.toHaveBeenCalledWith("quit_app");
    expect(screen.getByRole("dialog")).toHaveAttribute("open");
  });
});
