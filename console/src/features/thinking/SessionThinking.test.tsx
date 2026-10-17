import type { ReactNode } from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import {
  sessionThinkingApi,
  setPendingThinking,
  clearPendingThinking,
} from "./sessionThinkingApi";
import {
  resetSessionModel,
  saveDecisionSettings,
} from "../session-settings/sessionModel";
import { SessionThinking } from "./SessionThinking";
import type { ThinkingView } from "./types";

beforeEach(() => {
  vi.mocked(sessionThinkingApi.get).mockReset();
  vi.mocked(sessionThinkingApi.set).mockReset();
  vi.mocked(resetSessionModel).mockReset();
  vi.mocked(saveDecisionSettings).mockReset();
});

const effortView: ThinkingView = {
  model: "reasoning-model",
  model_name: "Reasoning model",
  model_key: "fixture:reasoning-model",
  control: {
    kind: "effort",
    efforts: ["low", "medium", "high"],
    supports_off: true,
  },
  value: { level: "low" },
  effective: { level: "low" },
  source: "session",
  reason: null,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function chooseEffort(key: string, keyCode: number) {
  const slider = screen.getByRole("slider");
  fireEvent.keyDown(slider, { key, keyCode });
  fireEvent.keyUp(slider, { key, keyCode });
}

it("keeps the panel and latest effort stable across slow, ordered saves", async () => {
  vi.mocked(sessionThinkingApi.get).mockResolvedValue(effortView);
  const first = deferred<ThinkingView>();
  const second = deferred<ThinkingView>();
  vi.mocked(sessionThinkingApi.set)
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise);
  const { container } = renderWithProviders(
    <SessionThinking agentId="a" sessionId="s" chatId="c" />,
  );
  const slider = await screen.findByRole("slider");
  await waitFor(() =>
    expect(slider).not.toHaveAttribute("aria-disabled", "true"),
  );
  const title = container.querySelector("section strong")!;
  chooseEffort("End", 35);
  await waitFor(() => expect(sessionThinkingApi.set).toHaveBeenCalledTimes(1));
  expect(title).toHaveTextContent("thinkingControl.high");
  expect(slider).toHaveAttribute("aria-valuenow", "3");
  expect(slider).not.toHaveAttribute("aria-disabled", "true");
  expect(container.querySelector('[class*="spin-blur"]')).toBeNull();

  chooseEffort("ArrowLeft", 37);
  expect(title).toHaveTextContent("thinkingControl.medium");
  expect(slider).toHaveAttribute("aria-valuenow", "2");
  expect(sessionThinkingApi.set).toHaveBeenCalledTimes(1);
  await act(async () =>
    first.resolve({ ...effortView, value: { level: "high" } }),
  );
  await waitFor(() => expect(sessionThinkingApi.set).toHaveBeenCalledTimes(2));
  expect(title).toHaveTextContent("thinkingControl.medium");
  expect(slider).toHaveAttribute("aria-valuenow", "2");
  await act(async () =>
    second.resolve({ ...effortView, value: { level: "medium" } }),
  );
  expect(title).toHaveTextContent("thinkingControl.medium");
  expect(slider).toHaveAttribute("aria-valuenow", "2");
  expect(
    vi.mocked(sessionThinkingApi.set).mock.calls.map((call) => call[2]),
  ).toEqual([{ level: "high" }, { level: "medium" }]);
});

it("restores the last confirmed effort if the latest queued save fails", async () => {
  vi.mocked(sessionThinkingApi.get).mockResolvedValue(effortView);
  const first = deferred<ThinkingView>();
  const second = deferred<ThinkingView>();
  vi.mocked(sessionThinkingApi.set)
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise);
  const { container } = renderWithProviders(
    <SessionThinking agentId="a" sessionId="s" chatId="c" />,
  );
  const slider = await screen.findByRole("slider");
  await waitFor(() =>
    expect(slider).not.toHaveAttribute("aria-disabled", "true"),
  );
  chooseEffort("End", 35);
  await waitFor(() => expect(sessionThinkingApi.set).toHaveBeenCalledTimes(1));
  chooseEffort("ArrowLeft", 37);
  await act(async () =>
    first.resolve({ ...effortView, value: { level: "high" } }),
  );
  await waitFor(() => expect(sessionThinkingApi.set).toHaveBeenCalledTimes(2));
  await act(async () => second.reject(new Error("save failed")));
  expect(container.querySelector("section strong")).toHaveTextContent(
    "thinkingControl.high",
  );
  expect(slider).toHaveAttribute("aria-valuenow", "3");
});

