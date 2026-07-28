import { act, render } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import FilesWorkspace from "./FilesWorkspace";
import { notifyProjectDirectoryChanged } from "../project-directory/projectDirectoryChangeEvent";

const lifecycle = vi.hoisted(() => ({
  clearProjectTabs: vi.fn(),
  editorMounted: vi.fn(),
  editorUnmounted: vi.fn(),
  navigatorMounted: vi.fn(),
  navigatorUnmounted: vi.fn(),
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: false }),
}));

vi.mock("../../stores/codingTabsStore", () => ({
  useTabsForScope: () => [],
  useActiveTabPathForScope: () => "",
  useCodingTabsStore: () => ({
    clearProjectTabs: lifecycle.clearProjectTabs,
    closeTab: vi.fn(),
    openTab: vi.fn(),
    setActiveTab: vi.fn(),
    setTabContent: vi.fn(),
    setTabDirty: vi.fn(),
  }),
}));

vi.mock("./FilesNavigator", () => ({
  default: function MockFilesNavigator() {
    useEffect(() => {
      lifecycle.navigatorMounted();
      return () => lifecycle.navigatorUnmounted();
    }, []);
    return <div>navigator</div>;
  },
}));

vi.mock("../../pages/Coding/TabbedEditor", () => ({
  default: function MockTabbedEditor() {
    useEffect(() => {
      lifecycle.editorMounted();
      return () => lifecycle.editorUnmounted();
    }, []);
    return <div>editor</div>;
  },
}));

vi.mock("../../pages/Coding/GitPanel", () => ({
  default: () => <div>git</div>,
}));

describe("FilesWorkspace directory changes", () => {
  it("rebuilds the Session navigator and editor watch host", () => {
    const scope = {
      kind: "session" as const,
      agentId: "agent-a",
      sessionId: "session-a",
      chatId: "chat-a",
    };
    render(<FilesWorkspace scope={scope} />);

    expect(lifecycle.navigatorMounted).toHaveBeenCalledTimes(1);
    expect(lifecycle.editorMounted).toHaveBeenCalledTimes(1);

    act(() => notifyProjectDirectoryChanged(scope));

    expect(lifecycle.clearProjectTabs).toHaveBeenCalledWith(
      "session:agent-a:session-a",
    );
    expect(lifecycle.navigatorUnmounted).toHaveBeenCalledTimes(1);
    expect(lifecycle.navigatorMounted).toHaveBeenCalledTimes(2);
    expect(lifecycle.editorUnmounted).toHaveBeenCalledTimes(1);
    expect(lifecycle.editorMounted).toHaveBeenCalledTimes(2);
  });
});
