import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useEffect, useState } from "react";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAgentStore } from "../../stores/agentStore";
import { useAuthStore } from "../../stores/authStore";
import sessionApi from "./sessionApi";
import ChatRoute from "./route";

const state = vi.hoisted(() => ({
  renders: [] as string[],
  mounts: 0,
  listChats: vi.fn(),
  getChatSpec: vi.fn(),
}));
vi.mock("../../api/modules/chat", async (original) => {
  const actual = await original<typeof import("../../api/modules/chat")>();
  return {
    ...actual,
    chatApi: {
      ...actual.chatApi,
      listChats: state.listChats,
      getChatSpec: state.getChatSpec,
    },
  };
});
vi.mock("./index", () => ({
  default: () => {
    const navigate = useNavigate();
    const [draft, setDraft] = useState("");
    useEffect(() => {
      state.mounts += 1;
    }, []);
    const agent = useAgentStore((value) => value.selectedAgent);
    const path = useLocation().pathname;
    state.renders.push(`${agent}:${path}`);
    return (
      <div>
        <span data-testid="active-chat">
          {agent}:{path}
        </span>
        <input
          aria-label="draft"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          onClick={async () => {
            const session = { name: "新对话" } as { id?: string; name: string };
            await sessionApi.createSession(session);
            const realId = "35d4965f-0299-4dde-b805-98596ec02c4d";
            sessionApi.acceptResolvedChat(
              session.id!,
              realId,
              sessionApi.getActiveOwner(),
            );
            navigate(`/chat/${realId}`);
          }}
        >
          发送首条消息
        </button>
      </div>
    );
  },
}));

function SkillsPage() {
  const navigate = useNavigate();
  return (
    <button
      onClick={() =>
        navigate("/chat/first", {
          state: { chatAgentId: useAgentStore.getState().selectedAgent },
        })
      }
    >
      返回聊天
    </button>
  );
}
function Page({ initial }: { initial: string }) {
  return (
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/skills" element={<SkillsPage />} />
        <Route path="/chat/*" element={<ChatRoute />} />
      </Routes>
    </MemoryRouter>
  );
}
beforeEach(() => {
  cleanup();
  state.renders = [];
  state.mounts = 0;
  sessionApi.resetForTests();
  useAuthStore.setState({ mode: "multi_user" });
  useAgentStore.setState({
    selectedAgent: "default",
    agents: ["default", "designer"].map((id) => ({
      id,
      name: id,
      description: "",
      workspace_dir: "/test/" + id,
      enabled: true,
      backend: "qwenpaw",
    })),
    lastChatIdByAgent: { default: "first", designer: "second" },
  });
  state.listChats
    .mockReset()
    .mockImplementation(async ({ requestContext }) => [
      { id: requestContext.agentId === "designer" ? "second" : "first" },
    ]);
  state.getChatSpec.mockReset().mockImplementation(async (id: string) => ({
    id,
    agent_id: id === "second" ? "designer" : "default",
    access_role: "owner",
    read_only: false,
  }));
});

it("keeps the live chat mounted when the POST resolves its backend UUID", async () => {
  render(<Page initial="/chat" />);
  fireEvent.change(screen.getByRole("textbox", { name: "draft" }), {
    target: { value: "正在流式生成" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送首条消息" }));
  await waitFor(() =>
    expect(screen.getByTestId("active-chat").textContent).toContain(
      "/chat/35d4965f",
    ),
  );
  expect(state.mounts).toBe(1);
  expect(screen.getByRole("textbox", { name: "draft" })).toHaveProperty(
    "value",
    "正在流式生成",
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("switches to the designer's own chat before rendering its conversation", async () => {
  render(<Page initial="/chat/first" />);
  await waitFor(() =>
    expect(screen.getByTestId("active-chat").textContent).toBe(
      "default:/chat/first",
    ),
  );
  act(() => useAgentStore.getState().setSelectedAgent("designer"));
  await waitFor(() =>
    expect(screen.getByTestId("active-chat").textContent).toBe(
      "designer:/chat/second",
    ),
  );
  expect(state.renders).not.toContain("designer:/chat/first");
});

it("returns from skills without switching back to the default agent", async () => {
  render(<Page initial="/skills" />);
  act(() => useAgentStore.getState().setSelectedAgent("designer"));
  fireEvent.click(screen.getByRole("button", { name: "返回聊天" }));
  await waitFor(() =>
    expect(screen.getByTestId("active-chat").textContent).toBe(
      "designer:/chat/second",
    ),
  );
  expect(useAgentStore.getState().selectedAgent).toBe("designer");
  expect(state.renders).not.toContain("default:/chat/first");
});

it("opens a fresh designer view when its saved chat belongs to another agent", async () => {
  render(<Page initial="/skills" />);
  act(() => {
    useAgentStore.getState().setSelectedAgent("designer");
    useAgentStore.getState().setLastChatId("designer", "first");
  });
  fireEvent.click(screen.getByRole("button", { name: "返回聊天" }));
  await waitFor(() =>
    expect(screen.getByTestId("active-chat").textContent).toBe(
      "designer:/chat",
    ),
  );
  expect(sessionApi.lastActiveChatId).toBeNull();
  expect(useAgentStore.getState().selectedAgent).toBe("designer");
});