it("discards queued writes and responses when switching chats", async () => {
  vi.mocked(sessionThinkingApi.get).mockResolvedValue(effortView);
  const first = deferred<ThinkingView>();
  vi.mocked(sessionThinkingApi.set).mockReturnValueOnce(first.promise);
  const { rerender } = renderWithProviders(
    <SessionThinking agentId="a" sessionId="s" chatId="c" />,
  );
  const slider = await screen.findByRole("slider");
  await waitFor(() =>
    expect(slider).not.toHaveAttribute("aria-disabled", "true"),
  );
  chooseEffort("End", 35);
  await waitFor(() => expect(sessionThinkingApi.set).toHaveBeenCalledTimes(1));
  chooseEffort("ArrowLeft", 37);
  rerender(<SessionThinking agentId="a" sessionId="other" chatId="other" />);
  await waitFor(() =>
    expect(sessionThinkingApi.get).toHaveBeenLastCalledWith(
      "a",
      "other",
      "other",
    ),
  );
  await act(async () =>
    first.resolve({ ...effortView, value: { level: "high" } }),
  );
  expect(sessionThinkingApi.set).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("slider")).toHaveAttribute("aria-valuenow", "1");
});

vi.mock("./sessionThinkingApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./sessionThinkingApi")>()),
  sessionThinkingApi: { get: vi.fn(), set: vi.fn() },
}));
vi.mock("../session-settings/sessionModel", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../session-settings/sessionModel")
  >()),
  resetSessionModel: vi.fn(),
  saveDecisionSettings: vi.fn(),
}));
vi.mock("../../pages/Chat/ModelSelector/ModelPickerPopover", () => ({
  ModelPickerPopover: ({
    children,
    content,
  }: {
    children: ReactNode;
    content: ReactNode;
  }) => (
    <>
      {children}
      {content}
    </>
  ),
}));

it.each([null, "decision-chat"])(
  "preserves advanced decision settings and thinking edits (chat=%s)",
  async (chatId) => {
    const decision = { enabled: false, configured: true, override: null };
    const view = { ...effortView, decision };
    const decisionSave = deferred<typeof decision>();
    const thinkingSave = deferred<ThinkingView>();
    vi.mocked(sessionThinkingApi.get).mockResolvedValue(view);
    vi.mocked(saveDecisionSettings).mockReturnValueOnce(decisionSave.promise);
    vi.mocked(sessionThinkingApi.set).mockReturnValueOnce(thinkingSave.promise);
    const { container } = renderWithProviders(
      <SessionThinking
        agentId="decision-agent"
        sessionId="decision-session"
        chatId={chatId}
      />,
    );
    const slider = await screen.findByRole("slider");
    await waitFor(() =>
      expect(slider).not.toHaveAttribute("aria-disabled", "true"),
    );
    fireEvent.click(screen.getByText("chat.sessionSettings.advanced"));
    const toggle = screen.getByRole("switch", {
      name: "chat.sessionSettings.decisionEnabled",
    });
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(saveDecisionSettings).toHaveBeenCalledWith(
        "decision-agent",
        { sessionId: "decision-session", chatId },
        { ...decision, enabled: true, override: true },
      ),
    );
    expect(toggle).toBeDisabled();
    expect(container.querySelector('[class*="spin-blur"]')).toBeNull();
    await act(async () => decisionSave.resolve({ ...decision, enabled: true }));
    expect(toggle).toBeChecked();
    expect(toggle).toBeEnabled();
    expect(slider).not.toHaveAttribute("aria-disabled", "true");

    chooseEffort("End", 35);
    if (chatId) {
      await waitFor(() =>
        expect(sessionThinkingApi.set).toHaveBeenCalledTimes(1),
      );
      expect(toggle).toBeDisabled();
      await act(async () =>
        thinkingSave.resolve({
          ...view,
          decision: { ...decision, enabled: true },
          value: { level: "high" },
        }),
      );
    } else {
      expect(sessionThinkingApi.set).not.toHaveBeenCalled();
    }
    expect(toggle).toBeChecked();
    expect(toggle).toBeEnabled();
    expect(slider).toHaveAttribute("aria-valuenow", "3");
    clearPendingThinking("decision-agent", "decision-session");
  },
);

it("shows the Hub catalog name in the trigger and panel instead of its routing ID", async () => {
  const model = "ddfc504d910c40d5afb25250933df0000";
  vi.mocked(sessionThinkingApi.get).mockResolvedValue({
    model,
    model_name: "Organization Qwen",
    provider_id: "hub-managed",
    model_key: `hub-managed:${model}`,
    model_source: "session",
    control: { kind: "unsupported", efforts: [], supports_off: false },
    value: { level: "inherit" },
    effective: { level: "inherit" },
    source: "model",
    reason: null,
  });
  renderWithProviders(
    <SessionThinking agentId="agent" sessionId="session" chatId="chat" />,
  );
  expect(await screen.findAllByText("Organization Qwen")).toHaveLength(2);
  expect(screen.queryByText(model)).not.toBeInTheDocument();
});

