import { beforeEach, expect, it, vi } from "vitest";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ModelSelector from "./index";
import { request } from "@/api/request";
import { useCreateNewSession } from "../hooks/useCreateNewSession";
import { draftModel } from "../conversationModel";
import sessionApi from "../sessionApi";

const state = vi.hoisted(() => ({
  user: { id: "alice" },
  selectedAgent: "agent-a",
  agents: [],
  createSession: vi.fn(),
}));
vi.mock("@/api/request", () => ({ request: vi.fn() }));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: Object.assign(
    (selector?: (s: typeof state) => unknown) =>
      selector ? selector(state) : state,
    { getState: () => state },
  ),
  isAgentHistoricalReadOnly: () => false,
}));
vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessions: () => ({ createSession: state.createSession }),
}));
vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { warning: vi.fn() } }),
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(
    (selector?: (s: typeof state) => unknown) =>
      selector ? selector(state) : state,
    { getState: () => state },
  ),
}));
vi.mock("../sessionApi", () => ({
  default: {
    getRealIdForSession: (id: string) => id,
    preferredChatId: "old-chat",
    lastNavigatedChatId: "old-chat",
  },
}));
vi.mock("../turnUsageStore", () => ({
  useTurnUsageStore: { getState: () => ({ setActiveMaxInputLength: vi.fn() }) },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "modelSelector.resetConversation": "恢复默认",
        "modelSelector.conversationModel": "会话模型",
      })[key] ?? key,
  }),
}));

const catalog = {
  enforced: true,
  models: [
    {
      id: "one",
      provider_id: "p",
      provider_name: "Provider",
      model: "one",
      name: "One",
      max_input_length: 32000,
    },
    {
      id: "two",
      provider_id: "p",
      provider_name: "Provider",
      model: "two",
      name: "Two",
      max_input_length: 64000,
    },
  ],
};
beforeEach(() => {
  state.user = { id: "alice" };
  state.createSession.mockReset();
  sessionApi.preferredChatId = "old-chat";
  sessionApi.lastNavigatedChatId = "old-chat";
  window.history.replaceState({}, "", "/chat/chat-a");
  vi.mocked(request)
    .mockReset()
    .mockImplementation(async (path, options) => {
      if (path.startsWith("/model-catalog/default"))
        return {
          active_llm: { provider_id: "p", model: "one" },
          locked: false,
        };
      if (path.startsWith("/model-catalog")) return catalog;
      const selected = options?.body
        ? JSON.parse(String(options.body))
        : { provider_id: "p", model: "one" };
      return {
        active_llm: selected ?? { provider_id: "p", model: "one" },
        locked: false,
        effective_max_input_length: 32000,
      };
    });
});

it("creates the blank SDK session before broadcasting the model reset", async () => {
  const order: string[] = [];
  state.createSession.mockImplementation(async () => {
    order.push("create-session");
  });
  const onNewChatReset = () => order.push("new-chat-reset");
  const onModelSwitched = () => order.push("model-reset");
  window.addEventListener("qwenpaw:new-chat-reset", onNewChatReset);
  window.addEventListener("model-switched", onModelSwitched);

  render(
    <MemoryRouter initialEntries={["/chat"]}>
      <DraftView />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByText("New draft"));

  await waitFor(() =>
    expect(order).toEqual([
      "new-chat-reset",
      "create-session",
      "new-chat-reset",
      "model-reset",
    ]),
  );
  expect(sessionApi.preferredChatId).toBeNull();
  expect(sessionApi.lastNavigatedChatId).toBeNull();
  window.removeEventListener("qwenpaw:new-chat-reset", onNewChatReset);
  window.removeEventListener("model-switched", onModelSwitched);
});
function DraftView() {
  const create = useCreateNewSession();
  return (
    <>
      <button onClick={create}>New draft</button>
      <ModelSelector />
    </>
  );
}

it("clears a draft through the real new-session hook and on leaving", async () => {
  window.history.replaceState({}, "", "/chat");
  const rendered = render(
    <MemoryRouter initialEntries={["/chat"]}>
      <DraftView />
    </MemoryRouter>,
  );
  await screen.findByText("Provider / One");
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByTitle("64000 tokens"));
  await waitFor(() => expect(draftModel()?.model).toBe("two"));
  fireEvent.click(screen.getByText("New draft"));
  await waitFor(() => expect(draftModel()).toBeUndefined());
  await waitFor(() =>
    expect(
      document.querySelector(".ant-select-selection-item")?.textContent,
    ).toBe("Provider / One"),
  );
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByTitle("64000 tokens"));
  await waitFor(() => expect(draftModel()?.model).toBe("two"));
  rendered.unmount();
  expect(draftModel()).toBeUndefined();
  render(
    <MemoryRouter initialEntries={["/chat"]}>
      <ModelSelector />
    </MemoryRouter>,
  );
  await screen.findByText("Provider / One");
});
function view() {
  return (
    <MemoryRouter initialEntries={["/chat/chat-a"]}>
      <ModelSelector />
    </MemoryRouter>
  );
}

it("sends actual selected model and clear only to the current conversation", async () => {
  render(view());
  await screen.findByText("Provider / One");
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByTitle("64000 tokens"));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/chats/chat-a/model", {
      method: "PUT",
      body: '{"provider_id":"p","model":"two"}',
    }),
  );
  await waitFor(() =>
    expect(screen.getByText("恢复默认").closest("button")).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByText("恢复默认"));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/chats/chat-a/model", {
      method: "PUT",
      body: "null",
    }),
  );
  expect(
    vi.mocked(request).mock.calls.some(([path]) => path === "/models/active"),
  ).toBe(false);
});
it("ignores an old account catalog response after switching accounts", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(request).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const rendered = render(view());
  state.user = { id: "bob" };
  rendered.rerender(view());
  await screen.findByText("Provider / One");
  await act(async () =>
    finish({
      enforced: true,
      models: [{ ...catalog.models[0], name: "Alice private" }],
    }),
  );
  expect(screen.queryByText(/Alice private/)).toBeNull();
});
it("shows catalog failures without offering an unauthorized model", async () => {
  vi.mocked(request).mockRejectedValue(new Error("catalog_unavailable"));
  render(view());
  await screen.findByText("catalog_unavailable");
  expect(screen.queryByText("Provider / One")).toBeNull();
});

it("uses the new agent default while the URL still points to the previous agent chat", async () => {
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.startsWith("/model-catalog/default")) {
      return {
        active_llm: { provider_id: "p", model: "one" },
        source: "platform",
        model_override: null,
        locked: false,
        effective_max_input_length: 32000,
      };
    }
    if (path.startsWith("/model-catalog")) return catalog;
    if (path === "/chats/chat-a/model") {
      throw new Error('Chat not found - {"detail":"Chat not found"}');
    }
    throw new Error(`unexpected request: ${path}`);
  });

  render(view());

  expect(await screen.findByText("Provider / One")).toBeInTheDocument();
  expect(request).toHaveBeenCalledWith(
    "/model-catalog/default?agent_id=agent-a",
  );
});
