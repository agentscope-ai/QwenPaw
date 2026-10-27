// @vitest-environment jsdom
/**
 * RestoreModal unit tests - Agent > Checkpoints > restore dialog.
 *
 * The component owns a two step flow: pick a restore scope, then preview it and
 * confirm. What this file pins down is the wiring the page cannot see:
 *
 *  - the reset effect keyed on `[open, node?.commit]` (not on `node` itself),
 *  - the fallback chain that builds the request payload out of a partial node,
 *  - the two guards that make `previewRestore` / `applyRestore` no-ops,
 *  - the derived `fileStatus` list (deleted vs restored) and the select-all
 *    checkbox state machine built on top of it,
 *  - which commit the confirmation actually sends (the one resolved by the
 *    preview, not the one on the node).
 *
 * antd is used directly by the product file, so the real Modal / Checkbox /
 * Alert / Divider / Spin are rendered here (no design stub is involved).
 * `checkpointsApi` and `useAppMessage` are mocked: this file asserts what the
 * modal sends and what it tells the user, not the transport.
 *
 * One arm is never hit by this suite and is pinned by observation instead of
 * being forced: `{previewing ? <Spin/> : ...}` lives inside the `preview`
 * branch, while `setPreview(result)` and `setPreviewing(false)` land in the
 * same async continuation. React 18 batching the two into a single render is
 * the assumed mechanism here, not an asserted one, so the test below only
 * claims what it measures: no spinner renders in flight, and none renders once
 * the host block is up either.
 * See "renders no spinner in flight nor once the preview resolved".
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { act } from "react";
// antd is imported by the product file directly, so the real components render.
// Only `Spin` is imported here, and only as the positive control that proves
// the `.ant-spin` selector used by the unreachability test really detects a
// spinner (see "renders no spinner in flight nor once the preview resolved").
import { Spin } from "antd";
import type { CheckpointNode, RestoreResult } from "@/api/types/checkpoints";

// ---- Hoisted mocks ---------------------------------------------------------

const cpMocks = vi.hoisted(() => ({
  status: vi.fn(),
  graph: vi.fn(),
  setAuto: vi.fn(),
  snapshot: vi.fn(),
  previewRestore: vi.fn(),
  restore: vi.fn(),
  previewGc: vi.fn(),
  runGc: vi.fn(),
  getGcSettings: vi.fn(),
  updateGcSettings: vi.fn(),
  reset: vi.fn(),
}));

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}));

vi.mock("@/api/modules/checkpoints", () => ({
  checkpointsApi: cpMocks,
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: messageMocks }),
}));

// Identity translator, but interpolation is surfaced so the selected-count
// label can be asserted on its real argument instead of on a rendered number.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: {
      language: "en",
      resolvedLanguage: "en",
      changeLanguage: vi.fn(),
    },
  }),
}));

import { RestoreModal } from "./RestoreModal";
import styles from "./index.module.less";

// ---- Fixtures --------------------------------------------------------------

const COMMIT = "abc1234";

function makeNode(overrides: Partial<CheckpointNode> = {}): CheckpointNode {
  return {
    ref: "refs/heads/main",
    kind: "snap",
    session_key: "sess-key",
    name: "snapshot-name",
    commit: COMMIT,
    sha: `${COMMIT}fullsha`,
    timestamp_ms: 1_700_000_000_000,
    subject: "subject-line",
    query: "query-line",
    channel: "console",
    restore_index: null,
    parent_commit: null,
    is_head: true,
    user_id: "user-1",
    session_id: "session-1",
    session_title: "session-title",
    ...overrides,
  };
}

function makeResult(overrides: Partial<RestoreResult> = {}): RestoreResult {
  return {
    target: "restore-target",
    commit: `${COMMIT}resolved`,
    restored_paths: ["a.txt"],
    deleted_paths: ["b.txt"],
    file_paths: ["a.txt", "b.txt"],
    pre_restore_ref: null,
    dry_run: true,
    include_memory: false,
    include_files: true,
    ...overrides,
  };
}

// A node whose identity fields are missing. `if (!node)` only rejects null, so
// this still reaches the payload builder and exercises every `?? ""` fallback.
const PARTIAL_NODE = {
  query: "partial-query",
} as unknown as CheckpointNode;

const LABEL_CONVERSATION = "checkpoints.restore.conversation";
const LABEL_MEMORY = "checkpoints.restore.memory";
const LABEL_FILES = "checkpoints.restore.files";
const LABEL_SELECT_ALL = "checkpoints.restore.selectAll";
const BTN_PREVIEW = "checkpoints.restore.preview";
const BTN_CONFIRM = "checkpoints.restore.confirm";
const BTN_BACK = "common.back";
const BTN_CANCEL = "common.cancel";
const WARNING = "checkpoints.restore.refreshWarning";

// ---- Helpers ---------------------------------------------------------------

type Handlers = {
  onClose: ReturnType<typeof vi.fn<() => void>>;
  onRestored: ReturnType<typeof vi.fn<() => void>>;
};

function renderModal(
  props: {
    open?: boolean;
    node?: CheckpointNode | null;
    onClose?: Handlers["onClose"];
    onRestored?: Handlers["onRestored"];
  } = {},
) {
  const onClose = props.onClose ?? vi.fn();
  const onRestored = props.onRestored ?? vi.fn();
  const view = render(
    <RestoreModal
      open={props.open ?? true}
      node={props.node === undefined ? makeNode() : props.node}
      onClose={onClose}
      onRestored={onRestored}
    />,
  );
  return { ...view, onClose, onRestored };
}

function dialog(): HTMLElement {
  const found = screen.getByRole("dialog");
  return found;
}

function footer(): HTMLElement {
  const found = document.querySelector(".ant-modal-footer");
  if (!found) throw new Error("footer missing");
  return found as HTMLElement;
}

function checkbox(label: string): HTMLInputElement {
  const found = screen.getByRole("checkbox", { name: label });
  return found as HTMLInputElement;
}

function clickCheckbox(label: string) {
  fireEvent.click(checkbox(label));
}

function button(name: string): HTMLButtonElement {
  // Match on textContent, not on the accessible name: once an antd button has
  // been through a loading cycle its accessible name picks up the spinner's
  // `aria-label="loading"`, while its textContent stays the plain label.
  const all = Array.from(screen.getAllByRole("button"));
  const hit = all.find((el) => (el.textContent ?? "").includes(name));
  if (!hit) throw new Error(`button not found: ${name}`);
  return hit as HTMLButtonElement;
}

// The indeterminate flag lives on the inner `.ant-checkbox` span (the input's
// parent), not on the outer `<label>` wrapper.
function selectAllInnerClass(): string {
  const all = checkbox(LABEL_SELECT_ALL);
  const inner = all.parentElement;
  if (!inner) throw new Error("select-all inner span missing");
  return inner.className;
}

async function openPreview(result: RestoreResult = makeResult()) {
  cpMocks.previewRestore.mockResolvedValue(result);
  fireEvent.click(button(BTN_PREVIEW));
  await waitFor(() => expect(cpMocks.previewRestore).toHaveBeenCalled());
  await screen.findByRole("alert");
}

function fileRow(path: string): HTMLElement {
  const codes = Array.from(document.querySelectorAll("code"));
  const hit = codes.find((el) => el.textContent === path);
  if (!hit) throw new Error(`file row missing for ${path}`);
  const wrapper = hit.closest("label");
  if (!wrapper) throw new Error(`file row label missing for ${path}`);
  return wrapper as HTMLElement;
}

// Let every pending microtask and state update settle. Used before asserting
// that something did NOT happen, so the negative is not vacuous.
async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  cpMocks.previewRestore.mockResolvedValue(makeResult());
  cpMocks.restore.mockResolvedValue(makeResult());
});

// ---- Tests -----------------------------------------------------------------

describe("visibility", () => {
  it("renders nothing at all while closed", () => {
    renderModal({ open: false });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.querySelector(".ant-modal-root")).toBeNull();
    expect(cpMocks.previewRestore).not.toHaveBeenCalled();
  });

  it("renders the dialog with the restore title once open", () => {
    renderModal();
    expect(dialog()).toBeInTheDocument();
    expect(document.querySelector(".ant-modal-title")?.textContent).toBe(
      "checkpoints.restore.title",
    );
    // The width prop is the only layout contract the page relies on.
    expect(
      (document.querySelector(".ant-modal") as HTMLElement).style.width,
    ).toBe("620px");
  });

  it("calls onClose from the modal cancel affordance", () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose from the footer cancel button", () => {
    const { onClose } = renderModal();
    fireEvent.click(button(BTN_CANCEL));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("target line", () => {
  it("prefers the query text for the target label", () => {
    renderModal({ node: makeNode({ query: "q", name: "n", subject: "s" }) });
    const target = document.querySelector(`.${styles.restoreTarget}`);
    expect(target).not.toBeNull();
    expect(target?.querySelector("span")?.textContent).toBe("q");
    expect(target?.querySelector("code")?.textContent).toBe(COMMIT);
  });

  it("falls back to the snapshot name when there is no query", () => {
    renderModal({ node: makeNode({ query: null, name: "n", subject: "s" }) });
    expect(
      document.querySelector(`.${styles.restoreTarget} span`)?.textContent,
    ).toBe("n");
  });

  it("falls back to the subject when both query and name are empty", () => {
    renderModal({
      node: makeNode({ query: null, name: "", subject: "s" }),
    });
    expect(
      document.querySelector(`.${styles.restoreTarget} span`)?.textContent,
    ).toBe("s");
  });

  it("renders an empty target line for a null node instead of throwing", () => {
    renderModal({ node: null });
    expect(
      document.querySelector(`.${styles.restoreTarget} span`)?.textContent,
    ).toBe("");
    expect(
      document.querySelector(`.${styles.restoreTarget} code`),
    ).not.toBeNull();
  });
});

describe("scope step", () => {
  it("shows the conversation scope as checked and permanently disabled", () => {
    renderModal();
    const box = checkbox(LABEL_CONVERSATION);
    expect(box.checked).toBe(true);
    expect(box.disabled).toBe(true);
    // Negative control: the two opt-in scopes are editable.
    expect(checkbox(LABEL_MEMORY).disabled).toBe(false);
    expect(checkbox(LABEL_FILES).disabled).toBe(false);
  });

  it("starts with both opt-in scopes off", () => {
    renderModal();
    expect(checkbox(LABEL_MEMORY).checked).toBe(false);
    expect(checkbox(LABEL_FILES).checked).toBe(false);
  });

  it("does not render the preview block before a preview exists", () => {
    renderModal();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("separator")).toBeNull();
    expect(
      screen.queryByRole("checkbox", { name: LABEL_SELECT_ALL }),
    ).toBeNull();
    expect(document.querySelector(`.${styles.scopeOptions}`)).not.toBeNull();
  });

  it("offers cancel and preview in the footer", () => {
    renderModal();
    expect(footer().textContent).toContain(BTN_CANCEL);
    expect(footer().textContent).toContain(BTN_PREVIEW);
    expect(footer().textContent).not.toContain(BTN_CONFIRM);
    expect(button(BTN_PREVIEW).disabled).toBe(false);
  });
});

describe("reset effect", () => {
  it("clears scope, preview and selection when the dialog is reopened", async () => {
    const view = renderModal();
    clickCheckbox(LABEL_MEMORY);
    clickCheckbox(LABEL_FILES);
    await openPreview();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(checkbox(LABEL_SELECT_ALL)).toBeInTheDocument();

    // Closing keeps the component mounted, so the state survives in React.
    view.rerender(
      <RestoreModal
        open={false}
        node={makeNode()}
        onClose={view.onClose}
        onRestored={view.onRestored}
      />,
    );
    await flush();

    view.rerender(
      <RestoreModal
        open
        node={makeNode()}
        onClose={view.onClose}
        onRestored={view.onRestored}
      />,
    );
    await flush();

    // The effect keyed on `[open, node?.commit]` must have wiped everything.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen.queryByRole("checkbox", { name: LABEL_SELECT_ALL }),
    ).toBeNull();
    expect(checkbox(LABEL_MEMORY).checked).toBe(false);
    expect(checkbox(LABEL_FILES).checked).toBe(false);
    expect(footer().textContent).toContain(BTN_PREVIEW);
  });

  it("drops a stale preview when a different commit is selected", async () => {
    const view = renderModal({ node: makeNode({ commit: "first111" }) });
    await openPreview();
    expect(screen.getByRole("alert")).toBeInTheDocument();

    view.rerender(
      <RestoreModal
        open
        node={makeNode({ commit: "second22" })}
        onClose={view.onClose}
        onRestored={view.onRestored}
      />,
    );

    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      document.querySelector(`.${styles.restoreTarget} code`)?.textContent,
    ).toBe("second22");
    // Back on the scope step, with both opt-in scopes cleared.
    expect(checkbox(LABEL_MEMORY).checked).toBe(false);
    expect(checkbox(LABEL_FILES).checked).toBe(false);
  });

  it("does not reset while the dialog stays open on the same commit", async () => {
    const view = renderModal({ node: makeNode({ commit: "same1234" }) });
    clickCheckbox(LABEL_MEMORY);
    await openPreview();
    expect(screen.getByRole("alert")).toBeInTheDocument();

    // Same open flag, same commit: the effect must not fire again, so the
    // preview survives even though a re-render happened.
    view.rerender(
      <RestoreModal
        open
        node={makeNode({ commit: "same1234", name: "renamed" })}
        onClose={view.onClose}
        onRestored={view.onRestored}
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: LABEL_MEMORY })).toBeNull();
    expect(footer().textContent).toContain(BTN_CONFIRM);
  });
});

describe("preview request", () => {
  it("sends the scope and the node identity", async () => {
    renderModal();
    await openPreview(makeResult({ file_paths: [], deleted_paths: [] }));
    expect(cpMocks.previewRestore).toHaveBeenCalledTimes(1);
    expect(cpMocks.previewRestore).toHaveBeenCalledWith({
      commit: COMMIT,
      session_id: "session-1",
      user_id: "user-1",
      channel: "console",
      include_memory: false,
      include_files: false,
    });
  });

  it("reports both opt-in scopes once they are ticked", async () => {
    renderModal();
    clickCheckbox(LABEL_MEMORY);
    clickCheckbox(LABEL_FILES);
    await openPreview();
    expect(cpMocks.previewRestore).toHaveBeenCalledWith(
      expect.objectContaining({ include_memory: true, include_files: true }),
    );
  });

  it("substitutes empty strings and the console channel for a partial node", async () => {
    renderModal({ node: PARTIAL_NODE });
    await openPreview(makeResult({ file_paths: [], deleted_paths: [] }));
    expect(cpMocks.previewRestore).toHaveBeenCalledWith({
      commit: "",
      session_id: "",
      user_id: "",
      channel: "console",
      include_memory: false,
      include_files: false,
    });
  });

  it("keeps a node channel that is present", async () => {
    renderModal({ node: makeNode({ channel: "dingtalk" }) });
    await openPreview(makeResult({ file_paths: [], deleted_paths: [] }));
    expect(cpMocks.previewRestore).toHaveBeenCalledWith(
      expect.objectContaining({ channel: "dingtalk" }),
    );
  });

  it("does not call the api when there is no node", async () => {
    renderModal({ node: null });
    fireEvent.click(button(BTN_PREVIEW));
    await flush();
    expect(cpMocks.previewRestore).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(messageMocks.error).not.toHaveBeenCalled();
  });

  it("calls the api for the very same click once a node exists", async () => {
    // Positive control for the guard above.
    renderModal({ node: makeNode() });
    fireEvent.click(button(BTN_PREVIEW));
    await waitFor(() =>
      expect(cpMocks.previewRestore).toHaveBeenCalledTimes(1),
    );
  });

  it("surfaces the failure and stays on the scope step", async () => {
    cpMocks.previewRestore.mockRejectedValue(new Error("preview boom"));
    renderModal();
    fireEvent.click(button(BTN_PREVIEW));
    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith("preview boom"),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(footer().textContent).toContain(BTN_PREVIEW);
    expect(button(BTN_PREVIEW).disabled).toBe(false);
  });

  it("renders no spinner in flight nor once the preview resolved", async () => {
    // `previewing` is only true between the click and the resolution, and the
    // only spinner that reads it sits inside the `preview` branch, gated by
    // `includeFiles`. Two states are therefore checked, and they need two
    // different controls:
    //   - in flight the host block is not mounted at all, so an absent spinner
    //     there says nothing about the selector. The host absence is asserted
    //     first, so that the spinner assertion is read as "still on the scope
    //     step" rather than as a finding.
    //   - once the preview resolved the host IS mounted, so `.ant-spin` is
    //     queried inside a scope that actually exists. That is the assertion
    //     with discriminating power.
    //
    // Positive control first: the `.ant-spin` selector does detect a real antd
    // Spin anywhere in the document.
    const control = render(<Spin size="small" />);
    expect(document.querySelectorAll(".ant-spin")).toHaveLength(1);
    control.unmount();
    expect(document.querySelectorAll(".ant-spin")).toHaveLength(0);

    let release: (value: RestoreResult) => void = () => {};
    cpMocks.previewRestore.mockReturnValue(
      new Promise<RestoreResult>((resolve) => {
        release = resolve;
      }),
    );
    renderModal();
    clickCheckbox(LABEL_FILES);
    fireEvent.click(button(BTN_PREVIEW));

    await waitFor(() => expect(cpMocks.previewRestore).toHaveBeenCalled());
    // In flight: the host block is absent by construction (the preview button
    // that triggered the call only renders while `preview` is null). Both
    // queries below are therefore expected to miss.
    expect(document.querySelector(`.${styles.fileSelection}`)).toBeNull();
    expect(document.querySelector(".ant-spin")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    // The in-flight state is observable on the preview button only.
    expect(button(BTN_PREVIEW).className).toContain("ant-btn-loading");

    await act(async () => {
      release(makeResult({ file_paths: ["a.txt"], deleted_paths: [] }));
    });
    await screen.findByRole("alert");
    // Settled: the host block is mounted and holds one file row, so the
    // `.ant-spin` query below runs against a scope that exists. This is the
    // assertion that would fail if the spinner arm ever rendered.
    const host = document.querySelector(`.${styles.fileSelection}`);
    expect(host).not.toBeNull();
    expect(host?.querySelectorAll("label")).toHaveLength(1);
    expect(host?.querySelectorAll(".ant-spin")).toHaveLength(0);
    expect(document.querySelectorAll(".ant-spin")).toHaveLength(0);

    // Second positive control, at the scope the assertion above actually uses:
    // a spinner injected into the host block is found by the host-scoped query.
    // Without this, "0 spinners inside the host" could still be a vacuous
    // result (the document-level control above only proves the selector works
    // somewhere, not inside this scope). The injection is synthetic and torn
    // down in the same test: the product code is never touched.
    const probeHost = document.createElement("div");
    host?.appendChild(probeHost);
    render(<Spin size="small" />, { container: probeHost });
    expect(host?.querySelectorAll(".ant-spin")).toHaveLength(1);
    expect(host?.querySelectorAll("label")).toHaveLength(1);
    act(() => {
      probeHost.remove();
    });
    expect(host?.querySelectorAll(".ant-spin")).toHaveLength(0);
    expect(document.querySelectorAll(".ant-spin")).toHaveLength(0);
    // The scope step (and its button) is gone, so check the flag globally: no
    // antd button may still be marked as loading once the call settled.
    expect(document.querySelectorAll(".ant-btn-loading")).toHaveLength(0);
    expect(footer().textContent).toContain(BTN_CONFIRM);
  });
});

describe("preview block", () => {
  it("shows the refresh warning, the conversation line and the new footer", async () => {
    renderModal();
    await openPreview(makeResult({ file_paths: [], deleted_paths: [] }));
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe(WARNING);
    expect(alert.className).toContain("ant-alert-warning");

    const summary = document.querySelector(`.${styles.previewSummary}`);
    expect(summary).not.toBeNull();
    expect(summary?.textContent).toBe(LABEL_CONVERSATION);

    expect(document.querySelector(`.${styles.scopeOptions}`)).toBeNull();
    expect(footer().textContent).toContain(BTN_BACK);
    expect(footer().textContent).toContain(BTN_CONFIRM);
    expect(footer().textContent).not.toContain(BTN_PREVIEW);
  });

  it("adds the memory line to the summary only when memory was requested", async () => {
    renderModal();
    clickCheckbox(LABEL_MEMORY);
    await openPreview(makeResult({ file_paths: [], deleted_paths: [] }));
    expect(
      document.querySelector(`.${styles.previewSummary}`)?.textContent,
    ).toBe(`${LABEL_CONVERSATION}${LABEL_MEMORY}`);
  });

  it("adds the selected-count line to the summary once files are in scope", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview(makeResult({ file_paths: ["a.txt"], deleted_paths: [] }));
    expect(
      document.querySelector(`.${styles.previewSummary}`)?.textContent,
    ).toBe(
      `${LABEL_CONVERSATION}checkpoints.restore.selectedCount:{"count":0}`,
    );
  });

  it("counts the ticks in the summary as files are selected", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    fireEvent.click(checkbox("a.txtcheckpoints.restore.restore"));
    expect(
      document.querySelector(`.${styles.previewSummary}`)?.textContent,
    ).toBe(
      `${LABEL_CONVERSATION}checkpoints.restore.selectedCount:{"count":1}`,
    );
  });

  it("hides the file section entirely when files are out of scope", async () => {
    renderModal();
    await openPreview();
    expect(screen.queryByRole("separator")).toBeNull();
    expect(
      screen.queryByRole("checkbox", { name: LABEL_SELECT_ALL }),
    ).toBeNull();
    expect(document.querySelector(`.${styles.fileSelection}`)).toBeNull();
    // The preview still carried two paths, so this is the scope flag talking.
    expect(cpMocks.previewRestore).toHaveBeenCalledWith(
      expect.objectContaining({ include_files: false }),
    );
  });

  it("returns to the scope step from the back button and forgets the preview", async () => {
    renderModal();
    clickCheckbox(LABEL_MEMORY);
    await openPreview();
    fireEvent.click(button(BTN_BACK));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.querySelector(`.${styles.scopeOptions}`)).not.toBeNull();
    expect(footer().textContent).toContain(BTN_PREVIEW);
    // Going back keeps the scope the user picked; it only drops the preview.
    expect(checkbox(LABEL_MEMORY).checked).toBe(true);
  });

  it("lets the memory scope be cleared again from the scope step", async () => {
    renderModal();
    clickCheckbox(LABEL_MEMORY);
    expect(checkbox(LABEL_MEMORY).checked).toBe(true);
    clickCheckbox(LABEL_MEMORY);
    expect(checkbox(LABEL_MEMORY).checked).toBe(false);
    // Both directions report the same empty scope to the api.
    await openPreview(makeResult({ file_paths: [], deleted_paths: [] }));
    expect(cpMocks.previewRestore).toHaveBeenCalledWith(
      expect.objectContaining({ include_memory: false }),
    );
  });
});

describe("file list", () => {
  it("lists every path with its delete or restore status", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview(
      makeResult({
        file_paths: ["a.txt", "b.txt", "c.txt"],
        deleted_paths: ["b.txt"],
      }),
    );
    const list = document.querySelector(`.${styles.fileSelection}`);
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll("label")).toHaveLength(3);

    expect(fileRow("a.txt").textContent).toBe(
      "a.txtcheckpoints.restore.restore",
    );
    expect(fileRow("b.txt").textContent).toBe(
      "b.txtcheckpoints.restore.delete",
    );
    expect(fileRow("c.txt").textContent).toBe(
      "c.txtcheckpoints.restore.restore",
    );

    expect(
      within(fileRow("a.txt")).getByText("checkpoints.restore.restore")
        .className,
    ).toContain(styles.restoreStatus);
    expect(
      within(fileRow("b.txt")).getByText("checkpoints.restore.delete")
        .className,
    ).toContain(styles.deleteStatus);
  });

  it("shows the muted placeholder when the preview reports no file changes", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview(makeResult({ file_paths: [], deleted_paths: [] }));
    const list = document.querySelector(`.${styles.fileSelection}`);
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll("label")).toHaveLength(0);
    const muted = list?.querySelector(`.${styles.muted}`);
    expect(muted?.textContent).toBe("checkpoints.restore.noFileChanges");
  });

  it("treats every path as restored when nothing was deleted", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview(makeResult({ file_paths: ["x"], deleted_paths: [] }));
    expect(fileRow("x").textContent).toBe("xcheckpoints.restore.restore");
  });

  it("marks an unlisted deleted path as irrelevant", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview(
      makeResult({ file_paths: ["a.txt"], deleted_paths: ["ghost.txt"] }),
    );
    expect(fileRow("a.txt").textContent).toBe(
      "a.txtcheckpoints.restore.restore",
    );
    expect(screen.queryByText("ghost.txt")).toBeNull();
  });

  it("keeps the select-all box unchecked and not indeterminate at first", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    const all = checkbox(LABEL_SELECT_ALL);
    expect(all.checked).toBe(false);
    expect(selectAllInnerClass()).not.toContain("ant-checkbox-indeterminate");
  });

  it("selects every path through the select-all box", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    fireEvent.click(checkbox(LABEL_SELECT_ALL));
    expect(checkbox("a.txtcheckpoints.restore.restore").checked).toBe(true);
    expect(checkbox("b.txtcheckpoints.restore.delete").checked).toBe(true);
    expect(checkbox(LABEL_SELECT_ALL).checked).toBe(true);
    expect(selectAllInnerClass()).not.toContain("ant-checkbox-indeterminate");
  });

  it("empties the selection when select-all is unticked", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    fireEvent.click(checkbox(LABEL_SELECT_ALL));
    fireEvent.click(checkbox(LABEL_SELECT_ALL));
    expect(checkbox("a.txtcheckpoints.restore.restore").checked).toBe(false);
    expect(checkbox("b.txtcheckpoints.restore.delete").checked).toBe(false);
    expect(checkbox(LABEL_SELECT_ALL).checked).toBe(false);
  });

  it("turns indeterminate once a single path is ticked", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    fireEvent.click(checkbox("a.txtcheckpoints.restore.restore"));
    expect(selectAllInnerClass()).toContain("ant-checkbox-indeterminate");
    expect(checkbox(LABEL_SELECT_ALL).checked).toBe(false);
  });

  it("turns fully checked when the last path is ticked by hand", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    fireEvent.click(checkbox("a.txtcheckpoints.restore.restore"));
    fireEvent.click(checkbox("b.txtcheckpoints.restore.delete"));
    expect(checkbox(LABEL_SELECT_ALL).checked).toBe(true);
    expect(selectAllInnerClass()).not.toContain("ant-checkbox-indeterminate");
  });

  it("drops a single path without touching the others", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    fireEvent.click(checkbox(LABEL_SELECT_ALL));
    fireEvent.click(checkbox("b.txtcheckpoints.restore.delete"));
    expect(checkbox("a.txtcheckpoints.restore.restore").checked).toBe(true);
    expect(checkbox("b.txtcheckpoints.restore.delete").checked).toBe(false);
    expect(selectAllInnerClass()).toContain("ant-checkbox-indeterminate");
  });

  it("keeps the select-all box unchecked when there are no paths at all", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview(makeResult({ file_paths: [], deleted_paths: [] }));
    const all = checkbox(LABEL_SELECT_ALL);
    expect(all.checked).toBe(false);
    expect(selectAllInnerClass()).not.toContain("ant-checkbox-indeterminate");
  });

  it("resets the selection when the files scope is toggled off and on", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    fireEvent.click(checkbox(LABEL_SELECT_ALL));
    expect(checkbox("a.txtcheckpoints.restore.restore").checked).toBe(true);

    // Back to the scope step, then flip the files scope: the preview and the
    // selection are both dropped by scopeChanged.
    fireEvent.click(button(BTN_BACK));
    clickCheckbox(LABEL_FILES);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen.queryByRole("checkbox", { name: LABEL_SELECT_ALL }),
    ).toBeNull();
  });
});

describe("confirm gating", () => {
  it("enables the confirm button when files are out of scope", async () => {
    renderModal();
    await openPreview();
    expect(button(BTN_CONFIRM).disabled).toBe(false);
  });

  it("disables the confirm button while files are in scope but nothing is picked", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    expect(button(BTN_CONFIRM).disabled).toBe(true);
  });

  it("enables the confirm button as soon as one path is picked", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    fireEvent.click(checkbox("a.txtcheckpoints.restore.restore"));
    expect(button(BTN_CONFIRM).disabled).toBe(false);
  });

  it("marks the confirm button as the destructive action", async () => {
    renderModal();
    await openPreview();
    expect(button(BTN_CONFIRM).className).toContain("ant-btn-dangerous");
    expect(button(BTN_CONFIRM).className).toContain("ant-btn-primary");
    expect(button(BTN_BACK).className).not.toContain("ant-btn-dangerous");
  });
});

describe("apply restore", () => {
  it("pins the confirmation to the commit resolved by the preview", async () => {
    renderModal();
    await openPreview(makeResult({ commit: "resolved99" }));
    fireEvent.click(button(BTN_CONFIRM));
    await waitFor(() => expect(cpMocks.restore).toHaveBeenCalledTimes(1));
    expect(cpMocks.restore).toHaveBeenCalledWith({
      commit: "resolved99",
      session_id: "session-1",
      user_id: "user-1",
      channel: "console",
      include_memory: false,
      include_files: false,
      files: undefined,
    });
  });

  it("omits the file list when files are out of scope", async () => {
    renderModal();
    clickCheckbox(LABEL_MEMORY);
    await openPreview();
    fireEvent.click(button(BTN_CONFIRM));
    await waitFor(() => expect(cpMocks.restore).toHaveBeenCalled());
    const payload = cpMocks.restore.mock.calls[0][0];
    expect(payload.files).toBeUndefined();
    expect(payload.include_memory).toBe(true);
    expect(payload.include_files).toBe(false);
  });

  it("sends exactly the picked paths when files are in scope", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    fireEvent.click(checkbox("b.txtcheckpoints.restore.delete"));
    fireEvent.click(button(BTN_CONFIRM));
    await waitFor(() => expect(cpMocks.restore).toHaveBeenCalled());
    expect(cpMocks.restore).toHaveBeenCalledWith(
      expect.objectContaining({
        include_files: true,
        files: ["b.txt"],
      }),
    );
  });

  it("sends every path when select-all was used", async () => {
    renderModal();
    clickCheckbox(LABEL_FILES);
    await openPreview();
    fireEvent.click(checkbox(LABEL_SELECT_ALL));
    fireEvent.click(button(BTN_CONFIRM));
    await waitFor(() => expect(cpMocks.restore).toHaveBeenCalled());
    expect(cpMocks.restore.mock.calls[0][0].files).toEqual(["a.txt", "b.txt"]);
  });

  it("reports success, closes and notifies the page", async () => {
    const { onClose, onRestored } = renderModal();
    await openPreview();
    fireEvent.click(button(BTN_CONFIRM));
    await waitFor(() =>
      expect(messageMocks.success).toHaveBeenCalledWith(
        "checkpoints.restore.success",
      ),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onRestored).toHaveBeenCalledTimes(1);
    expect(messageMocks.error).not.toHaveBeenCalled();
  });

  it("reports the failure and keeps the dialog on the preview step", async () => {
    cpMocks.restore.mockRejectedValue(new Error("restore boom"));
    const { onClose, onRestored } = renderModal();
    await openPreview();
    fireEvent.click(button(BTN_CONFIRM));
    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith("restore boom"),
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(onRestored).not.toHaveBeenCalled();
    expect(messageMocks.success).not.toHaveBeenCalled();
    // Still on the preview step, so the user can retry.
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(footer().textContent).toContain(BTN_CONFIRM);
  });

  it("leaves the confirm button usable again after a failure", async () => {
    cpMocks.restore.mockRejectedValue(new Error("nope"));
    renderModal();
    await openPreview();
    fireEvent.click(button(BTN_CONFIRM));
    await waitFor(() => expect(messageMocks.error).toHaveBeenCalled());
    expect(button(BTN_CONFIRM).disabled).toBe(false);
    expect(button(BTN_CONFIRM).className).not.toContain("ant-btn-loading");
  });

  it("does nothing when the node disappeared under a kept preview", async () => {
    // The reset effect is keyed on `node?.commit`, so a node without a commit
    // can be swapped for null without the preview being dropped. The confirm
    // button stays on screen, and the guard is what stops the request.
    const view = renderModal({ node: PARTIAL_NODE });
    clickCheckbox(LABEL_MEMORY);
    await openPreview(
      makeResult({ commit: "resolved99", file_paths: [], deleted_paths: [] }),
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();

    view.rerender(
      <RestoreModal
        open
        node={null}
        onClose={view.onClose}
        onRestored={view.onRestored}
      />,
    );

    // Observed behaviour pinned without endorsement: the button is still
    // rendered and still enabled, but clicking it is a silent no-op.
    expect(footer().textContent).toContain(BTN_CONFIRM);
    expect(button(BTN_CONFIRM).disabled).toBe(false);
    fireEvent.click(button(BTN_CONFIRM));
    await flush();
    expect(cpMocks.restore).not.toHaveBeenCalled();
    expect(messageMocks.success).not.toHaveBeenCalled();
    expect(messageMocks.error).not.toHaveBeenCalled();
    expect(view.onClose).not.toHaveBeenCalled();
    expect(view.onRestored).not.toHaveBeenCalled();
  });
});
