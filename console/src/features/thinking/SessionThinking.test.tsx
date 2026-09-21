import type { ReactNode } from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { sessionThinkingApi } from "./sessionThinkingApi";
import { resetSessionModel } from "../session-settings/sessionModel";
import { SessionThinking } from "./SessionThinking";

vi.mock("./sessionThinkingApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./sessionThinkingApi")>()),
  sessionThinkingApi: { get: vi.fn(), set: vi.fn() },
}));
vi.mock("../session-settings/sessionModel", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../session-settings/sessionModel")
  >()),
  resetSessionModel: vi.fn(),
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