it("restores the default model directly even when thinking is unsupported", async () => {
  const view = {
    model: "custom",
    model_name: "Custom model",
    provider_id: "kilo",
    model_key: "kilo:custom",
    model_source: "session" as const,
    control: { kind: "unsupported" as const, efforts: [], supports_off: false },
    value: { level: "inherit" as const },
    effective: { level: "inherit" as const },
    source: "model" as const,
    reason: null,
  };
  vi.mocked(sessionThinkingApi.get).mockResolvedValue(view);
  vi.mocked(resetSessionModel).mockResolvedValue({ active_llm: null });
  renderWithProviders(
    <SessionThinking agentId="agent" sessionId="session" chatId="chat" />,
  );
  await screen.findAllByText("Custom model");
  vi.mocked(sessionThinkingApi.get).mockResolvedValue({
    ...view,
    model: "default",
    model_name: "Default model",
    model_source: "agent",
  });
  fireEvent.click(
    screen.getByRole("button", { name: "thinkingControl.resetModel" }),
  );
  await waitFor(() =>
    expect(resetSessionModel).toHaveBeenCalledWith("agent", {
      sessionId: "session",
      chatId: "chat",
    }),
  );
  expect(await screen.findAllByText("Default model")).toHaveLength(2);
  expect(sessionThinkingApi.set).not.toHaveBeenCalled();
});

it("hides the Hub routing ID when no readable name is available", async () => {
  const model = "ddfc504d910c40d5afb25250933df0000";
  vi.mocked(sessionThinkingApi.get).mockResolvedValue({
    model,
    model_name: null,
    provider_id: "hub-managed",
    model_key: `hub-managed:${model}`,
    model_source: "session",
    control: { kind: "unsupported", efforts: [], supports_off: false },
    value: { level: "inherit" },
    effective: { level: "inherit" },
    source: "model",
    reason: null,
  });
  renderWithProviders(
    <SessionThinking agentId="agent" sessionId="session" chatId="chat" />,
  );
  await waitFor(() => expect(sessionThinkingApi.get).toHaveBeenCalled());
  expect(screen.queryByText(model)).not.toBeInTheDocument();
});

it.each([null, "chat"])(
  "resets thinking-only overrides to agent defaults (chat=%s)",
  async (chatId) => {
    const view = {
      model: "qwen",
      model_name: "Qwen",
      provider_id: "dashscope",
      model_key: "dashscope:qwen",
      model_source: "agent" as const,
      control: {
        kind: "effort" as const,
        efforts: ["low" as const, "high" as const],
        supports_off: false,
      },
      value: { level: "high" as const },
      effective: { level: "high" as const },
      source: "session" as const,
      reason: null,
    };
    vi.mocked(sessionThinkingApi.get).mockResolvedValue(view);
    vi.mocked(resetSessionModel).mockImplementation(async () => {
      clearPendingThinking("agent", "session");
      return { active_llm: null };
    });
    setPendingThinking("agent", "session", { level: "high" }, view.model_key);
    renderWithProviders(
      <SessionThinking agentId="agent" sessionId="session" chatId={chatId} />,
    );
    const reset = await screen.findByRole("button", {
      name: "thinkingControl.resetModel",
    });
    await waitFor(() => expect(reset).toBeEnabled());
    vi.mocked(sessionThinkingApi.get).mockResolvedValue({
      ...view,
      value: { level: "inherit" },
      effective: { level: "low" },
      source: "agent",
    });
    fireEvent.click(reset);
    await waitFor(() =>
      expect(screen.getByRole("slider")).toHaveAttribute("aria-valuenow", "0"),
    );
    await waitFor(() => expect(reset).toBeDisabled());

    expect(resetSessionModel).toHaveBeenCalledWith("agent", {
      sessionId: "session",
      chatId,
    });
  },
);

it("keeps the new depth visible while saving instead of reverting the indicator", async () => {
  const view = {
    model: "qwen",
    model_name: "Qwen",
    provider_id: "dashscope",
    model_key: "dashscope:qwen",
    control: {
      kind: "budget" as const,
      efforts: [],
      supports_off: true,
      budget_min: 1000,
      budget_max: 10000,
    },
    value: { level: "budget" as const, budget_tokens: 1000 },
    effective: { level: "budget" as const, budget_tokens: 1000 },
    source: "session" as const,
    reason: null,
  };
  vi.mocked(sessionThinkingApi.get).mockResolvedValue(view);
  let resolve!: (value: typeof view) => void;
  vi.mocked(sessionThinkingApi.set).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  renderWithProviders(<SessionThinking agentId="a" sessionId="s" chatId="c" />);
  await screen.findByRole("img", { name: "thinkingControl.light" });
  fireEvent.click(
    screen.getByRole("button", { name: "thinkingControl.budget" }),
  );
  const input = screen.getByRole("spinbutton", {
    name: "thinkingControl.budget",
  });
  fireEvent.change(input, { target: { value: "10000" } });
  expect(
    screen.getByRole("img", { name: "thinkingControl.intensive" }),
  ).toBeInTheDocument();
  fireEvent.blur(input);
  expect(
    screen.getByRole("img", { name: "thinkingControl.intensive" }),
  ).toBeInTheDocument();
  resolve({ ...view, value: { level: "budget", budget_tokens: 10000 } });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "thinkingControl.budget" }),
    ).toBeEnabled(),
  );
  expect(
    screen.getByRole("img", { name: "thinkingControl.intensive" }),
  ).toBeInTheDocument();
});
