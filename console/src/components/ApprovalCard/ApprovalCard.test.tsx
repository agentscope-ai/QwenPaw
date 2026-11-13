import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import styles from "./ApprovalCard.module.less";
import { ApprovalCard, type ApprovalCardProps } from "./ApprovalCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback: string) => fallback,
  }),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

function renderApprovalCard() {
  const onApprove = vi
    .fn<ApprovalCardProps["onApprove"]>()
    .mockResolvedValue(undefined);
  renderCard({ onApprove });
  return onApprove;
}

function renderCard({
  isGeneralized = true,
  onApprove = async () => {},
}: {
  isGeneralized?: boolean;
  onApprove?: ApprovalCardProps["onApprove"];
} = {}) {
  renderWithProviders(
    <ApprovalCard
      requestId="approval-1"
      toolName="shell"
      toolSource="tool"
      severity="medium"
      findingsCount={0}
      findingsSummary=""
      toolParams={{}}
      createdAt={Date.now() / 1000}
      timeoutSeconds={60}
      agentId="default"
      isGeneralized={isGeneralized}
      exactTarget="pytest -q"
      similarTarget="pytest *"
      onApprove={onApprove}
      onDeny={vi.fn().mockResolvedValue(undefined)}
    />,
  );

  return onApprove;
}

describe("ApprovalCard generalized approval", () => {
  it("prioritizes one-time approval without changing approval scopes", async () => {
    const onApprove = renderApprovalCard();
    const user = userEvent.setup();
    const approveOnce = screen.getByRole("button", { name: "Just Once" });
    const approveAlways = screen.getByRole("button", {
      name: "Always Allow",
    });

    expect(approveOnce).toHaveClass(styles.approveOnceButton);
    expect(approveAlways).toHaveClass(styles.approveAlwaysButton);
    expect(approveOnce).toHaveClass("ant-btn-primary");
    expect(approveAlways).not.toHaveClass("ant-btn-primary");
    expect(
      approveOnce.compareDocumentPosition(approveAlways) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);

    await user.click(approveOnce);
    await waitFor(() => {
      expect(onApprove).toHaveBeenCalledWith("approval-1", "exact");
    });
    await waitFor(() => expect(approveAlways).not.toBeDisabled());

    await user.click(approveAlways);
    await waitFor(() => {
      expect(onApprove).toHaveBeenLastCalledWith("approval-1", "similar");
    });
  });

  it("keeps a single-scope approval visually primary", () => {
    renderCard({ isGeneralized: false });

    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toHaveClass(styles.approveOnceButton);
    expect(approve).toHaveClass("ant-btn-primary");
  });
});
