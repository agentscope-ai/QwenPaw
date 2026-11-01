import {
  act,
  render,
  screen,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  loadFile: vi.fn().mockResolvedValue({ content: "" }),
  saveFile: vi.fn().mockResolvedValue({ written: true }),
  getHeartbeatConfig: vi.fn(),
  updateHeartbeatConfig: vi.fn(),
}));
const agentState = vi.hoisted(() => ({ selectedAgent: "default" }));
vi.mock("../../../api", () => ({ default: api }));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: Object.assign(
    () => ({ selectedAgent: agentState.selectedAgent }),
    {
      getState: () => agentState,
      subscribe: () => () => {},
    },
  ),
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

const config = (every: string, target: "main" | "last" | "inbox" = "main") => ({
  enabled: true,
  every,
  target,
  timeoutSeconds: 300,
  activeHours: { start: "08:00", end: "22:00" },
});

describe("Heartbeat schedule", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    agentState.selectedAgent = "default";
    api.loadFile.mockResolvedValue({ content: "" });
    api.getHeartbeatConfig.mockResolvedValue({
      enabled: true,
      every: "6h",
      target: "main",
      timeoutSeconds: 300,
      activeHours: { start: "08:00", end: "22:00" },
    });
    api.updateHeartbeatConfig.mockResolvedValue({});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });
  it("keeps every hydrated reply target visible and selectable", async () => {
    render(<HeartbeatPage />);
    await screen.findByRole("switch", { name: "heartbeat.enabled" });

    for (const name of [
      "heartbeat.targetMain",
      "heartbeat.targetLast",
      "heartbeat.targetInbox",
    ]) {
      const target = screen.getByRole("radio", { name });
      const targetItem = target.closest(".ant-segmented-item");
      expect(targetItem).toBeVisible();
      fireEvent.click(targetItem!);
      expect(target).toBeChecked();
    }
  });

  it("blocks autosave controls until retry restores persisted config", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    let loadFails = true;
    api.getHeartbeatConfig.mockImplementation(async () => {
      if (loadFails) throw new Error("network down");
      return {
        enabled: true,
        every: "12h",
        target: "inbox",
        timeoutSeconds: 900,
        activeHours: { start: "09:00", end: "21:00" },
      };
    });

    api.loadFile.mockResolvedValue({ content: "Healthy instructions" });
    render(<HeartbeatPage />);

    const retry = await screen.findByRole("button", { name: "common.retry" });
    expect(screen.getByRole("alert")).toHaveTextContent("heartbeat.loadFailed");
    expect(
      screen.queryByRole("switch", { name: "heartbeat.enabled" }),
    ).toBeNull();
    expect(
      screen.queryByRole("radio", { name: "heartbeat.targetInbox" }),
    ).toBeNull();
    const instructions = await screen.findByRole("textbox", {
      name: "HEARTBEAT.md",
    });
    expect(instructions).toHaveValue("Healthy instructions");
    expect(api.loadFile).toHaveBeenCalledWith("HEARTBEAT.md", "default");
    fireEvent.change(instructions, {
      target: { value: "Updated while schedule is unavailable" },
    });
    await waitFor(
      () =>
        expect(api.saveFile).toHaveBeenCalledWith(
          "HEARTBEAT.md",
          "Updated while schedule is unavailable",
          "default",
        ),
      { timeout: 2500 },
    );
    expect(api.updateHeartbeatConfig).not.toHaveBeenCalled();

    loadFails = false;
    fireEvent.click(retry);

    expect(
      await screen.findByRole("switch", { name: "heartbeat.enabled" }),
    ).toBeChecked();
    expect(
      screen.getByRole("button", { name: "12 heartbeat.unitHours" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("radio", { name: "heartbeat.targetInbox" }),
    ).toBeChecked();
    expect(
      screen.getByRole("switch", { name: "heartbeat.activeHours" }),
    ).toBeChecked();
    expect(
      screen.getByRole("slider", { name: "heartbeat.timeoutSeconds" }),
    ).toHaveAttribute("aria-valuenow", "900");
    expect(screen.getByDisplayValue("09:00")).toBeInTheDocument();
    expect(screen.getByDisplayValue("21:00")).toBeInTheDocument();
    expect(api.updateHeartbeatConfig).not.toHaveBeenCalled();
  });

  it("ignores late agent responses and only saves the current agent", async () => {
    const agentA = deferred<ReturnType<typeof config>>();
    api.getHeartbeatConfig.mockImplementation((agentId: string) =>
      agentId === "agent-a" ? agentA.promise : Promise.resolve(config("12h")),
    );
    agentState.selectedAgent = "agent-a";
    const view = render(<HeartbeatPage />);
    await waitFor(() =>
      expect(api.getHeartbeatConfig).toHaveBeenCalledWith("agent-a"),
    );

    agentState.selectedAgent = "agent-b";
    view.rerender(<HeartbeatPage />);
    await waitFor(() =>
      expect(api.getHeartbeatConfig).toHaveBeenCalledWith("agent-b"),
    );
    expect(
      await screen.findByRole("button", { name: "12 heartbeat.unitHours" }),
    ).toHaveAttribute("aria-pressed", "true");

    await act(async () => {
      agentA.resolve(config("1h", "inbox"));
      await agentA.promise;
    });
    expect(
      screen.getByRole("button", { name: "12 heartbeat.unitHours" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("radio", { name: "heartbeat.targetMain" }),
    ).toBeChecked();
    expect(api.updateHeartbeatConfig).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "3 heartbeat.unitHours" }),
    );
    await waitFor(
      () =>
        expect(api.updateHeartbeatConfig).toHaveBeenCalledWith(
          expect.objectContaining({ every: "3h", target: "main" }),
          "agent-b",
        ),
      { timeout: 2500 },
    );
    expect(api.updateHeartbeatConfig).toHaveBeenCalledTimes(1);
  });

  it("keeps agent B visible when agent A rejects late", async () => {
    const agentA = deferred<ReturnType<typeof config>>();
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.getHeartbeatConfig.mockImplementation((agentId: string) =>
      agentId === "agent-a" ? agentA.promise : Promise.resolve(config("6h")),
    );
    agentState.selectedAgent = "agent-a";
    const view = render(<HeartbeatPage />);
    await waitFor(() =>
      expect(api.getHeartbeatConfig).toHaveBeenCalledWith("agent-a"),
    );

    agentState.selectedAgent = "agent-b";
    view.rerender(<HeartbeatPage />);
    expect(
      await screen.findByRole("button", { name: "6 heartbeat.unitHours" }),
    ).toHaveAttribute("aria-pressed", "true");
    await act(async () => {
      agentA.reject(new Error("late A failure"));
      await agentA.promise.catch(() => undefined);
    });

    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen.getByRole("switch", { name: "heartbeat.enabled" }),
    ).toBeChecked();
    expect(api.updateHeartbeatConfig).not.toHaveBeenCalled();
  });

  it("locks schedule writes immediately when the selected agent changes", async () => {
    agentState.selectedAgent = "agent-a";
    render(<HeartbeatPage />);
    const preset = await screen.findByRole("button", {
      name: "3 heartbeat.unitHours",
    });

    agentState.selectedAgent = "agent-b";
    fireEvent.click(preset);
    await new Promise((resolve) => setTimeout(resolve, 1100));

    expect(api.updateHeartbeatConfig).not.toHaveBeenCalled();
  });
  it.each(["24h", "48h"])(
    "preserves %s when disabling an existing heartbeat",
    async (every) => {
      api.getHeartbeatConfig.mockResolvedValue({
        enabled: true,
        every,
        target: "main",
        timeoutSeconds: 300,
      });
      render(<HeartbeatPage />);
      const enabled = await screen.findByRole("switch", {
        name: "heartbeat.enabled",
      });
      await waitFor(() =>
        expect(
          screen.getByRole("spinbutton", { name: "heartbeat.unitHours" }),
        ).toHaveAttribute("aria-valuenow", String(Number.parseInt(every))),
      );
      fireEvent.click(enabled);
      await waitFor(
        () =>
          expect(api.updateHeartbeatConfig).toHaveBeenCalledWith(
            expect.objectContaining({ enabled: false, every }),
            "default",
          ),
        { timeout: 2500 },
      );
    },
  );
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
  it("saves a newer edit made while the previous save is running", async () => {
    const firstSave = deferred<void>();
    api.updateHeartbeatConfig
      .mockImplementationOnce(() => firstSave.promise)
      .mockResolvedValueOnce({});
    render(<HeartbeatPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "3 heartbeat.unitHours" }),
    );
    await waitFor(
      () => expect(api.updateHeartbeatConfig).toHaveBeenCalledTimes(1),
      { timeout: 2500 },
    );

    fireEvent.click(
      screen.getByRole("button", { name: "12 heartbeat.unitHours" }),
    );
    await act(async () => {
      firstSave.resolve();
      await firstSave.promise;
    });

    await waitFor(() =>
      expect(api.updateHeartbeatConfig).toHaveBeenLastCalledWith(
        expect.objectContaining({ every: "12h" }),
        "default",
      ),
    );
    expect(api.updateHeartbeatConfig).toHaveBeenCalledTimes(2);
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
