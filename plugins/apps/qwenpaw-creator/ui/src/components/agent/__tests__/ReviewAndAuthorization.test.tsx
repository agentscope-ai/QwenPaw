import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import DecisionTray from "@/components/agent/DecisionTray";
import { installMockFetch } from "@/test/mockFetch";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";

const pending = {
  id: "authorization-1",
  transactionId: "round-1",
  specialistRunId: "run-1",
  executionRequestId: "request-1",
  targetRef: "element:r2v-window",
  scope: { operation: "r2v_generation", message: "生成 Element 视频" },
  status: "PENDING" as const,
  authorizationToken: "token-1",
  provider: "dashscope",
  model: "wan2.7-r2v",
  estimatedCost: 2.5,
  currency: "CNY",
  maxCandidates: 2,
  createdAt: "now",
};

describe("file-native execution authorization decisions", () => {
  beforeEach(() => {
    useAgentDockUiStore.getState().reset();
    useExecutionAuthorizationStore.getState().reset();
    useExecutionAuthorizationStore.getState().bindProject("p1");
  });

  it("approves the exact project-level authorization request from the inline tray", async () => {
    useExecutionAuthorizationStore.setState({ items: [pending] });
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/execution-authorizations/authorization-1/approve",
        response: { json: { ...pending, status: "APPROVED" } },
      },
    ]);

    render(<DecisionTray projectId="p1" />);
    // Blocking level: tray is expanded and the summary bar says execution is
    // blocked until confirmed.
    const tray = document.querySelector("[data-decision-tray]");
    expect(tray).toHaveAttribute("data-decision-tray-urgent", "true");
    expect(
      screen.getByText("1 项待决策 · 需确认后才能继续"),
    ).toBeInTheDocument();
    expect(screen.getByText("生成 Element 视频")).toBeInTheDocument();
    fireEvent.click(screen.getByText("继续"));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].url).not.toContain("/transactions/");
    expect(calls[0].body).toEqual({
      authorizationToken: "token-1",
      provider: "dashscope",
      model: "wan2.7-r2v",
      maxCost: 2.5,
      maxCandidates: 2,
    });
  });

  it("declines with the exact token and removes the tray afterwards", async () => {
    useExecutionAuthorizationStore.setState({ items: [pending] });
    installMockFetch([
      {
        match: "/projects/p1/execution-authorizations/authorization-1/decline",
        response: { json: { ...pending, status: "DECLINED" } },
      },
    ]);

    render(<DecisionTray projectId="p1" />);
    fireEvent.click(screen.getByText("取消"));

    // Once everything is handled the tray disappears entirely and stops taking
    // up chat panel space.
    await waitFor(() =>
      expect(
        document.querySelector("[data-decision-tray]"),
      ).not.toBeInTheDocument(),
    );
  });

  it("keeps the amber summary line when collapsed with a blocking authorization", () => {
    useExecutionAuthorizationStore.setState({ items: [pending] });
    render(<DecisionTray projectId="p1" />);

    fireEvent.click(screen.getByRole("button", { name: "折叠决策托盘" }));
    const tray = document.querySelector("[data-decision-tray]");
    expect(tray).toHaveAttribute("data-decision-tray-collapsed", "true");
    expect(tray).toHaveAttribute("data-decision-tray-urgent", "true");
    // Collapsing hides the cards, but the summary bar keeps the blocking notice.
    expect(screen.queryByText("生成 Element 视频")).not.toBeInTheDocument();
    expect(screen.getByText(/生产确认 1 项阻塞执行中/)).toBeInTheDocument();
  });
});
