import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PostAssistance } from "./PostAssistance";
import type { AssistantSession } from "./writingSession";
vi.mock("@/api/modules/agents", () => ({
  agentsApi: { listAgents: vi.fn(async () => ({ agents: [] })) },
}));
vi.mock("@/api/modules/chat", () => ({
  chatApi: { listChats: vi.fn(async () => []) },
}));
vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
it("restores the conversation and log context without clearing them on mount", async () => {
  const snapshot: AssistantSession = {
    language: "zh",
    writingStyle: "detailed",
    writingAgent: "writer",
    history: [
      { role: "user", content: "My request" },
      { role: "assistant", content: "# Suggested article\n\nPreserved reply" },
    ],
    result: "# Suggested article\n\nPreserved reply",
    agent: "diagnostic-agent",
    session: "session-1",
    minutes: 15,
    evidence: [{ id: "log-1", content: "Reviewed log excerpt" }],
    warnings: [],
    publicImages: {},
    insertedImages: {},
  };
  const onSessionChange = vi.fn();
  render(
    <PostAssistance
      sessionState={snapshot}
      onSessionChange={onSessionChange}
      articleType="discussion"
      resources={[]}
      draft=""
      instructions=""
      onInstructions={() => {}}
      onInsertImage={async () => {}}
      onApply={() => {}}
      onBusy={() => {}}
      screenshots={{
        images: [],
        setImages: vi.fn(),
        loading: false,
        error: "",
        add: vi.fn(),
      }}
    />,
  );
  expect(screen.getByText("My request")).toBeInTheDocument();
  expect(screen.getByText("Preserved reply")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "communityAssist.apply" }),
  ).toBeEnabled();
  await waitFor(() => expect(onSessionChange).toHaveBeenCalled());
  expect(
    onSessionChange.mock.calls[onSessionChange.mock.calls.length - 1]?.[0],
  ).toMatchObject(snapshot);
});
