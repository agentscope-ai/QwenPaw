import type { ReactNode } from "react";
import {
  MemoryRouter,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentDock from "@/components/agent/AgentDock";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { installMockFetch } from "@/test/mockFetch";
import { msg, seedCreatorSession } from "@/test/agentFixtures";

// Counts how often any message markdown is parsed. A keystroke must not walk
// the historical conversation through the remark pipeline again.
const renderCounter = vi.hoisted(() => ({ markdown: 0 }));

vi.mock("react-markdown", () => ({
  default: ({ children }: { children?: ReactNode }) => {
    renderCounter.markdown += 1;
    return <div data-testid="markdown-body">{children}</div>;
  },
}));

function renderDock() {
  return render(
    <MemoryRouter initialEntries={["/project/p1/plan"]}>
      <Routes>
        <Route path="/project/:id/plan" element={<AgentDock />} />
      </Routes>
    </MemoryRouter>,
  );
}

function ProjectSwitcher() {
  const { id } = useParams();
  const navigate = useNavigate();
  const other = id === "p1" ? "p2" : "p1";
  return (
    <button type="button" onClick={() => navigate(`/project/${other}/plan`)}>
      {`go-${other}`}
    </button>
  );
}

function renderDockWithSwitcher() {
  return render(
    <MemoryRouter initialEntries={["/project/p1/plan"]}>
      <Routes>
        <Route
          path="/project/:id/plan"
          element={
            <>
              <AgentDock />
              <ProjectSwitcher />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

const composerBox = () =>
  screen.getByRole("textbox", { name: "输入修改意图，@ 可引用对象…" });

const history = () => [
  msg({ messageId: "u-1", messageSeq: 1, role: "user", text: "先做一版剧本" }),
  msg({
    messageId: "a-1",
    messageSeq: 2,
    role: "assistant",
    source: "creator_agent",
    text: "## 剧本\n\n| 场次 | 内容 |\n| --- | --- |\n| 1 | 开场 |",
  }),
  msg({ messageId: "u-2", messageSeq: 3, role: "user", text: "再改一下" }),
  msg({
    messageId: "a-2",
    messageSeq: 4,
    role: "assistant",
    source: "creator_agent",
    text: "**改好了**\n\n- 第一点\n- 第二点",
  }),
];

describe("AgentDock composer render path", () => {
  beforeEach(() => {
    seedCreatorSession();
    useCreatorSessionStore.setState({ messages: history() });
    useAgentDockUiStore.setState({ draft: "", unsentDrafts: {} });
    useAgentDockUiStore.getState().setOpen(true);
    installMockFetch([]);
    renderCounter.markdown = 0;
  });

  it("does not re-parse history markdown while the user types", () => {
    renderDock();
    const box = composerBox();
    const baseline = renderCounter.markdown;
    expect(baseline).toBeGreaterThan(0);

    for (const value of ["第", "第一", "第一句", "第一句话"]) {
      fireEvent.input(box, { target: { textContent: value } });
    }

    // The root cause of #8706: keystrokes must not reach the shared draft
    // slot, or every input would re-render the whole dock.
    expect(useAgentDockUiStore.getState().draft).toBe("");
    expect(renderCounter.markdown).toBe(baseline);
  });

  it("still re-parses updated messages when the conversation changes", () => {
    renderDock();
    const baseline = renderCounter.markdown;

    act(() =>
      useCreatorSessionStore.setState({
        messages: [
          ...history(),
          msg({
            messageId: "a-3",
            messageSeq: 5,
            role: "assistant",
            source: "creator_agent",
            text: "追加一条回复",
          }),
        ],
      }),
    );

    expect(renderCounter.markdown).toBeGreaterThan(baseline);
  });

  it("keeps an unsent draft across a fold and reopen", async () => {
    renderDock();
    const box = composerBox();
    fireEvent.input(box, {
      target: { textContent: "Keep this unsent instruction" },
    });
    expect(box.textContent).toBe("Keep this unsent instruction");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();
    expect(useAgentDockUiStore.getState().unsentDrafts).toEqual({
      p1: ["Keep this unsent instruction"],
    });

    fireEvent.click(screen.getByRole("button", { name: "创作助手" }));
    await waitFor(() => {
      expect(composerBox().textContent).toBe("Keep this unsent instruction");
    });
  });

  it("parks the outgoing draft on a Project switch and restores it on return", async () => {
    renderDockWithSwitcher();
    fireEvent.input(composerBox(), {
      target: { textContent: "Half-typed for p1" },
    });

    fireEvent.click(screen.getByRole("button", { name: "go-p2" }));
    await waitFor(() =>
      expect(useAgentDockUiStore.getState().unsentDrafts).toEqual({
        p1: ["Half-typed for p1"],
      }),
    );
    await waitFor(() => expect(composerBox().textContent ?? "").toBe(""));

    fireEvent.click(screen.getByRole("button", { name: "go-p1" }));
    await waitFor(() =>
      expect(composerBox().textContent).toBe("Half-typed for p1"),
    );
  });

  it("does not restore an unsent draft that belongs to another Project", () => {
    useAgentDockUiStore.setState({
      unsentDrafts: { "p-other": ["Leaked from another Project"] },
    });
    renderDock();

    expect(composerBox().textContent ?? "").toBe("");
    expect(useAgentDockUiStore.getState().unsentDrafts).toEqual({
      "p-other": ["Leaked from another Project"],
    });
  });

  it("keeps one draft per Project across A → B → A → B round trips", async () => {
    renderDockWithSwitcher();
    fireEvent.input(composerBox(), { target: { textContent: "Draft A" } });

    fireEvent.click(screen.getByRole("button", { name: "go-p2" }));
    await waitFor(() => expect(composerBox().textContent ?? "").toBe(""));
    expect(useAgentDockUiStore.getState().unsentDrafts).toEqual({
      p1: ["Draft A"],
    });

    fireEvent.input(composerBox(), { target: { textContent: "Draft B" } });
    fireEvent.click(screen.getByRole("button", { name: "go-p1" }));
    await waitFor(() => expect(composerBox().textContent).toBe("Draft A"));
    // Restoring A consumed only A: B must still be parked for its own return.
    expect(useAgentDockUiStore.getState().unsentDrafts).toEqual({
      p2: ["Draft B"],
    });

    fireEvent.click(screen.getByRole("button", { name: "go-p2" }));
    await waitFor(() => expect(composerBox().textContent).toBe("Draft B"));
  });

  it("consumes a one-shot injection and prefers the edited draft on reopen", async () => {
    renderDock();
    act(() => useAgentDockUiStore.getState().setDraft("Original injection"));
    await waitFor(() =>
      expect(composerBox().textContent).toBe("Original injection"),
    );
    expect(useAgentDockUiStore.getState().draft).toBe("");

    fireEvent.input(composerBox(), {
      target: { textContent: "Edited instruction" },
    });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(useAgentDockUiStore.getState().unsentDrafts).toEqual({
      p1: ["Edited instruction"],
    });

    fireEvent.click(screen.getByRole("button", { name: "创作助手" }));
    await waitFor(() =>
      expect(composerBox().textContent).toBe("Edited instruction"),
    );
  });
});
