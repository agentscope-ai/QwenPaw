import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSessionListStore } from "../../stores/sessionListStore";
import { RouteDocumentTitle } from "./RouteDocumentTitle";
import { getRouteTitle } from "./routeTitle";

describe("RouteDocumentTitle", () => {
  beforeEach(() => {
    useSessionListStore.setState({ sessions: [] });
  });

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
