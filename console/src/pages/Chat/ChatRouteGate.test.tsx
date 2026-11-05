import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatHistory, ChatSpec } from "../../api/types";
import { chatApi } from "../../api/modules/chat";
import { useAgentStore } from "../../stores/agentStore";
import ChatRouteGate from "./ChatRouteGate";
import { prefetchChatHistory } from "./chatRoutePrefetch";
import sessionApi from "./sessionApi";

vi.mock("./index", () => ({
  default: () => <div>Chat page</div>,
}));

vi.mock("./sessionApi", () => ({
  default: {
    getActiveOwner: vi.fn(() => ({ agentId: "b", generation: 2 })),
    registerResolvedChat: vi.fn(),
  },
}));

vi.mock("./chatRoutePrefetch", () => ({
  prefetchChatHistory: vi.fn(),
}));

const TARGET = "22222222-2222-4222-8222-222222222222";

function chat(status?: ChatSpec["status"]): ChatSpec {
  return {
    id: TARGET,
    name: "Target conversation",
    session_id: `runtime-${TARGET}`,
    user_id: "target-user",
    channel: "console",
    created_at: null,
    updated_at: null,
    status,
  };
}

function history(): ChatHistory {
  return {
    messages: [
      {
        id: "user-1",
        role: "user",
        type: "message",
        content: [{ type: "text", text: "Preview question" }],
      },
      {
        id: "assistant-1",
        role: "assistant",
        type: "message",
        content: [{ type: "text", text: "**Preview answer**" }],
      },
    ],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function mount(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ChatRouteGate />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  useAgentStore.setState({ selectedAgent: "a" });
  vi.mocked(prefetchChatHistory).mockResolvedValue(history());
});

describe("ChatRouteGate", () => {
  it("resolves a cold link before mounting the Chat page", async () => {
    const pending = deferred<{ agent_id: string; chat: ChatSpec }>();
    const resolve = vi
      .spyOn(chatApi, "resolveChat")
      .mockReturnValue(pending.promise);

    mount(`/chat/${TARGET}`);

    expect(screen.getByRole("status")).toBeVisible();
    expect(screen.queryByText("Chat page")).not.toBeInTheDocument();

    await act(async () => {
      pending.resolve({ agent_id: "b", chat: chat() });
    });

    await waitFor(() => expect(screen.getByText("Chat page")).toBeVisible());
    expect(screen.queryByText("Preview answer")).not.toBeInTheDocument();
    expect(resolve).toHaveBeenCalledWith(TARGET, {
      currentAgentId: "a",
      signal: expect.any(AbortSignal),
    });
    expect(useAgentStore.getState().selectedAgent).toBe("b");
    expect(prefetchChatHistory).toHaveBeenCalledWith(
      TARGET,
      "b",
      expect.any(AbortSignal),
    );
    expect(sessionApi.registerResolvedChat).toHaveBeenCalledWith(
      chat(),
      sessionApi.getActiveOwner(),
    );
  });

  it("opens the draft route without resolving persisted ownership", async () => {
    const resolve = vi.spyOn(chatApi, "resolveChat");

    mount("/chat");

    expect(await screen.findByText("Chat page")).toBeVisible();
    expect(resolve).not.toHaveBeenCalled();
  });

  it("mounts a running chat without waiting for history preview", async () => {
    const pendingHistory = deferred<ChatHistory>();
    vi.spyOn(chatApi, "resolveChat").mockResolvedValue({
      agent_id: "a",
      chat: chat("running"),
    });
    vi.mocked(prefetchChatHistory).mockReturnValue(pendingHistory.promise);

    mount(`/chat/${TARGET}`);

    expect(await screen.findByText("Chat page")).toBeVisible();
    expect(screen.queryByText("Preview answer")).not.toBeInTheDocument();
    expect(sessionApi.registerResolvedChat).toHaveBeenCalledWith(
      chat("running"),
      sessionApi.getActiveOwner(),
    );
  });

  it("retries a failed cold-link resolution", async () => {
    const resolve = vi
      .spyOn(chatApi, "resolveChat")
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ agent_id: "a", chat: chat() });

    mount(`/chat/${TARGET}`);

    expect(await screen.findByRole("alert")).toBeVisible();
    await act(async () => screen.getByRole("button").click());

    await waitFor(() => expect(screen.getByText("Chat page")).toBeVisible());
    expect(resolve).toHaveBeenCalledTimes(2);
  });

  it("resolves the current path after a failed chat changes", async () => {
    const next = "33333333-3333-4333-8333-333333333333";
    const resolve = vi
      .spyOn(chatApi, "resolveChat")
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ agent_id: "a", chat: chat() });
    function NavigateNext() {
      const navigate = useNavigate();
      return (
        <>
          <button onClick={() => navigate(`/chat/${next}`)}>Next</button>
          <button onClick={() => navigate(`/chat/${TARGET}`)}>Back</button>
        </>
      );
    }
    render(
      <MemoryRouter initialEntries={[`/chat/${TARGET}`]}>
        <NavigateNext />
        <ChatRouteGate />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("alert")).toBeVisible();
    fireEvent.click(screen.getByText("Next"));
    await waitFor(() => expect(screen.getByText("Chat page")).toBeVisible());
    expect(resolve.mock.calls.map(([reference]) => reference)).toEqual([
      TARGET,
      next,
    ]);
    const mountedPage = screen.getByText("Chat page");
    fireEvent.click(screen.getByText("Back"));
    expect(screen.getByText("Chat page")).toBe(mountedPage);
    expect(resolve).toHaveBeenCalledTimes(2);
  });
});
