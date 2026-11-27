import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { ApiError } from "../../api/request";
import { commandsApi } from "../../api/modules/commands";
import en from "../../locales/en.json";
import zh from "../../locales/zh.json";
import styles from "./ApprovalCard.module.less";
import { ApprovalCard, type ApprovalCardProps } from "./ApprovalCard";

let language: "en" | "zh" = "en";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback: string, values?: Record<string, string>) => {
      const resource = language === "zh" ? zh : en;
      const template = String(
        key
          .split(".")
          .reduce<unknown>(
            (value, part) =>
              value && typeof value === "object"
                ? (value as Record<string, unknown>)[part]
                : undefined,
            resource,
          ) ?? fallback,
      );
      return template.replace(
        /\{\{(\w+)\}\}/g,
        (_, name: string) => values?.[name] ?? "",
      );
    },
  }),
}));

afterEach(() => {
  language = "en";
  vi.restoreAllMocks();
});

function renderCard(overrides: Partial<ApprovalCardProps> = {}) {
  const props: ApprovalCardProps = {
    requestId: "approval-1",
    toolName: "shell",
    toolSource: "tool",
    severity: "medium",
    findingsCount: 1,
    findingsSummary: "Review the command before allowing execution.",
    toolParams: { command: "pytest -q" },
    createdAt: Date.now() / 1000,
    timeoutSeconds: 60,
    agentId: "default",
    sessionId: "session-1",
    isGeneralized: true,
    approvalBehavior: "session_rule",
    exactTarget: "pytest -q",
    similarTarget: "pytest *",
    onApprove: vi.fn().mockResolvedValue(undefined),
    onDeny: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  renderWithProviders(<ApprovalCard {...props} />);
  return props;
}

describe("ApprovalCard decisions", () => {
  it.each(["exact", "similar"] as const)(
    "submits %s once and keeps approval separate from execution",
    async (scope) => {
      const props = renderCard();
      const user = userEvent.setup();
      const exact = screen.getByRole("button", {
        name: en.approval.allowTarget,
      });
      const pattern = screen.getByRole("button", {
        name: en.approval.allowPattern,
      });
      expect(exact).toHaveClass("ant-btn-primary", styles.approveOnceButton);
      expect(pattern).not.toHaveClass("ant-btn-primary");
      expect(
        pattern.compareDocumentPosition(exact) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).not.toBe(0);
      await user.click(scope === "exact" ? exact : pattern);
      await waitFor(() =>
        expect(props.onApprove).toHaveBeenCalledWith("approval-1", scope),
      );
      expect(screen.getByRole("status")).toHaveTextContent(
        en.approval.approved,
      );
      expect(
        screen.queryByRole("button", { name: en.approval.allowTarget }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText(/execution succeeded/i),
      ).not.toBeInTheDocument();
    },
  );

  it("locks all decisions synchronously during submission", async () => {
    let finish!: () => void;
    const onApprove = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const { onDeny } = renderCard({ onApprove });
    const button = screen.getByRole("button", {
      name: en.approval.allowTarget,
    });
    act(() => {
      fireEvent.click(button);
      fireEvent.click(button);
      fireEvent.click(screen.getByRole("button", { name: en.approval.deny }));
    });
    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onDeny).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      en.approval.submitting,
    );
    expect(
      screen
        .getAllByRole("button")
        .filter((b) => b.classList.contains("ant-btn"))
        .every((b) => b.hasAttribute("disabled")),
    ).toBe(true);
    await act(async () => finish());
  });

  it("rejects only the current call and uses a neutral button", async () => {
    const props = renderCard();
    const button = screen.getByRole("button", { name: en.approval.deny });
    expect(button).not.toHaveClass("ant-btn-dangerous");
    await userEvent.click(button);
    expect(props.onDeny).toHaveBeenCalledWith("approval-1");
    expect(props.onApprove).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(en.approval.denied);
  });

  it.each([404, 409])(
    "disables a request rejected with HTTP %s",
    async (status) => {
      renderCard({
        onApprove: vi
          .fn()
          .mockRejectedValue(new ApiError(status, "unavailable")),
      });
      await userEvent.click(
        screen.getByRole("button", { name: en.approval.allowTarget }),
      );
      expect(screen.getByRole("status")).toHaveTextContent(
        en.approval.unavailable,
      );
      expect(
        screen.queryByRole("button", { name: en.approval.deny }),
      ).not.toBeInTheDocument();
    },
  );

  it.each([new Error("Network failure"), new ApiError(500, "Server error")])(
    "keeps context without claiming success or offering an unverified retry",
    async (error) => {
      renderCard({ onDeny: vi.fn().mockRejectedValue(error) });
      await userEvent.click(
        screen.getByRole("button", { name: en.approval.deny }),
      );
      expect(screen.getByRole("status")).toHaveTextContent(
        en.approval.submitUnconfirmed,
      );
      expect(
        screen.getByText("Review the command before allowing execution."),
      ).toBeVisible();
      expect(
        screen.queryByRole("button", { name: en.approval.allowTarget }),
      ).not.toBeInTheDocument();
    },
  );

  it("unlocks decisions only after a successful check for this request", async () => {
    const check = vi
      .spyOn(commandsApi, "isApprovalPending")
      .mockRejectedValueOnce(new Error("Offline"))
      .mockResolvedValueOnce(true);
    const deny = vi.fn().mockRejectedValue(new Error("Network failure"));
    renderCard({ onDeny: deny, rootSessionId: "root-session" });
    await userEvent.click(
      screen.getByRole("button", { name: en.approval.deny }),
    );
    const recheck = screen.getByRole("button", {
      name: en.approval.checkStatus,
    });
    await userEvent.click(recheck);
    expect(screen.getByRole("status")).toHaveTextContent(
      en.approval.checkStatusFailed,
    );
    expect(screen.queryByRole("button", { name: en.approval.deny })).toBeNull();
    await userEvent.click(recheck);
    expect(
      screen.getByRole("button", { name: en.approval.deny }),
    ).toBeEnabled();
    expect(check).toHaveBeenLastCalledWith("approval-1", "root-session");
    expect(deny).toHaveBeenCalledOnce();
  });

  it("keeps an approval locked when the server no longer lists it", async () => {
    vi.spyOn(commandsApi, "isApprovalPending").mockResolvedValue(false);
    renderCard({
      onDeny: vi.fn().mockRejectedValue(new ApiError(500, "Offline")),
    });
    await userEvent.click(
      screen.getByRole("button", { name: en.approval.deny }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: en.approval.checkStatus }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      en.approval.unavailable,
    );
    expect(
      screen.queryByRole("button", { name: en.approval.allowTarget }),
    ).toBeNull();
  });

  it.each([
    [
      403,
      'Root session mismatch - {"detail":"Root session mismatch"}',
      "Root session mismatch",
    ],
    [400, "Request failed: 400 Bad Request", "HTTP 400"],
  ])(
    "shows the server reason for an explicit HTTP %s rejection",
    async (status, message, reason) => {
      renderCard({
        onApprove: vi.fn().mockRejectedValue(new ApiError(status, message)),
      });
      await userEvent.click(
        screen.getByRole("button", { name: en.approval.allowTarget }),
      );
      expect(screen.getByRole("status")).toHaveTextContent(
        en.approval.submitRejected.replace("{{reason}}", reason),
      );
      expect(
        screen.getByText("Review the command before allowing execution."),
      ).toBeVisible();
      expect(
        screen.queryByRole("button", { name: en.approval.deny }),
      ).not.toBeInTheDocument();
    },
  );

  it.each([false, true])(
    "disables expired requests in chat/inbox (%s)",
    (showInboxAgentContext) => {
      renderCard({ createdAt: Date.now() / 1000 - 61, showInboxAgentContext });
      expect(screen.getByRole("status")).toHaveTextContent(en.approval.expired);
      expect(
        screen.queryByRole("button", { name: en.approval.allowTarget }),
      ).not.toBeInTheDocument();
    },
  );

  it("checks the deadline again inside the click handler", () => {
    const props = renderCard();
    vi.spyOn(Date, "now").mockReturnValue((props.createdAt + 61) * 1000);
    fireEvent.click(
      screen.getByRole("button", { name: en.approval.allowTarget }),
    );
    expect(props.onApprove).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(en.approval.expired);
  });

  it("dismisses an expired notice without submitting a decision", async () => {
    const onAcknowledge = vi.fn().mockResolvedValue(undefined);
    const props = renderCard({
      createdAt: Date.now() / 1000 - 61,
      onAcknowledge,
    });
    await userEvent.click(
      screen.getByRole("button", { name: en.approval.dismiss }),
    );
    expect(onAcknowledge).toHaveBeenCalledWith("approval-1");
    expect(props.onApprove).not.toHaveBeenCalled();
    expect(props.onDeny).not.toHaveBeenCalled();
  });

  it.each([
    ["once", en.approval.allowOnce, en.approval.onceHint],
    ["strict", en.approval.approve, en.approval.strictHint],
    ["session_app", en.approval.allowApp, en.approval.sessionAppHint],
    ["unknown", en.approval.approve, en.approval.unknownHint],
  ] as const)(
    "uses verified semantics for %s even when the target is generalized",
    (approvalBehavior, label, hint) => {
      renderCard({ approvalBehavior });
      expect(screen.getByRole("button", { name: label })).toHaveClass(
        "ant-btn-primary",
      );
      expect(screen.getByText(hint)).toBeVisible();
      expect(
        screen.queryByRole("button", { name: en.approval.allowPattern }),
      ).not.toBeInTheDocument();
    },
  );

  it("shows the target for non-generalized calls", () => {
    renderCard({ isGeneralized: false });
    expect(screen.getByText("pytest -q")).toBeVisible();
    expect(
      screen.getByRole("button", { name: en.approval.allowTarget }),
    ).toBeEnabled();
  });

  it.each(["en", "zh"] as const)(
    "shows application identity and risk outside collapsed parameters in %s",
    (selectedLanguage) => {
      language = selectedLanguage;
      const resource = selectedLanguage === "zh" ? zh : en;
      const appId = String.raw`process:C:\Applications\Editor.exe`;
      renderCard({
        approvalBehavior: "session_app",
        showInboxAgentContext: true,
        isGeneralized: false,
        exactTarget: "Editor for this session",
        toolParams: {
          canonical_app_id: appId,
          risk: "high",
          warning: "Application identity needs verification.",
        },
      });
      for (const value of [
        appId,
        "high",
        "Application identity needs verification.",
      ]) {
        const detail = screen.getByText(value, { exact: true });
        expect(detail).toBeVisible();
        expect(detail.closest("details")).toBeNull();
      }
      expect(
        screen.getByText(`${resource.approval.applicationId}:`),
      ).toBeVisible();
      expect(
        document.querySelector(`.${styles.paramsDetails}`),
      ).not.toHaveAttribute("open");
    },
  );

  it("preserves Chinese scope wording and keyboard order", async () => {
    language = "zh";
    renderCard();
    const user = userEvent.setup();
    const reject = screen.getByRole("button", { name: zh.approval.deny });
    reject.focus();
    await user.tab();
    expect(
      screen.getByRole("button", { name: zh.approval.allowPattern }),
    ).toHaveFocus();
    await user.tab();
    expect(
      screen.getByRole("button", { name: zh.approval.allowTarget }),
    ).toHaveFocus();
    expect(screen.getByText(zh.approval.sessionRuleHint)).toBeVisible();
  });
});
