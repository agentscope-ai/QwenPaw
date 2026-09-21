import type { ReactNode } from "react";
import { screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { sessionThinkingApi } from "./sessionThinkingApi";
import { SessionThinking } from "./SessionThinking";

vi.mock("./sessionThinkingApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./sessionThinkingApi")>()),
  sessionThinkingApi: { get: vi.fn() },
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
