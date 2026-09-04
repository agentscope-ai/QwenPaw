/**
 * RestoreBackupModal — final step of the backup restore flow. Covers detail
 * loading (success/failure gating of the OK button), the trust banner
 * variants, full vs custom restore modes, strategy defaults derived from the
 * trust state, the custom scope checkboxes and agent table, the workspace
 * dir input for new agents, request building for both modes, success
 * messages (including preserved local keys) and the error matrix: trust
 * prompts (legacy/foreign), target-busy with locked paths, restore timeout,
 * plain-reason and fallback failures.
 *
 * The agent table and trust dialog are stubbed: their props are captured and
 * buttons are exposed so selection changes and the trust confirmation can be
 * driven deterministically.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

const apiMocks = vi.hoisted(() => ({
  getBackup: vi.fn(),
  restoreBackup: vi.fn(),
}));

vi.mock("@/api", () => ({ default: apiMocks }));

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: messageMocks }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
  }),
}));

const tableProps = vi.hoisted(() => ({ current: null as any }));
const trustProps = vi.hoisted(() => ({ current: null as any }));

vi.mock("./RestoreAgentTable", () => ({
  default: (props: any) => {
    tableProps.current = props;
    return React.createElement(
      "div",
      { "data-testid": "agent-table" },
      React.createElement(
        "button",
        { onClick: () => props.onSelectionChange(["agent-a"]) },
        "select-only-a",
      ),
      React.createElement(
        "button",
        { onClick: () => props.onIncludeAgentsChange(false) },
        "exclude-agents",
      ),
      props.summaryText ?? "",
    );
  },
}));

vi.mock("../trust/BackupTrustDialog", () => ({
  default: (props: any) => {
    trustProps.current = props;
    if (!props.open) return null;
    return React.createElement(
      "div",
      { "data-testid": "trust-dialog", "data-mode": props.mode },
      React.createElement(
        "button",
        { onClick: props.onConfirm },
        "trust-confirm",
      ),
      React.createElement(
        "button",
        { onClick: props.onCancel },
        "trust-cancel",
      ),
    );
  },
}));

import RestoreBackupModal from "./RestoreBackupModal";

function makeBackup(overrides: Record<string, unknown> = {}) {
  return {
    id: "bk-1",
    name: "Nightly backup",
    description: "before release",
    created_at: "2026-09-01T00:00:00Z",
    scope: {
      include_agents: true,
      include_global_config: true,
      include_secrets: true,
      include_skill_pool: true,
    },
    agent_count: 2,
    ...overrides,
  };
}

function makeDetail(overrides: Record<string, unknown> = {}) {
  return {
    ...makeBackup(),
    workspace_stats: {
      "agent-a": { files: 10, size: 100, name: "Agent A" },
      "agent-b": { files: 5, size: 50, name: "Agent B" },
    },
    ...overrides,
  };
}

/** agent-b is intentionally absent so it counts as a new agent. */
const existingAgents = [
  { id: "agent-a", name: "Agent A", workspace_dir: "/w/a" },
];

function renderModal(
  backup = makeBackup(),
  agents = existingAgents as never[],
) {
  const onClose = vi.fn();
  const onSuccess = vi.fn();
  const rendered = render(
    <RestoreBackupModal
      open
      backup={backup as never}
      agents={agents}
      onClose={onClose}
      onSuccess={onSuccess}
    />,
  );
  return { onClose, onSuccess, unmount: rendered.unmount };
}

async function confirmAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText("backup.restoreConfirm"));
  await user.click(screen.getByText("common.confirm"));
}

