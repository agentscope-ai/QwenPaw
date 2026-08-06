import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { codingModeApi } from "../api/modules/codingMode";
import { useAgentStore } from "../stores/agentStore";
import { useCodingModeStore } from "../stores/codingModeStore";
import { useOsWindows } from "./osWindowStore";
import { useOsAppLauncher } from "./useOsAppLauncher";

vi.mock("../api/modules/codingMode", () => ({
  codingModeApi: {
    toggle: vi.fn(),
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

function Harness() {
  const launchApp = useOsAppLauncher();
  return (
    <>
      <button type="button" onClick={() => void launchApp("core.coding")}>
        Open Coding
      </button>
      <button type="button" onClick={() => void launchApp("core.chat")}>
        Open Chat
      </button>
    </>
  );
}

describe("useOsAppLauncher", () => {
  beforeEach(() => {
    vi.mocked(codingModeApi.toggle).mockReset();
    vi.mocked(codingModeApi.toggle).mockResolvedValue({
      enabled: true,
      agent_id: "default",
    });
    useAgentStore.setState({ selectedAgent: "default" });
    useCodingModeStore.setState({
      codingModeByAgent: { default: false },
      codingModeRevisionByAgent: {},
    });
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
    Object.defineProperty(window, "innerWidth", {
      value: 1440,
      configurable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      value: 900,
      configurable: true,
    });
  });

  it("enables Coding Mode before opening its desktop window", async () => {
    useOsWindows.getState().open("core.chat");
    renderWithProviders(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Open Coding" }));

    await waitFor(() => {
      expect(codingModeApi.toggle).toHaveBeenCalledWith(true);
      expect(useOsWindows.getState().windows["core.chat"]).toBeUndefined();
      expect(useOsWindows.getState().windows["core.coding"]).toBeDefined();
    });
    expect(useCodingModeStore.getState().codingModeByAgent.default).toBe(true);
  });

  it("does not open Coding when backend activation fails", async () => {
    vi.mocked(codingModeApi.toggle).mockRejectedValueOnce(
      new Error("Activation failed"),
    );
    renderWithProviders(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Open Coding" }));

    await waitFor(() => {
      expect(codingModeApi.toggle).toHaveBeenCalledWith(true);
    });
    expect(useOsWindows.getState().windows["core.coding"]).toBeUndefined();
  });

  it("reopens the current mode after its window is closed", async () => {
    useCodingModeStore.setState({
      codingModeByAgent: { default: true },
    });
    renderWithProviders(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Open Coding" }));
    await waitFor(() => {
      expect(useOsWindows.getState().windows["core.coding"]).toBeDefined();
    });

    useOsWindows.getState().close("core.coding");
    fireEvent.click(screen.getByRole("button", { name: "Open Coding" }));

    await waitFor(() => {
      expect(useOsWindows.getState().windows["core.coding"]).toBeDefined();
    });
    expect(codingModeApi.toggle).not.toHaveBeenCalled();
  });

  it("can switch modes and reopen after both windows were closed", async () => {
    renderWithProviders(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Open Coding" }));
    await waitFor(() => {
      expect(useOsWindows.getState().windows["core.coding"]).toBeDefined();
    });

    fireEvent.click(screen.getByRole("button", { name: "Open Chat" }));
    await waitFor(() => {
      expect(useOsWindows.getState().windows["core.coding"]).toBeUndefined();
      expect(useOsWindows.getState().windows["core.chat"]).toBeDefined();
    });

    useOsWindows.getState().close("core.chat");
    fireEvent.click(screen.getByRole("button", { name: "Open Coding" }));

    await waitFor(() => {
      expect(useOsWindows.getState().windows["core.coding"]).toBeDefined();
    });
    expect(codingModeApi.toggle).toHaveBeenNthCalledWith(1, true);
    expect(codingModeApi.toggle).toHaveBeenNthCalledWith(2, false);
    expect(codingModeApi.toggle).toHaveBeenNthCalledWith(3, true);
  });
});
