import type { ReactNode } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentStatsSummary } from "../../../api/types/agentStats";
import AgentStatsPage from "./index";

const mocks = vi.hoisted(() => ({
  getAgentStats: vi.fn(),
  messageError: vi.fn(),
  storeState: {
    selectedAgent: "agent-a",
    agents: [
      {
        id: "agent-a",
        name: "Agent A",
        description: "",
        workspace_dir: "/workspace/agent-a",
        enabled: true,
        backend: "qwenpaw",
      },
      {
        id: "agent-b",
        name: "Agent B",
        description: "",
        workspace_dir: "/workspace/agent-b",
        enabled: true,
        backend: "qwenpaw",
      },
    ],
  },
}));

vi.mock("../../../api", () => ({
  default: { getAgentStats: mocks.getAgentStats },
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: mocks.messageError } }),
}));

vi.mock("../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => mocks.storeState,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "nav.settings": "Settings",
        "agentStats.title": "Agent Statistics",
        "agentStats.totalSessions": "Total Sessions",
        "agentStats.totalMessages": "Total Messages",
        "agentStats.promptTokens": "Prompt Tokens",
        "agentStats.completionTokens": "Completion Tokens",
        "agentStats.currentAgentLlmCalls": "Recorded Turns",
        "agentStats.toolCalls": "Tool Calls",
      })[key] ?? key,
  }),
}));

vi.mock("@/components/PageHeader", () => ({
  PageHeader: () => null,
}));

vi.mock("@agentscope-ai/design", () => ({
  Button: ({ children }: { children?: ReactNode }) => (
    <button type="button">{children}</button>
  ),
  Card: ({ children, title }: { children?: ReactNode; title?: ReactNode }) => (
    <section>
      {title}
      {children}
    </section>
  ),
  Empty: () => <div>No data</div>,
}));

vi.mock("antd", () => ({
  DatePicker: { RangePicker: () => <div data-testid="date-range" /> },
  Spin: () => <div data-testid="spinner" />,
  Tooltip: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock("@ant-design/plots", () => ({
  Column: () => <div data-testid="column-chart" />,
  Pie: () => <div data-testid="pie-chart" />,
}));

function summary(
  agentPromptTokens: number,
  agentCompletionTokens: number,
  recordedTurns: number,
): AgentStatsSummary {
  return {
    total_active_sessions: 1,
    total_messages: 4,
    total_user_messages: 2,
    total_assistant_messages: 2,
    total_prompt_tokens: 900_000,
    total_completion_tokens: 90_000,
    total_llm_calls: 90,
    total_tool_calls: 0,
    agent_prompt_tokens: agentPromptTokens,
    agent_completion_tokens: agentCompletionTokens,
    agent_llm_calls: recordedTurns,
    agent_cache_read_tokens: 0,
    agent_cache_eligible_input_tokens: 0,
    agent_cache_hit_rate: null,
    by_date: [
      {
        date: "2026-08-13",
        chats: 1,
        active_sessions: 1,
        user_messages: 2,
        assistant_messages: 2,
        total_messages: 4,
        prompt_tokens: 900_000,
        completion_tokens: 90_000,
        llm_calls: 90,
        tool_calls: 0,
        agent_prompt_tokens: agentPromptTokens,
        agent_completion_tokens: agentCompletionTokens,
        agent_llm_calls: recordedTurns,
        agent_cache_read_tokens: 0,
      },
    ],
    channel_stats: [],
    start_date: "2026-08-06",
    end_date: "2026-08-13",
  };
}

function expectCard(label: string, value: string): void {
  const labelNode = screen.getByText(label);
  const card = labelNode.closest("section");
  expect(card).not.toBeNull();
  expect(within(card as HTMLElement).getByText(value)).toBeInTheDocument();
}

describe("TC-AGT-06: AgentStatsPage current-agent statistics", () => {
  beforeEach(() => {
    mocks.storeState.selectedAgent = "agent-a";
    mocks.getAgentStats.mockImplementation(() =>
      Promise.resolve(
        mocks.storeState.selectedAgent === "agent-a"
          ? summary(52_500, 343, 5)
          : summary(12_900, 72, 2),
      ),
    );
  });

  afterEach(() => vi.clearAllMocks());

  it("renders agent usage and refreshes it when the current agent changes", async () => {
    const view = render(<AgentStatsPage />);

    expect(await screen.findByText("Agent A")).toBeInTheDocument();
    expectCard("Prompt Tokens", "52.5K");
    expectCard("Completion Tokens", "343");
    expectCard("Recorded Turns", "5");
    expect(screen.queryByText("900K")).not.toBeInTheDocument();
    expect(screen.queryByText("All Agents")).not.toBeInTheDocument();

    mocks.storeState.selectedAgent = "agent-b";
    view.rerender(<AgentStatsPage />);

    await waitFor(() => expect(mocks.getAgentStats).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Agent B")).toBeInTheDocument();
    expectCard("Prompt Tokens", "12.9K");
    expectCard("Completion Tokens", "72");
    expectCard("Recorded Turns", "2");
    expect(screen.queryByText("52.5K")).not.toBeInTheDocument();
  });
});
