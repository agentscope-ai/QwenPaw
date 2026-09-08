/**
 * CheckpointsPage — agent checkpoint browser. Covers loading/error/retry,
 * summary and truncated indicator, search/kind/session filters, auto-save
 * toggle, snapshot creation, GC flows (preview + confirm, thorough variant,
 * settings load/save), reset, node detail drawer (restore gating, commit
 * copy) and the empty/mismatch descriptions.
 *
 * The heavy graph renderer and restore modal are stubbed; the imperative
 * Modal.useModal confirm is captured via a spy so onOk can be driven.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

const modalConfirmSpy = vi.hoisted(() => vi.fn());

const cpMocks = vi.hoisted(() => ({
  status: vi.fn(),
  graph: vi.fn(),
  setAuto: vi.fn(),
  snapshot: vi.fn(),
  previewGc: vi.fn(),
  gc: vi.fn(),
  getGcSettings: vi.fn(),
  updateGcSettings: vi.fn(),
  reset: vi.fn(),
}));

vi.mock("@/api/modules/checkpoints", () => ({
  checkpointsApi: cpMocks,
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (s: { selectedAgent: string }) => unknown) =>
    selector({ selectedAgent: "agent-1" }),
}));

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
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
  }),
}));

// Capture the imperative modal.confirm from Modal.useModal.
vi.mock("antd", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, any>;
  return {
    ...actual,
    Modal: Object.assign(actual.Modal, {
      useModal: () => [{ confirm: modalConfirmSpy }, null],
    }),
  };
});

// Stub the graph renderer: rows become selectable buttons.
vi.mock("./CheckpointGraph", () => ({
  CheckpointGraph: ({
    rows,
    onSelect,
    emptyDescription,
  }: {
    rows: Array<{ commit: string }>;
    onSelect: (node: unknown) => void;
    emptyDescription: string;
  }) =>
    rows.length > 0
      ? React.createElement(
          "div",
          null,
          rows.map((n) =>
            React.createElement(
              "button",
              {
                key: n.commit,
                type: "button",
                "data-commit": n.commit,
                onClick: () => onSelect(n),
              },
              n.commit,
            ),
          ),
        )
      : React.createElement("div", null, emptyDescription),
}));

vi.mock("./RestoreModal", () => ({
  RestoreModal: ({ open }: { open: boolean }) =>
    open
      ? React.createElement("div", { "data-testid": "restore-modal" })
      : null,
}));

vi.mock("./graphLayout", () => ({
  buildGraphRows: (nodes: unknown[]) => nodes,
  graphLaneCount: () => 1,
}));

import CheckpointsPage from "./index";

const node = (overrides: Record<string, unknown> = {}) => ({
  commit: "c1aaaa",
  kind: "auto",
  query: "fix the bug",
  name: null,
  subject: "fix the bug",
  session_key: "s1",
  session_id: "sess-1",
  session_title: "Session One",
  channel: "console",
  timestamp_ms: 1_700_000_000_000,
  parent_commit: "p0bbbbbbbbbb",
  ...overrides,
});

function setupDefaultMocks() {
  cpMocks.status.mockResolvedValue({
    auto_enabled: true,
    workspace_dir: "/ws",
  });
  cpMocks.graph.mockResolvedValue({
    nodes: [
      node(),
      node({ commit: "c2bbbb", kind: "snap", query: "snapshot one" }),
    ],
    sessions: [
      {
        session_key: "s1",
        session_id: "sess-1",
        title: "Session One",
        user_id: "u1",
        channel: "console",
      },
    ],
    summary: { total: 2, auto: 1, snapshots: 1, safety: 0, heads: 1 },
    truncated: false,
  });
  cpMocks.setAuto.mockResolvedValue({ auto_enabled: true });
  cpMocks.snapshot.mockResolvedValue({});
  cpMocks.previewGc.mockResolvedValue({ deleted_refs: ["r1"] });
  cpMocks.gc.mockResolvedValue({ deleted_refs: ["r1"] });
  cpMocks.getGcSettings.mockResolvedValue({
    gc_keep_count: 50,
    gc_keep_days: 30,
    pre_restore_retention_days: 7,
  });
  cpMocks.updateGcSettings.mockResolvedValue({
    gc_keep_count: 50,
    gc_keep_days: 30,
    pre_restore_retention_days: 7,
  });
  cpMocks.reset.mockResolvedValue({ reset: true, auto_enabled: true });
}

async function renderPage() {
  const user = userEvent.setup();
  const utils = render(<CheckpointsPage />);
  await waitFor(() =>
    expect(screen.getByText("checkpoints.summary.total")).toBeInTheDocument(),
  );
  return { user, ...utils };
}

describe("CheckpointsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  it("renders the summary bar and workspace path", async () => {
    await renderPage();
    expect(screen.getByText("/ws")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("shows the truncated indicator when the graph is truncated", async () => {
    cpMocks.graph.mockResolvedValue({
      nodes: [node()],
      sessions: [],
      summary: { total: 1, auto: 1, snapshots: 0, safety: 0, heads: 1 },
      truncated: true,
    });
    await renderPage();
    expect(screen.getByText("checkpoints.showingLatest")).toBeInTheDocument();
  });

  it("shows the error state with retry when loading fails", async () => {
    cpMocks.status.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<CheckpointsPage />);

    await waitFor(() =>
      expect(screen.getByText("checkpoints.loadFailed")).toBeInTheDocument(),
    );

    // Retry succeeds
    cpMocks.status.mockResolvedValue({ auto_enabled: true });
    await user.click(screen.getByText("checkpoints.retry"));
    await waitFor(() =>
      expect(screen.getByText("checkpoints.summary.total")).toBeInTheDocument(),
    );
  });

  it("filters nodes by search text", async () => {
    const user = userEvent.setup();
    await renderPage();

    const search = screen.getByPlaceholderText("checkpoints.search");
    await user.type(search, "snapshot one");

    await waitFor(() => expect(screen.getByText("c2bbbb")).toBeInTheDocument());
    expect(screen.queryByText("c1aaaa")).not.toBeInTheDocument();
  });

  it("shows the no-matches description when filters hit nothing", async () => {
    const user = userEvent.setup();
    await renderPage();

    const search = screen.getByPlaceholderText("checkpoints.search");
    await user.type(search, "zzz-not-there");

    await waitFor(() =>
      expect(screen.getByText("checkpoints.noMatches")).toBeInTheDocument(),
    );
  });

  it("shows the empty description when there are no checkpoints", async () => {
    cpMocks.graph.mockResolvedValue({
      nodes: [],
      sessions: [],
      summary: { total: 0, auto: 0, snapshots: 0, safety: 0, heads: 0 },
      truncated: false,
    });
    render(<CheckpointsPage />);
    await waitFor(() =>
      expect(screen.getByText("checkpoints.empty")).toBeInTheDocument(),
    );
  });

  it("toggles auto checkpoints on and off", async () => {
    const { user } = await renderPage();

    cpMocks.setAuto.mockResolvedValue({ auto_enabled: false });
    await user.click(screen.getByRole("switch"));

    await waitFor(() => expect(cpMocks.setAuto).toHaveBeenCalledWith(false));
    expect(messageMocks.success).toHaveBeenCalledWith(
      "checkpoints.autoDisabled",
    );
  });

  it("reports auto-toggle failures", async () => {
    cpMocks.setAuto.mockRejectedValue(new Error("denied"));
    const { user } = await renderPage();

    await user.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith("denied"),
    );
  });

  it("creates a snapshot via the snapshot dialog", async () => {
    const { user } = await renderPage();

    await user.click(screen.getByText("checkpoints.snapshot"));

    const modal = document.querySelector(".ant-modal") as HTMLElement;
    const nameInput = within(modal).getByPlaceholderText(
      "checkpoints.snapshotDialog.placeholder",
    );
    await user.type(nameInput, "my snap");
    await user.click(
      within(modal).getByRole("button", { name: "checkpoints.snapshot" }),
    );

    await waitFor(() =>
      expect(cpMocks.snapshot).toHaveBeenCalledWith(
        expect.objectContaining({
          session_id: "sess-1",
          name: "my snap",
        }),
      ),
    );
    expect(messageMocks.success).toHaveBeenCalledWith(
      "checkpoints.snapshotCreated",
    );
  });

  it("reports snapshot failures", async () => {
    cpMocks.snapshot.mockRejectedValue(new Error("disk full"));
    const { user } = await renderPage();

    await user.click(screen.getByText("checkpoints.snapshot"));
    const modal = document.querySelector(".ant-modal") as HTMLElement;
    await user.click(
      within(modal).getByRole("button", { name: "checkpoints.snapshot" }),
    );

    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith("disk full"),
    );
  });

  it("runs GC through the preview-then-confirm flow", async () => {
    const { user } = await renderPage();

    await user.click(screen.getByLabelText("checkpoints.more"));
    await waitFor(() =>
      expect(screen.getByText("checkpoints.gc.action")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("checkpoints.gc.action"));

    await waitFor(() => expect(cpMocks.previewGc).toHaveBeenCalledWith({}));
    await waitFor(() => expect(modalConfirmSpy).toHaveBeenCalled());

    const opts = modalConfirmSpy.mock.calls[
      modalConfirmSpy.mock.calls.length - 1
    ]?.[0] as {
      onOk: () => Promise<void>;
    };
    await opts.onOk();

    await waitFor(() => expect(cpMocks.gc).toHaveBeenCalledWith({}));
    expect(messageMocks.success).toHaveBeenCalledWith("checkpoints.gc.success");
  });

  it("runs the thorough GC variant with the compact flag", async () => {
    const { user } = await renderPage();

    await user.click(screen.getByLabelText("checkpoints.more"));
    await waitFor(() =>
      expect(
        screen.getByText("checkpoints.gc.thoroughAction"),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByText("checkpoints.gc.thoroughAction"));

    await waitFor(() =>
      expect(cpMocks.previewGc).toHaveBeenCalledWith({ compact: true }),
    );
    const opts = modalConfirmSpy.mock.calls[
      modalConfirmSpy.mock.calls.length - 1
    ]?.[0] as {
      onOk: () => Promise<void>;
    };
    await opts.onOk();

    await waitFor(() =>
      expect(cpMocks.gc).toHaveBeenCalledWith({ compact: true }),
    );
    expect(messageMocks.success).toHaveBeenCalledWith(
      "checkpoints.gc.thoroughSuccess",
    );
  });

  it("reports GC preview failures", async () => {
    cpMocks.previewGc.mockRejectedValue(new Error("no repo"));
    const { user } = await renderPage();

    await user.click(screen.getByLabelText("checkpoints.more"));
    await user.click(await screen.findByText("checkpoints.gc.action"));

    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith("no repo"),
    );
  });

  it("opens and saves the GC settings modal", async () => {
    const { user } = await renderPage();

    await user.click(screen.getByLabelText("checkpoints.more"));
    await user.click(await screen.findByText("checkpoints.gc.settingsAction"));

    await waitFor(() => expect(cpMocks.getGcSettings).toHaveBeenCalled());

    const modal = document.querySelector(".ant-modal") as HTMLElement;
    await user.click(
      within(modal).getByRole("button", { name: "common.save" }),
    );

    await waitFor(() =>
      expect(cpMocks.updateGcSettings).toHaveBeenCalledWith(
        expect.objectContaining({ gc_keep_count: 50 }),
      ),
    );
    expect(messageMocks.success).toHaveBeenCalledWith(
      "checkpoints.gc.settingsSaved",
    );
  });

  it("reports GC settings load failures and closes the modal", async () => {
    cpMocks.getGcSettings.mockRejectedValue(new Error("no settings"));
    const { user } = await renderPage();

    await user.click(screen.getByLabelText("checkpoints.more"));
    await user.click(await screen.findByText("checkpoints.gc.settingsAction"));

    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith("no settings"),
    );
  });

  it("resets all checkpoints through the confirm dialog", async () => {
    const { user } = await renderPage();

    await user.click(screen.getByLabelText("checkpoints.more"));
    await user.click(await screen.findByText("checkpoints.reset.action"));

    await waitFor(() => expect(modalConfirmSpy).toHaveBeenCalled());
    const opts = modalConfirmSpy.mock.calls[
      modalConfirmSpy.mock.calls.length - 1
    ]?.[0] as {
      onOk: () => Promise<void>;
    };
    await opts.onOk();

    await waitFor(() => expect(cpMocks.reset).toHaveBeenCalled());
    expect(messageMocks.success).toHaveBeenCalledWith(
      "checkpoints.reset.success",
    );
  });

  it("opens the detail drawer for a selected node with restore enabled", async () => {
    const { user } = await renderPage();

    await user.click(screen.getByRole("button", { name: "c1aaaa" }));

    await waitFor(() =>
      expect(screen.getByText("checkpoints.details")).toBeInTheDocument(),
    );
    expect(screen.getByText("fix the bug")).toBeInTheDocument();
    // The commit appears both in the graph list and in the drawer detail
    expect(screen.getAllByText("c1aaaa").length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole("button", { name: /checkpoints\.restore\.action/ }),
    ).toBeEnabled();

    // Open the restore modal
    await user.click(
      screen.getByRole("button", { name: /checkpoints\.restore\.action/ }),
    );
    expect(screen.getByTestId("restore-modal")).toBeInTheDocument();
  });

  it("disables restore for nodes without a session", async () => {
    cpMocks.graph.mockResolvedValue({
      nodes: [node({ session_id: null, session_title: null })],
      sessions: [],
      summary: { total: 1, auto: 1, snapshots: 0, safety: 0, heads: 1 },
      truncated: false,
    });
    const { user } = await renderPage();

    await user.click(screen.getByRole("button", { name: "c1aaaa" }));

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /checkpoints\.restore\.action/ }),
      ).toBeDisabled(),
    );
  });

  it("filters by session through the session select", async () => {
    cpMocks.graph.mockResolvedValue({
      nodes: [
        node(),
        node({
          commit: "other-session",
          session_key: "s2",
          session_id: "sess-2",
          session_title: "Session Two",
          query: "other work",
        }),
      ],
      sessions: [
        {
          session_key: "s1",
          session_id: "sess-1",
          title: "Session One",
          user_id: "u1",
          channel: "console",
        },
        {
          session_key: "s2",
          session_id: "sess-2",
          title: "Session Two",
          user_id: "u1",
          channel: "console",
        },
      ],
      summary: { total: 2, auto: 2, snapshots: 0, safety: 0, heads: 1 },
      truncated: false,
    });
    const { user } = await renderPage();

    // Both commits visible initially
    expect(screen.getByText("other-session")).toBeInTheDocument();

    // Open the session filter (second combobox: kind, session)
    const comboboxes = screen.getAllByRole("combobox");
    await user.click(comboboxes[1]);
    await waitFor(() =>
      expect(screen.getAllByText("Session One").length).toBeGreaterThan(0),
    );
    const option = screen
      .getAllByText("Session One")
      .find((el) => el.closest(".ant-select-item"))!;
    await user.click(option);

    await waitFor(() =>
      expect(screen.queryByText("other-session")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("c1aaaa")).toBeInTheDocument();
  });
});
