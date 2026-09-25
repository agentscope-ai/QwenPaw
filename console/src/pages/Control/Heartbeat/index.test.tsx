import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  loadFile: vi.fn().mockResolvedValue({ content: "" }),
  saveFile: vi.fn().mockResolvedValue({ written: true }),
  getHeartbeatConfig: vi.fn(),
  updateHeartbeatConfig: vi.fn(),
}));
vi.mock("../../../api", () => ({ default: api }));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: Object.assign(() => ({ selectedAgent: "default" }), {
    subscribe: () => () => {},
  }),
}));
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { destroy: vi.fn(), success: vi.fn(), error: vi.fn() },
  }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@agentscope-ai/design", async () => vi.importActual("antd"));
vi.mock("@number-flow/react", () => ({
  default: ({ value }: { value: number }) => <span>{value}</span>,
}));
import HeartbeatPage from "./index";

describe("Heartbeat schedule", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getHeartbeatConfig.mockResolvedValue({
      enabled: true,
      every: "6h",
      target: "main",
      timeoutSeconds: 300,
      activeHours: { start: "08:00", end: "22:00" },
    });
    api.updateHeartbeatConfig.mockResolvedValue({});
  });
  it("saves a preset and delivery choice while preserving advanced settings", async () => {
    render(<HeartbeatPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "3 heartbeat.unitHours" }),
    );
    fireEvent.click(
      screen.getByRole("radio", { name: "heartbeat.targetInbox" }),
    );
    await waitFor(
      () =>
        expect(api.updateHeartbeatConfig).toHaveBeenCalledWith(
          {
            enabled: true,
            every: "3h",
            target: "inbox",
            timeoutSeconds: 300,
            activeHours: { start: "08:00", end: "22:00" },
          },
          "default",
        ),
      { timeout: 2500 },
    );
  });
  it("keeps the interval read-only while disabled and restores it on enable", async () => {
    api.getHeartbeatConfig.mockResolvedValue({
      enabled: false,
      every: "6h",
      target: "main",
      timeoutSeconds: 300,
    });
    render(<HeartbeatPage />);
    const preset = await screen.findByRole("button", {
      name: "3 heartbeat.unitHours",
    });
    expect(preset).toBeDisabled();
    expect(screen.queryAllByRole("spinbutton")).toHaveLength(0);
    fireEvent.click(preset);
    expect(api.updateHeartbeatConfig).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("switch", { name: "heartbeat.enabled" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "3 heartbeat.unitHours" }),
      ).toBeEnabled(),
    );
    expect(screen.getAllByRole("spinbutton")[0]).toHaveAttribute(
      "aria-valuenow",
      "6",
    );
    await waitFor(
      () =>
        expect(api.updateHeartbeatConfig).toHaveBeenCalledWith(
          expect.objectContaining({ enabled: true, every: "6h" }),
          "default",
        ),
      { timeout: 2500 },
    );
  });
  it("edits HEARTBEAT.md and flushes the current agent's content on leaving", async () => {
    api.loadFile.mockResolvedValue({ content: "Check inbox" });
    const view = render(<HeartbeatPage />);
    const input = await screen.findByRole("textbox", { name: "HEARTBEAT.md" });
    expect(input).toHaveValue("Check inbox");
    fireEvent.change(input, { target: { value: "Summarize unread messages" } });
    view.unmount();
    await waitFor(() =>
      expect(api.saveFile).toHaveBeenCalledWith(
        "HEARTBEAT.md",
        "Summarize unread messages",
        "default",
      ),
    );
  });
});