describe("RestoreBackupModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tableProps.current = null;
    trustProps.current = null;
    apiMocks.getBackup.mockResolvedValue(makeDetail());
    apiMocks.restoreBackup.mockResolvedValue({});
  });

  it("shows backup name, description and fetches the detail on open", async () => {
    renderModal();
    expect(screen.getByText("Nightly backup")).toBeInTheDocument();
    expect(screen.getByText("before release")).toBeInTheDocument();
    await waitFor(() =>
      expect(apiMocks.getBackup).toHaveBeenCalledWith("bk-1"),
    );
  });

  it("disables OK until the confirm checkbox is checked", async () => {
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    const ok = screen.getByText("common.confirm").closest("button");
    expect(ok).toBeDisabled();
    await user.click(screen.getByText("backup.restoreConfirm"));
    expect(ok).toBeEnabled();
  });

  it("shows an error alert and keeps OK disabled when the detail fails", async () => {
    const user = userEvent.setup();
    apiMocks.getBackup.mockRejectedValue(new Error("gone"));
    renderModal();
    await waitFor(() =>
      expect(screen.getByText("backup.detailLoadFailed")).toBeInTheDocument(),
    );
    expect(messageMocks.error).toHaveBeenCalledWith("backup.detailLoadFailed");
    await user.click(screen.getByText("backup.restoreConfirm"));
    expect(screen.getByText("common.confirm").closest("button")).toBeDisabled();
  });

  it.each([
    [false, /backup\.trustLocalBanner/],
    [true, /backup\.trustForeignBanner/],
    [null, /backup\.trustLegacyBanner/],
  ])(
    "shows the right trust banner for accepted_via_trust=%s",
    async (accepted, pattern) => {
      renderModal(makeBackup({ accepted_via_trust: accepted }));
      await waitFor(() =>
        expect(screen.getByText(pattern)).toBeInTheDocument(),
      );
    },
  );

  it("defaults to full mode with the warning alert for full backups", async () => {
    renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await waitFor(() => {
      const fullWrapper = document
        .querySelector('input[value="full"]')!
        .closest(".ant-radio-wrapper");
      expect(fullWrapper).toHaveClass("ant-radio-wrapper-checked");
    });
    expect(screen.getByText("backup.restoreFullWarning")).toBeInTheDocument();
  });

  it("defaults to custom mode and disables full for partial backups", async () => {
    renderModal(
      makeBackup({
        scope: {
          include_agents: true,
          include_global_config: true,
          include_secrets: false,
          include_skill_pool: false,
        },
      }),
    );
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await waitFor(() => {
      const customWrapper = document
        .querySelector('input[value="custom"]')!
        .closest(".ant-radio-wrapper");
      expect(customWrapper).toHaveClass("ant-radio-wrapper-checked");
    });
    expect(document.querySelector('input[value="full"]')).toBeDisabled();
    expect(
      screen.getByText("backup.restoreModeFullDisabled"),
    ).toBeInTheDocument();
    // Scope rows follow the backup scope: global config yes, secrets/skills no.
    expect(screen.getByText("backup.scopeGlobalConfig")).toBeInTheDocument();
    expect(screen.queryByText("backup.scopeSecrets")).not.toBeInTheDocument();
    expect(screen.queryByText("backup.scopeSkillPool")).not.toBeInTheDocument();
  });

  it("defaults the strategy to restore for trust-accepted foreign backups", async () => {
    renderModal(makeBackup({ accepted_via_trust: false }));
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    expect(document.querySelector('input[value="restore"]')).toBeChecked();
  });

  it("shows the workspace dir input only when new agents exist", async () => {
    const first = renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    expect(
      screen.getByPlaceholderText("backup.defaultWorkspaceDirPlaceholder"),
    ).toBeInTheDocument();
    first.unmount();

    // When every backup agent already exists locally the input disappears.
    renderModal(makeBackup(), [
      { id: "agent-a", name: "Agent A", workspace_dir: "/w/a" },
      { id: "agent-b", name: "Agent B", workspace_dir: "/w/b" },
    ] as never[]);
    await waitFor(() =>
      expect(
        screen.queryByPlaceholderText("backup.defaultWorkspaceDirPlaceholder"),
      ).not.toBeInTheDocument(),
    );
  });

  it("builds a full-mode request with every agent and scope flag", async () => {
    const user = userEvent.setup();
    const { onClose, onSuccess } = renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await confirmAndSubmit(user);
    await waitFor(() =>
      expect(apiMocks.restoreBackup).toHaveBeenCalledWith("bk-1", {
        mode: "full",
        include_agents: true,
        agent_ids: ["agent-a", "agent-b"],
        include_global_config: true,
        include_secrets: true,
        include_skill_pool: true,
        default_workspace_dir: null,
        preserve_local_protected_config: true,
      }),
    );
    expect(messageMocks.success).toHaveBeenCalledWith("backup.restoreSuccess");
    expect(onSuccess).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("builds a custom-mode request from selections and workspace dir", async () => {
    const user = userEvent.setup();
    renderModal(
      makeBackup({
        accepted_via_trust: false,
        scope: {
          include_agents: true,
          include_global_config: true,
          include_secrets: false,
          include_skill_pool: false,
        },
      }),
    );
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());

    await user.type(
      screen.getByPlaceholderText("backup.defaultWorkspaceDirPlaceholder"),
      "/custom/dir ",
    );
    await user.click(screen.getByText("select-only-a"));
    // Uncheck the global config scope row.
    await user.click(screen.getByText("backup.scopeGlobalConfig"));
    await confirmAndSubmit(user);

    await waitFor(() =>
      expect(apiMocks.restoreBackup).toHaveBeenCalledWith("bk-1", {
        mode: "custom",
        include_agents: true,
        agent_ids: ["agent-a"],
        include_global_config: false,
        include_secrets: false,
        include_skill_pool: false,
        default_workspace_dir: "/custom/dir",
        // accepted_via_trust === false defaults the strategy to restore.
        preserve_local_protected_config: false,
      }),
    );
  });

  it("sends empty agent ids when the agents scope row is excluded", async () => {
    const user = userEvent.setup();
    renderModal(
      makeBackup({
        scope: {
          include_agents: true,
          include_global_config: false,
          include_secrets: false,
          include_skill_pool: false,
        },
      }),
    );
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await user.click(screen.getByText("exclude-agents"));
    await confirmAndSubmit(user);
    await waitFor(() =>
      expect(apiMocks.restoreBackup).toHaveBeenCalledWith(
        "bk-1",
        expect.objectContaining({
          mode: "custom",
          include_agents: false,
          agent_ids: [],
        }),
      ),
    );
  });

  it("reports preserved local keys in the success message", async () => {
    apiMocks.restoreBackup.mockResolvedValue({
      preserved_local_keys: ["security", "mcp"],
    });
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await confirmAndSubmit(user);
    await waitFor(() =>
      expect(messageMocks.success).toHaveBeenCalledWith(
        expect.stringContaining("backup.restoreSuccessPreserved"),
      ),
    );
  });

  it("opens the legacy trust prompt and retries with trust_mode on confirm", async () => {
    apiMocks.restoreBackup
      .mockRejectedValueOnce(
        new Error('denied - {"code":"backup_legacy_unsigned"}'),
      )
      .mockResolvedValueOnce({});
    const user = userEvent.setup();
    const { onClose } = renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await confirmAndSubmit(user);

    await waitFor(() => expect(trustProps.current?.open).toBe(true));
    expect(screen.getByTestId("trust-dialog")).toHaveAttribute(
      "data-mode",
      "legacy",
    );

    await user.click(screen.getByText("trust-confirm"));
    await waitFor(() =>
      expect(apiMocks.restoreBackup).toHaveBeenCalledWith(
        "bk-1",
        expect.objectContaining({
          trust_mode: "legacy",
        }),
      ),
    );
    expect(messageMocks.success).toHaveBeenCalledWith("backup.restoreSuccess");
    expect(onClose).toHaveBeenCalled();
  });

  it("opens the foreign trust prompt for signature mismatches and cancels", async () => {
    apiMocks.restoreBackup.mockRejectedValue(
      new Error('denied - {"code":"backup_signature_mismatch"}'),
    );
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await confirmAndSubmit(user);
    await waitFor(() =>
      expect(screen.getByTestId("trust-dialog")).toHaveAttribute(
        "data-mode",
        "foreign",
      ),
    );

    await user.click(screen.getByText("trust-cancel"));
    await waitFor(() => expect(trustProps.current?.open).toBe(false));
    expect(apiMocks.restoreBackup).toHaveBeenCalledTimes(1);
  });

  it("surfaces failures from the trust retry without reopening the dialog", async () => {
    apiMocks.restoreBackup
      .mockRejectedValueOnce(
        new Error('denied - {"code":"backup_legacy_unsigned"}'),
      )
      .mockRejectedValueOnce(new Error('boom - {"message":"disk full"}'));
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await confirmAndSubmit(user);
    await waitFor(() => expect(trustProps.current?.open).toBe(true));

    await user.click(screen.getByText("trust-confirm"));
    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith(
        expect.objectContaining({
          content: "backup.restoreFailed: disk full",
          duration: 8,
        }),
      ),
    );
    // The dialog stays open after a failed retry so the user can try again.
    expect(trustProps.current?.open).toBe(true);
  });

  it("lists locked paths when the restore target is busy", async () => {
    apiMocks.restoreBackup.mockRejectedValue(
      new Error(
        'conflict - {"code":"restore_target_busy","locked_paths":["/data/a",123,""]}',
      ),
    );
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await confirmAndSubmit(user);
    await waitFor(() => expect(messageMocks.error).toHaveBeenCalled());

    const arg =
      messageMocks.error.mock.calls[
        messageMocks.error.mock.calls.length - 1
      ][0];
    expect(arg).toMatchObject({ duration: 8 });
    const { container } = render(arg.content as React.ReactElement);
    expect(container.textContent).toContain("backup.restoreTargetBusy");
    expect(container.textContent).toContain("/data/a");
    expect(container.textContent).not.toContain("123");
  });

  it("flags restore timeouts with the dedicated message", async () => {
    apiMocks.restoreBackup.mockRejectedValue(
      new Error("Request timeout after 60000ms POST /backups/bk-1/restore"),
    );
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await confirmAndSubmit(user);
    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith(
        expect.objectContaining({
          content: "backup.restoreTimedOut",
          duration: 8,
        }),
      ),
    );
  });

  it("uses the parsed string detail as the failure reason", async () => {
    apiMocks.restoreBackup.mockRejectedValue(new Error('bad - "boom"'));
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await confirmAndSubmit(user);
    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith(
        expect.objectContaining({
          content: "backup.restoreFailed: boom",
          duration: 8,
        }),
      ),
    );
  });

  it("falls back to the generic failure message without detail", async () => {
    apiMocks.restoreBackup.mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(apiMocks.getBackup).toHaveBeenCalled());
    await confirmAndSubmit(user);
    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith("backup.restoreFailed"),
    );
  });
});
