import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSessionListStore } from "../../stores/sessionListStore";
import { useAgentStore } from "../../stores/agentStore";
import { useSessionAttentionStore } from "../../stores/sessionAttentionStore";
import ConsolePollService from "../../components/ConsolePollService";
import { RouteDocumentTitle } from "./RouteDocumentTitle";
import { getRouteTitle } from "./routeTitle";

const notificationMocks = vi.hoisted(() => ({
  getPushMessages: vi.fn(),
  setApprovals: vi.fn(),
  observe: vi.fn(),
}));

vi.mock("../../api/modules/console", () => ({
  consoleApi: { getPushMessages: notificationMocks.getPushMessages },
}));
vi.mock("../../contexts/ApprovalContext", () => ({
  useApprovalContext: () => ({ setApprovals: notificationMocks.setApprovals }),
}));
vi.mock("../../notifications/useApprovalNotifications", () => ({
  useApprovalNotifications: () => notificationMocks.observe,
}));
vi.mock("../../notifications/useSystemNotifications", () => ({
  useSystemNotifications: () => notificationMocks.observe,
}));

describe("RouteDocumentTitle", () => {
  beforeEach(() => {
    useSessionListStore.setState({ sessions: [], resolvedRouteSession: null });
    useSessionAttentionStore.setState({ seenFinishedAt: {} });
    notificationMocks.getPushMessages
      .mockReset()
      .mockResolvedValue({ messages: [] });
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("clears completion and notification dots together on visibility", async () => {
    vi.useFakeTimers();
    const initial = {
      id: "chat-a",
      name: "Project plan",
      lastFinishedAt: null,
      messages: [],
    };
    useSessionListStore.setState({ sessions: [initial] });
    render(
      <>
        <RouteDocumentTitle title="Chat" sessionId="chat-a" />
        <ConsolePollService />
      </>,
    );
    await act(() => vi.advanceTimersByTimeAsync(0));
    notificationMocks.getPushMessages.mockResolvedValue({
      messages: [{ id: "notification-1", text: "Done" }],
    });

    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
      useSessionListStore.setState({
        sessions: [{ ...initial, lastFinishedAt: "2026-11-09T10:00:00Z" }],
      });
    });
    await act(() => vi.advanceTimersByTimeAsync(30800));
    expect(document.title).toBe("• Project plan · QwenPaw");

    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(document.title).toBe("Project plan · QwenPaw");
    await act(() => vi.advanceTimersByTimeAsync(1600));
    expect(document.title).toBe("Project plan · QwenPaw");
  });

  it("keeps a completion dot until the current tab becomes visible", () => {
    const initial = {
      id: "local-a",
      realId: "chat-a",
      name: "Project plan",
      lastFinishedAt: null,
      messages: [],
    };
    useSessionListStore.setState({ sessions: [initial] });
    render(<RouteDocumentTitle title="Chat" sessionId="chat-a" />);

    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
      useSessionListStore.setState({
        sessions: [{ ...initial, lastFinishedAt: "2026-11-09T10:00:00Z" }],
      });
    });
    expect(document.title).toBe("• Project plan · QwenPaw");

    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(document.title).toBe("Project plan · QwenPaw");
    const agentId = useAgentStore.getState().selectedAgent;
    expect(
      useSessionAttentionStore.getState().seenFinishedAt[`${agentId}:chat-a`],
    ).toBe("2026-11-09T10:00:00Z");

    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(document.title).toBe("Project plan · QwenPaw");
  });

  it.each(["idle", "running"])(
    "does not infer a completion from status %s without a new timestamp",
    (status) => {
      vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
      const initial = {
        id: "chat-a",
        name: "Project plan",
        lastFinishedAt: "2026-11-09T09:00:00Z",
        messages: [],
      };
      useSessionListStore.setState({ sessions: [initial] });
      render(<RouteDocumentTitle title="Chat" sessionId="chat-a" />);
      act(() => {
        useSessionListStore.setState({ sessions: [{ ...initial, status }] });
      });
      expect(document.title).toBe("Project plan · QwenPaw");
    },
  );

  it("updates the browser title when the active route changes", () => {
    const { rerender } = render(<RouteDocumentTitle title="Chat" />);
    expect(document.title).toBe("Chat · QwenPaw");

    rerender(<RouteDocumentTitle title="Models" />);
    expect(document.title).toBe("Models · QwenPaw");
  });

  it.each(["chat-a", "local-a", "runtime-a"])(
    "uses the session name for route reference %s",
    (sessionId) => {
      useSessionListStore.setState({
        sessions: [
          {
            id: "local-a",
            realId: "chat-a",
            sessionId: "runtime-a",
            name: "Project plan",
            messages: [],
          },
        ],
      });

      render(<RouteDocumentTitle title="Chat" sessionId={sessionId} />);

      expect(document.title).toBe("Project plan · QwenPaw");
    },
  );

  it.each(["id", "sessionId"])(
    "prefers a canonical Chat over another session's %s alias",
    (alias) => {
      useSessionListStore.setState({
        sessions: [
          {
            id: "local-a",
            realId: "chat-a",
            [alias]: "chat-b",
            name: "Conversation A",
            messages: [],
          },
          { id: "chat-b", name: "Conversation B", messages: [] },
        ],
      });

      render(<RouteDocumentTitle title="Chat" sessionId="chat-b" />);

      expect(document.title).toBe("Conversation B · QwenPaw");
    },
  );

  it("prefers an SDK display ID over an unconfirmed runtime alias", () => {
    useSessionListStore.setState({
      sessions: [
        {
          id: "chat-a",
          sessionId: "local-b",
          name: "Conversation A",
          messages: [],
        },
        {
          id: "local-b",
          realId: "chat-b",
          name: "Conversation B",
          messages: [],
        },
      ],
    });

    render(<RouteDocumentTitle title="Chat" sessionId="local-b" />);

    expect(document.title).toBe("Conversation B · QwenPaw");
  });

  it("uses the route title for an ambiguous runtime alias", () => {
    useSessionListStore.setState({
      sessions: [
        { id: "chat-a", sessionId: "shared", name: "A", messages: [] },
        { id: "chat-b", sessionId: "shared", name: "B", messages: [] },
      ],
    });

    render(<RouteDocumentTitle title="Chat" sessionId="shared" />);

    expect(document.title).toBe("Chat · QwenPaw");
  });

  it("updates the title when switching sessions or leaving chat", () => {
    useSessionListStore.setState({
      sessions: [
        { id: "chat-a", name: "Project plan", messages: [] },
        { id: "chat-b", name: "Release notes", messages: [] },
      ],
    });
    const { rerender } = render(
      <RouteDocumentTitle title="Chat" sessionId="chat-a" />,
    );
    expect(document.title).toBe("Project plan · QwenPaw");

    rerender(<RouteDocumentTitle title="Chat" sessionId="chat-b" />);
    expect(document.title).toBe("Release notes · QwenPaw");

    rerender(<RouteDocumentTitle title="Models" />);
    expect(document.title).toBe("Models · QwenPaw");

    act(() => {
      useSessionListStore.setState({
        sessions: [{ id: "chat-b", name: "Renamed chat", messages: [] }],
      });
    });
    expect(document.title).toBe("Models · QwenPaw");
  });

  it("tracks session loading, renaming, and removal through the shared store", () => {
    render(<RouteDocumentTitle title="Chat" sessionId="chat-a" />);
    expect(document.title).toBe("Chat · QwenPaw");

    act(() => {
      useSessionListStore.setState({
        sessions: [{ id: "chat-a", name: "Project plan", messages: [] }],
      });
    });
    expect(document.title).toBe("Project plan · QwenPaw");

    act(() => {
      useSessionListStore.setState({
        sessions: [{ id: "chat-a", name: "Release notes", messages: [] }],
      });
    });
    expect(document.title).toBe("Release notes · QwenPaw");

    act(() => useSessionListStore.setState({ sessions: [] }));
    expect(document.title).toBe("Chat · QwenPaw");
  });

  it.each(["", "   "])(
    "uses the localized route title for an unnamed session (%j)",
    (name) => {
      useSessionListStore.setState({
        sessions: [{ id: "chat-a", name, messages: [] }],
      });

      render(<RouteDocumentTitle title="聊天" sessionId="chat-a" />);

      expect(document.title).toBe("聊天 · QwenPaw");
    },
  );

  it.each([undefined, "new", "missing"])(
    "uses the route title when the reference is %s",
    (sessionId) => {
      useSessionListStore.setState({
        sessions: [
          { id: "chat-a", name: "Previous conversation", messages: [] },
          { id: "new", name: "Draft conversation", messages: [] },
        ],
      });

      render(<RouteDocumentTitle title="Chat" sessionId={sessionId} />);

      expect(document.title).toBe("Chat · QwenPaw");
    },
  );

  it("publishes the session title through the existing notification event", () => {
    const onTitleChange = vi.fn();
    document.addEventListener("qwenpaw:document-title-change", onTitleChange);
    try {
      useSessionListStore.setState({
        sessions: [{ id: "chat-a", name: "Project plan", messages: [] }],
      });

      render(<RouteDocumentTitle title="Chat" sessionId="chat-a" />);

      expect(onTitleChange).toHaveBeenLastCalledWith(
        expect.objectContaining({ detail: "Project plan · QwenPaw" }),
      );

      act(() => {
        useSessionListStore.setState({
          sessions: [{ id: "chat-a", name: "Release notes", messages: [] }],
        });
      });
      expect(onTitleChange).toHaveBeenLastCalledWith(
        expect.objectContaining({ detail: "Release notes · QwenPaw" }),
      );
    } finally {
      document.removeEventListener(
        "qwenpaw:document-title-change",
        onTitleChange,
      );
    }
  });

  it("keeps the brand title unchanged when no route is selected", () => {
    render(<RouteDocumentTitle title="QwenPaw" />);
    expect(document.title).toBe("QwenPaw");
  });
});

describe("getRouteTitle", () => {
  it("resolves localized route metadata", () => {
    expect(
      getRouteTitle(
        {
          id: "plugin.page",
          path: "/plugin",
          meta: {
            domain: "extensions",
            title: (locale) => (locale === "zh" ? "插件" : "Plugin"),
            scope: "global",
            layout: "standard",
            navigation: "context",
          },
        },
        "zh",
      ),
    ).toBe("插件");
  });

  it("uses a safe title for legacy plugin routes", () => {
    expect(
      getRouteTitle({ id: "plugin.audit-log", path: "/audit-log" }, "en"),
    ).toBe("Audit Log");
  });
});
