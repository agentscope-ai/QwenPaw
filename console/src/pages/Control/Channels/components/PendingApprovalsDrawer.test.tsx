// @vitest-environment jsdom
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "antd";

const mocks = vi.hoisted(() => ({
  approve: vi.fn(),
  deny: vi.fn(),
  dismiss: vi.fn(),
  getPending: vi.fn(),
  updatePendingRemark: vi.fn(),
  updateUsername: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: vi.fn(), success: vi.fn() },
  }),
}));

vi.mock("../../../../api/modules/accessControl", () => ({
  accessControlApi: {
    approveAclPending: (...args: unknown[]) => mocks.approve(...args),
    denyAclPending: (...args: unknown[]) => mocks.deny(...args),
    dismissAclPending: (...args: unknown[]) => mocks.dismiss(...args),
    getAclAllPending: (...args: unknown[]) => mocks.getPending(...args),
    updatePendingRemark: (...args: unknown[]) =>
      mocks.updatePendingRemark(...args),
    updateUsername: (...args: unknown[]) => mocks.updateUsername(...args),
  },
}));

vi.mock("@/components/interaction/SettingsDrawer", () => ({
  SettingsDrawer: ({
    children,
    open,
  }: {
    children: React.ReactNode;
    open: boolean;
  }) =>
    open ? <section data-testid="pending-drawer">{children}</section> : null,
}));

import { PendingApprovalsDrawer } from "./PendingApprovalsDrawer";

describe("PendingApprovalsDrawer owner guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getPending.mockResolvedValue([
      {
        channel: "dingtalk",
        user_id: "user-a",
        username: "Alice",
        remark: "",
        first_message: "hello",
        timestamp: 1,
      },
    ]);
  });

  it("rejects captured approve, deny, and dismiss callbacks after agent switch", async () => {
    let currentAgent = "agent-a";
    const onStale = vi.fn();
    render(
      <App>
        <PendingApprovalsDrawer
          open
          ownerAgentId="agent-a"
          canMutate={(ownerAgentId) => ownerAgentId === currentAgent}
          onStale={onStale}
          onClose={vi.fn()}
        />
      </App>,
    );
    await waitFor(() => expect(mocks.getPending).toHaveBeenCalledOnce());
    await screen.findByText("Alice");

    currentAgent = "agent-b";
    fireEvent.click(screen.getByRole("button", { name: "channels.approve" }));
    fireEvent.click(screen.getByRole("button", { name: "channels.deny" }));
    fireEvent.click(screen.getByRole("button", { name: "channels.dismiss" }));

    expect(mocks.approve).not.toHaveBeenCalled();
    expect(mocks.deny).not.toHaveBeenCalled();
    expect(mocks.dismiss).not.toHaveBeenCalled();
    expect(onStale).toHaveBeenCalledTimes(3);
  });

  it("does not let agent A completion clear agent B action loading", async () => {
    let resolveAgentA!: () => void;
    let resolveAgentB!: () => void;
    const agentAAction = new Promise<void>((resolve) => {
      resolveAgentA = resolve;
    });
    const agentBAction = new Promise<void>((resolve) => {
      resolveAgentB = resolve;
    });
    mocks.approve
      .mockReturnValueOnce(agentAAction)
      .mockReturnValueOnce(agentBAction);

    let currentAgent = "agent-a";
    const drawer = (ownerAgentId: string) => (
      <App>
        <PendingApprovalsDrawer
          open
          ownerAgentId={ownerAgentId}
          canMutate={(owner) => owner === currentAgent}
          onStale={vi.fn()}
          onClose={vi.fn()}
        />
      </App>
    );
    const view = render(drawer("agent-a"));
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "channels.approve" }));
    expect(mocks.approve).toHaveBeenCalledTimes(1);

    currentAgent = "agent-b";
    view.rerender(drawer("agent-b"));
    await screen.findByText("Alice");
    const agentBApprove = screen.getByRole("button", {
      name: "channels.approve",
    });
    fireEvent.click(agentBApprove);
    expect(mocks.approve).toHaveBeenCalledTimes(2);
    expect(agentBApprove).toHaveClass("ant-btn-loading");
    fireEvent.click(agentBApprove);
    expect(mocks.approve).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolveAgentA();
      await agentAAction;
    });
    expect(agentBApprove).toHaveClass("ant-btn-loading");

    await act(async () => {
      resolveAgentB();
      await agentBAction;
    });
    await waitFor(() =>
      expect(agentBApprove).not.toHaveClass("ant-btn-loading"),
    );
  });

  it("keeps each row loading until that row's action settles", async () => {
    mocks.getPending.mockResolvedValue([
      {
        channel: "dingtalk",
        user_id: "user-a",
        username: "Alice",
        remark: "",
        first_message: "hello",
        timestamp: 1,
      },
      {
        channel: "dingtalk",
        user_id: "user-b",
        username: "Bob",
        remark: "",
        first_message: "hello",
        timestamp: 2,
      },
    ]);
    let resolveAlice!: () => void;
    let resolveBob!: () => void;
    const aliceAction = new Promise<void>((resolve) => {
      resolveAlice = resolve;
    });
    const bobAction = new Promise<void>((resolve) => {
      resolveBob = resolve;
    });
    mocks.approve
      .mockReturnValueOnce(aliceAction)
      .mockReturnValueOnce(bobAction);

    render(
      <App>
        <PendingApprovalsDrawer
          open
          ownerAgentId="agent-a"
          canMutate={(owner) => owner === "agent-a"}
          onStale={vi.fn()}
          onClose={vi.fn()}
        />
      </App>,
    );
    await screen.findByText("Bob");
    const approveButtons = screen.getAllByRole("button", {
      name: "channels.approve",
    });
    fireEvent.click(approveButtons[0]);
    fireEvent.click(approveButtons[1]);

    expect(mocks.approve).toHaveBeenCalledTimes(2);
    expect(approveButtons[0]).toHaveClass("ant-btn-loading");
    expect(approveButtons[1]).toHaveClass("ant-btn-loading");

    await act(async () => {
      resolveAlice();
      await aliceAction;
    });
    await waitFor(() =>
      expect(approveButtons[0]).not.toHaveClass("ant-btn-loading"),
    );
    expect(approveButtons[1]).toHaveClass("ant-btn-loading");

    await act(async () => {
      resolveBob();
      await bobAction;
    });
    await waitFor(() =>
      expect(approveButtons[1]).not.toHaveClass("ant-btn-loading"),
    );
  });
});
