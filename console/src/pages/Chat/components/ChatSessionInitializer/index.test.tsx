import { act, render, waitFor } from "@testing-library/react";
import type { IAgentScopeRuntimeWebUIRef } from "@agentscope-ai/chat";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { useAgentStore } from "../../../../stores/agentStore";
import sessionApi from "../../sessionApi";
import ChatSessionInitializer from "./index";

const state = vi.hoisted(() => ({
  sessions: [{ id: "new-chat", realId: "new-chat" }],
  currentSessionId: "old-chat",
  setCurrentSessionId: vi.fn(),
  setSessions: vi.fn(),
}));
vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessionsState: () => state,
}));
vi.mock("../../hooks/useCreateNewSession", () => ({
  useCreateNewSession: () => vi.fn(),
}));

beforeEach(() => {
  state.currentSessionId = "old-chat";
  state.setCurrentSessionId.mockClear();
  sessionApi.setActiveAgent("default");
  useAgentStore.setState({
    selectedAgent: "default",
    lastChatIdByAgent: { default: "old-chat" },
  });
  sessionApi.lastNavigatedChatId = null;
  sessionApi.isSessionSwitching = false;
  vi.restoreAllMocks();
});

it("applies the URL even when a navigation marker exists but SDK selection is stale", () => {
  sessionApi.lastNavigatedChatId = "new-chat";
  render(
    <MemoryRouter initialEntries={["/chat/new-chat"]}>
      <ChatSessionInitializer />
    </MemoryRouter>,
  );
  expect(state.setCurrentSessionId).toHaveBeenCalledWith("new-chat");
});

it("repairs a stale SDK selection after completion without reloading on list polling", () => {
  state.currentSessionId = "new-chat";
  const view = render(
    <MemoryRouter initialEntries={["/chat/new-chat"]}>
      <ChatSessionInitializer />
    </MemoryRouter>,
  );
  state.sessions = [...state.sessions];
  view.rerender(
    <MemoryRouter initialEntries={["/chat/new-chat"]}>
      <ChatSessionInitializer />
    </MemoryRouter>,
  );
  expect(state.setCurrentSessionId).not.toHaveBeenCalled();
  state.currentSessionId = "old-chat";
  view.rerender(
    <MemoryRouter initialEntries={["/chat/new-chat"]}>
      <ChatSessionInitializer />
    </MemoryRouter>,
  );
  expect(state.setCurrentSessionId).toHaveBeenCalledWith("new-chat");
});

it("does not persist stale sessions during an agent ownership transition", () => {
  sessionApi.setActiveAgent("previous-agent");
  render(
    <MemoryRouter initialEntries={["/chat/new-chat"]}>
      <ChatSessionInitializer />
    </MemoryRouter>,
  );
  expect(useAgentStore.getState().lastChatIdByAgent.default).toBe("old-chat");
});

it("persists a valid URL selection so leaving the page restores that chat", async () => {
  render(
    <MemoryRouter initialEntries={["/chat/new-chat"]}>
      <ChatSessionInitializer />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(useAgentStore.getState().lastChatIdByAgent.default).toBe("new-chat"),
  );
});

it("does not persist a URL absent from the accessible session list", () => {
  render(
    <MemoryRouter initialEntries={["/chat/foreign-chat"]}>
      <ChatSessionInitializer />
    </MemoryRouter>,
  );
  expect(useAgentStore.getState().lastChatIdByAgent.default).toBe("old-chat");
});

it("keeps the in-memory restore target aligned with an accessible URL", () => {
  sessionApi.lastActiveChatId = "old-chat";
  render(
    <MemoryRouter initialEntries={["/chat/new-chat"]}>
      <ChatSessionInitializer />
    </MemoryRouter>,
  );
  expect(sessionApi.lastActiveChatId).toBe("new-chat");
});

it("restores the URL selection when a switch finishes after the page mounts", () => {
  sessionApi.isSessionSwitching = true;
  render(
    <MemoryRouter initialEntries={["/chat/new-chat"]}>
      <ChatSessionInitializer />
    </MemoryRouter>,
  );
  expect(state.setCurrentSessionId).not.toHaveBeenCalled();

  act(() => sessionApi.finishSessionSwitch());

  expect(state.setCurrentSessionId).toHaveBeenCalledWith("new-chat");
});

it("restores canonical messages when returning to an already-selected URL with an empty runtime", async () => {
  state.currentSessionId = "new-chat";
  const removeAllMessages = vi.fn();
  const updateMessage = vi.fn();
  const runtimeRef = {
    current: {
      messages: {
        getMessages: () => [],
        removeAllMessages,
        updateMessage,
      },
    },
  } as unknown as React.RefObject<IAgentScopeRuntimeWebUIRef | null>;
  const canonicalMessage = { id: "persisted-user", role: "user", content: [] };
  vi.spyOn(sessionApi, "preloadSession").mockResolvedValue({
    session: {
      id: "new-chat",
      name: "restored",
      messages: [canonicalMessage],
    },
    realId: "new-chat",
  } as never);

  render(
    <MemoryRouter initialEntries={["/chat/new-chat"]}>
      <ChatSessionInitializer runtimeRef={runtimeRef} />
    </MemoryRouter>,
  );

  await waitFor(() => expect(removeAllMessages).toHaveBeenCalledOnce());
  expect(updateMessage).toHaveBeenCalledWith(canonicalMessage);
  expect(state.setCurrentSessionId).not.toHaveBeenCalled();
});
