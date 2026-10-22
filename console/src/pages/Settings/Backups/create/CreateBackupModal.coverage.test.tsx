/**
 * Unit tests for CreateBackupModal, the user-initiated backup dialog.
 *
 * Facts that shaped this suite (each one read off the source or measured):
 *
 * 1. antd renders for real here. The component imports `Modal, Input, Alert,
 *    Button, Space` straight from `antd`, so the input/textarea markup, the two
 *    notices and the danger button are the genuine article. Only `Modal` is
 *    stubbed, because antd fires `afterOpenChange` after the open animation,
 *    which never runs in jsdom; without a stub the whole "fresh session on
 *    open" contract (name prefill, description reset, scope reset,
 *    runner.reset) would be unreachable.
 * 2. The `Modal` stub fires `afterOpenChange(true)` once per open transition,
 *    not once per render. That matters: the component's handler rebuilds the
 *    scope object every call, so a stub keyed on the handler's identity would
 *    re-enter on every render. Real antd also fires it once, after the
 *    animation, so once-per-transition is the faithful shape.
 * 3. The `useBackupRunner` stub is backed by an external store subscribed with
 *    `useSyncExternalStore`, so flipping `loading` re-renders the dialog. A
 *    plain object read at render time cannot express "the user confirmed, now
 *    the progress view replaces the form".
 * 4. `./BackupScopeForm` and `./BackupProgress` are mocked on purpose (the
 *    scope form has its own suite next door), which keeps this file's coverage
 *    attributable to CreateBackupModal alone. The scope form mock exposes a
 *    button that emits a partial scope, so scope changes drive real state.
 * 5. `../shared/scope` is NOT mocked. `buildScope` and `defaultCreateScope` are
 *    product logic, so the payload handed to the runner is asserted end to end.
 * 6. The default name is `Backup ${dayjs().format("YYYY-MM-DD HH:mm")}`, so the
 *    clock is pinned with fake timers and the exact string is asserted. Every
 *    interaction uses `fireEvent` (synchronous), because `waitFor` can hang
 *    while fake timers are installed.
 * 7. `okButtonProps` is `{ style: { display: "none" } }` while running and
 *    `{ disabled: !name.trim() }` otherwise. The stub renders the OK button only
 *    when it is not display-hidden, so "confirm disappears while a backup runs"
 *    is a queryable fact rather than a style inspection.
 * 8. Both the footer danger button and `cancelText` render the same i18n key
 *    (`common.cancel`), so those two are told apart with `within(footerSlot)`
 *    instead of a document-wide text query.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import React from "react";
import type { AgentSummary } from "@/api/types/agents";
import type { BackupJobSnapshot } from "@/api/types/backup";

type RunnerSnapshot = {
  loading: boolean;
  progress: number;
  progressMsg: string;
};

// External store behind the useBackupRunner stub (see note 3).
const runnerStore = vi.hoisted(() => {
  let state = { loading: false, progress: 0, progressMsg: "" };
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((l) => l());
  return {
    get: () => state,
    set: (patch: Partial<typeof state>) => {
      state = { ...state, ...patch };
      notify();
    },
    clear: () => {
      state = { loading: false, progress: 0, progressMsg: "" };
      notify();
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    start: vi.fn(),
    resume: vi.fn(),
    cancel: vi.fn(),
    reset: vi.fn(),
  };
});

vi.mock("react-i18next", () => {
  const t = (key: string, opts?: Record<string, unknown>) =>
    opts ? `${key}:${JSON.stringify(opts)}` : key;
  return {
    useTranslation: () => ({
      t,
      i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
    }),
  };
});

vi.mock("../shared/useBackupRunner", () => ({
  useBackupRunner: () => {
    const snap = React.useSyncExternalStore(
      runnerStore.subscribe,
      runnerStore.get,
      runnerStore.get,
    ) as RunnerSnapshot;
    return {
      loading: snap.loading,
      progress: snap.progress,
      progressMsg: snap.progressMsg,
      // Mirrors the real hook: starting a job puts the dialog into its
      // running state.
      start: (payload: unknown) => {
        runnerStore.start(payload);
        runnerStore.set({ loading: true });
      },
      resume: runnerStore.resume,
      cancel: runnerStore.cancel,
      reset: runnerStore.reset,
    };
  },
}));

vi.mock("./BackupScopeForm", () => ({
  // Test double on purpose (see note 4). It renders the incoming value so the
  // assertions can read back what the modal passed down, and it exposes a
  // button that emits a partial scope, which drives real component state.
  default: function BackupScopeFormMock(props: {
    value: {
      backupMode: string;
      selectedAgents: string[];
      globalConfig: boolean;
      includeSkillPool: boolean;
      includeSecrets: boolean;
    };
    onChange: (next: Record<string, unknown>) => void;
    agents: { id: string }[];
  }) {
    return (
      <div data-testid="scope-form">
        <span data-testid="scope-value">
          {JSON.stringify([
            props.value.backupMode,
            props.value.selectedAgents,
            props.value.globalConfig,
            props.value.includeSkillPool,
            props.value.includeSecrets,
          ])}
        </span>
        <span data-testid="scope-agents">
          {props.agents.map((a) => a.id).join(",")}
        </span>
        <button
          type="button"
          data-testid="scope-to-partial"
          onClick={() =>
            props.onChange({
              ...props.value,
              backupMode: "partial",
              selectedAgents: ["a2"],
              globalConfig: false,
              includeSkillPool: false,
              includeSecrets: true,
            })
          }
        >
          to-partial
        </button>
        <button
          type="button"
          data-testid="scope-to-partial-none"
          onClick={() =>
            props.onChange({
              ...props.value,
              backupMode: "partial",
              selectedAgents: [],
              globalConfig: false,
              includeSkillPool: false,
              includeSecrets: true,
            })
          }
        >
          to-partial-no-agent
        </button>
      </div>
    );
  },
}));

vi.mock("./BackupProgress", () => ({
  default: function BackupProgressMock(props: {
    progress: number;
    progressMsg: string;
  }) {
    return (
      <div
        data-testid="backup-progress"
        data-progress={props.progress}
        data-msg={props.progressMsg}
      />
    );
  },
}));

vi.mock("antd", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("antd");
  const ModalStub = (props: {
    open?: boolean;
    title?: React.ReactNode;
    children?: React.ReactNode;
    footer?: React.ReactNode;
    okText?: React.ReactNode;
    cancelText?: React.ReactNode;
    okButtonProps?: { disabled?: boolean; style?: { display?: string } };
    onOk?: () => void;
    onCancel?: () => void;
    afterOpenChange?: (open: boolean) => void;
    closable?: boolean;
    maskClosable?: boolean;
  }) => {
    const {
      open,
      title,
      children,
      footer,
      okText,
      cancelText,
      okButtonProps,
      onOk,
      onCancel,
      closable,
      maskClosable,
    } = props;
    // Keep the latest handler without re-firing the effect when its identity
    // changes (see note 2).
    const handlerRef = React.useRef(props.afterOpenChange);
    handlerRef.current = props.afterOpenChange;
    const wasOpenRef = React.useRef(false);
    React.useEffect(() => {
      if (open && !wasOpenRef.current) {
        wasOpenRef.current = true;
        handlerRef.current?.(true);
      } else if (!open && wasOpenRef.current) {
        wasOpenRef.current = false;
        // Real antd also reports the close transition, so the stub does too.
        handlerRef.current?.(false);
      }
    }, [open]);
    if (!open) return null;
    const okHidden = okButtonProps?.style?.display === "none";
    return (
      <div
        data-testid="backup-modal"
        data-closable={String(closable)}
        data-mask-closable={String(maskClosable)}
      >
        <div data-testid="modal-title">{title}</div>
        {children}
        <div data-testid="modal-footer-slot">{footer}</div>
        {!okHidden && (
          <button
            type="button"
            data-testid="modal-ok"
            disabled={Boolean(okButtonProps?.disabled)}
            onClick={onOk}
          >
            {okText}
          </button>
        )}
        {/*
          Fires onOk even while the real OK button is disabled, so the guard
          inside the component's own handleOk can be exercised. A disabled
          button swallows click events, which would leave that guard (and the
          request it protects) permanently untested.
        */}
        <button type="button" data-testid="modal-ok-force" onClick={onOk}>
          force-ok
        </button>
        <button
          type="button"
          data-testid="modal-cancel"
          onClick={onCancel}
          disabled={onCancel === undefined}
        >
          {cancelText}
        </button>
      </div>
    );
  };
  return { ...actual, Modal: ModalStub };
});

import CreateBackupModal from "./CreateBackupModal";

function makeAgent(id: string, name: string): AgentSummary {
  return { id, name } as unknown as AgentSummary;
}

const AGENTS = [makeAgent("a1", "Agent One"), makeAgent("a2", "Agent Two")];

function renderModal(
  opts: {
    open?: boolean;
    agents?: AgentSummary[];
    resumeJob?: BackupJobSnapshot | null;
  } = {},
) {
  const onClose = vi.fn();
  const onSuccess = vi.fn();
  render(
    <CreateBackupModal
      open={opts.open ?? true}
      agents={opts.agents ?? AGENTS}
      onClose={onClose}
      onSuccess={onSuccess}
      resumeJob={opts.resumeJob ?? null}
    />,
  );
  return { onClose, onSuccess };
}

function nameInput(): HTMLInputElement {
  return screen.getByPlaceholderText("backup.namePlaceholder");
}

function describeInput(): HTMLTextAreaElement {
  return screen.getByPlaceholderText("backup.descriptionPlaceholder");
}

function scopeValue(): string {
  return screen.getByTestId("scope-value").textContent ?? "";
}

/** Drives the stubbed runner from outside act() so React does not warn. */
function setRunner(patch: Partial<RunnerSnapshot>) {
  act(() => {
    runnerStore.set(patch);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-03-04T05:06:07"));
  runnerStore.clear();
  runnerStore.start.mockClear();
  runnerStore.resume.mockClear();
  runnerStore.cancel.mockClear();
  runnerStore.reset.mockClear();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("CreateBackupModal - visibility", () => {
  it("renders nothing while closed", () => {
    renderModal({ open: false });
    expect(screen.queryByTestId("backup-modal")).toBeNull();
    expect(screen.queryByPlaceholderText("backup.namePlaceholder")).toBeNull();
  });

  it("shows the create title, both notices and the scope form when open", () => {
    renderModal();
    expect(screen.getByTestId("modal-title").textContent).toBe(
      "backup.createTitle",
    );
    expect(screen.getByText("backup.localModelsNotice")).toBeTruthy();
    expect(screen.getByText("backup.securityNotice")).toBeTruthy();
    expect(screen.getByTestId("scope-form")).toBeTruthy();
    expect(screen.queryByTestId("backup-progress")).toBeNull();
  });
});

describe("CreateBackupModal - fresh session on open", () => {
  it("prefills a timestamped name and clears the description", () => {
    renderModal();
    // The clock is pinned to 2026-03-04T05:06:07, so the generated label is
    // asserted exactly.
    expect(nameInput().value).toBe("Backup 2026-03-04 05:06");
    expect(describeInput().value).toBe("");
  });

  it("seeds the scope from every agent id and resets the runner", () => {
    renderModal();
    // defaultCreateScope: full mode, all agents selected, global config and
    // skill pool on, secrets off.
    expect(scopeValue()).toBe(
      JSON.stringify(["full", ["a1", "a2"], true, true, false]),
    );
    expect(screen.getByTestId("scope-agents").textContent).toBe("a1,a2");
    expect(runnerStore.reset).toHaveBeenCalledTimes(1);
    expect(runnerStore.resume).not.toHaveBeenCalled();
  });

  it("seeds an empty selection when there are no agents", () => {
    renderModal({ agents: [] });
    expect(scopeValue()).toBe(JSON.stringify(["full", [], true, true, false]));
    expect(screen.getByTestId("scope-agents").textContent).toBe("");
  });

  it("follows the edited scope value instead of the seeded default", () => {
    renderModal();
    fireEvent.click(screen.getByTestId("scope-to-partial"));
    expect(scopeValue()).toBe(
      JSON.stringify(["partial", ["a2"], false, false, true]),
    );
  });

  it("resumes the pending job instead of prefilling the form", () => {
    const resumeJob = { job_id: "job-9" } as unknown as BackupJobSnapshot;
    renderModal({ resumeJob });
    expect(runnerStore.resume).toHaveBeenCalledTimes(1);
    expect(runnerStore.resume).toHaveBeenCalledWith(resumeJob);
    // The resume branch returns early, so neither the name prefill nor the
    // runner reset happen on this open.
    expect(runnerStore.reset).not.toHaveBeenCalled();
    expect(nameInput().value).toBe("");
  });
});

describe("CreateBackupModal - confirm gating", () => {
  it("disables confirm while the prefilled name is blanked out", () => {
    renderModal();
    expect(screen.getByTestId("modal-ok")).not.toBeDisabled();
    fireEvent.change(nameInput(), { target: { value: "" } });
    expect(screen.getByTestId("modal-ok")).toBeDisabled();
  });

  it("keeps confirm disabled for a whitespace-only name", () => {
    renderModal();
    fireEvent.change(nameInput(), { target: { value: "    " } });
    expect(screen.getByTestId("modal-ok")).toBeDisabled();
    fireEvent.click(screen.getByTestId("modal-ok"));
    expect(runnerStore.start).not.toHaveBeenCalled();
  });

  it("re-enables confirm once a name is typed", () => {
    renderModal();
    fireEvent.change(nameInput(), { target: { value: "" } });
    expect(screen.getByTestId("modal-ok")).toBeDisabled();
    fireEvent.change(nameInput(), { target: { value: "Nightly" } });
    expect(screen.getByTestId("modal-ok")).not.toBeDisabled();
  });

  it("starts no backup if the confirm handler fires with a blank name", () => {
    renderModal();
    fireEvent.change(nameInput(), { target: { value: "   " } });
    // The real confirm button is disabled here, so this drives the component's
    // own guard directly: even if onOk ever fires with a blank name, no backup
    // request may leave the dialog.
    fireEvent.click(screen.getByTestId("modal-ok-force"));
    expect(runnerStore.start).not.toHaveBeenCalled();
    expect(nameInput().value).toBe("   ");
  });

  it("does not re-seed the form when the close transition is reported", () => {
    const { rerender } = render(
      <CreateBackupModal
        open
        agents={AGENTS}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        resumeJob={null}
      />,
    );
    expect(runnerStore.reset).toHaveBeenCalledTimes(1);
    fireEvent.change(nameInput(), { target: { value: "Typed by hand" } });

    // antd reports the finished close transition with visible=false; the
    // handler must ignore it rather than reset the form again.
    rerender(
      <CreateBackupModal
        open={false}
        agents={AGENTS}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        resumeJob={null}
      />,
    );
    expect(runnerStore.reset).toHaveBeenCalledTimes(1);
  });
});

describe("CreateBackupModal - request payload", () => {
  it("starts a full backup with the trimmed name and no description", () => {
    renderModal();
    fireEvent.change(nameInput(), { target: { value: "  Nightly  " } });
    fireEvent.change(describeInput(), { target: { value: "   " } });
    fireEvent.click(screen.getByTestId("modal-ok"));

    expect(runnerStore.start).toHaveBeenCalledTimes(1);
    const payload = runnerStore.start.mock.calls[0][0] as {
      name: string;
      description?: string;
      scope: Record<string, boolean>;
      agents: string[];
    };
    expect(payload.name).toBe("Nightly");
    // A whitespace-only description collapses to undefined, not "".
    expect(payload.description).toBeUndefined();
    // buildScope("full", ...) forces every flag on.
    expect(payload.scope).toEqual({
      include_agents: true,
      include_global_config: true,
      include_secrets: true,
      include_skill_pool: true,
    });
    expect(payload.agents).toEqual(["a1", "a2"]);
  });

  it("keeps a trimmed description when one is typed", () => {
    renderModal();
    fireEvent.change(describeInput(), {
      target: { value: " before release " },
    });
    fireEvent.click(screen.getByTestId("modal-ok"));
    const payload = runnerStore.start.mock.calls[0][0] as {
      description?: string;
    };
    expect(payload.description).toBe("before release");
  });

  it("narrows the scope and agent list in partial mode", () => {
    renderModal();
    fireEvent.click(screen.getByTestId("scope-to-partial"));
    fireEvent.click(screen.getByTestId("modal-ok"));

    const payload = runnerStore.start.mock.calls[0][0] as {
      scope: Record<string, boolean>;
      agents: string[];
    };
    expect(payload.scope).toEqual({
      include_agents: true,
      include_global_config: false,
      include_secrets: true,
      include_skill_pool: false,
    });
    expect(payload.agents).toEqual(["a2"]);
  });

  it("drops agents entirely when partial mode selects none", () => {
    renderModal();
    expect(screen.getByTestId("modal-ok")).not.toBeDisabled();
    fireEvent.change(nameInput(), { target: { value: "No agents" } });
    fireEvent.click(screen.getByTestId("scope-to-partial-none"));
    // With an empty selection buildScope reports include_agents false and an
    // empty agents list, even though secrets were toggled on. This is the one
    // reachable path where a confirmed backup carries no agent ids at all.
    fireEvent.click(screen.getByTestId("modal-ok"));
    const payload = runnerStore.start.mock.calls[0][0] as {
      scope: Record<string, boolean>;
      agents: string[];
    };
    expect(payload.scope.include_agents).toBe(false);
    expect(payload.agents).toEqual([]);
    expect(payload.scope.include_secrets).toBe(true);
  });
});

describe("CreateBackupModal - while a backup runs", () => {
  it("swaps the form for progress, hides confirm and offers a cancel", () => {
    const { onClose } = renderModal();
    setRunner({ progress: 42, progressMsg: "Archiving agents" });
    fireEvent.click(screen.getByTestId("modal-ok")); // start() flips loading

    const progress = screen.getByTestId("backup-progress");
    expect(progress.getAttribute("data-progress")).toBe("42");
    expect(progress.getAttribute("data-msg")).toBe("Archiving agents");
    expect(screen.queryByPlaceholderText("backup.namePlaceholder")).toBeNull();
    expect(screen.queryByTestId("scope-form")).toBeNull();
    // okButtonProps becomes display:none while running.
    expect(screen.queryByTestId("modal-ok")).toBeNull();
    const footerSlot = screen.getByTestId("modal-footer-slot");
    expect(within(footerSlot).getByText("common.cancel")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("refuses close requests while running", () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByTestId("modal-ok"));

    const modal = screen.getByTestId("backup-modal");
    expect(modal.getAttribute("data-closable")).toBe("false");
    expect(modal.getAttribute("data-mask-closable")).toBe("false");
    // onCancel is undefined while running, so the stub disables the button.
    const cancel = screen.getByTestId("modal-cancel");
    expect(cancel).toBeDisabled();
    fireEvent.click(cancel);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("hands the danger cancel button to the runner", () => {
    renderModal();
    fireEvent.click(screen.getByTestId("modal-ok"));

    const footerSlot = screen.getByTestId("modal-footer-slot");
    fireEvent.click(within(footerSlot).getByText("common.cancel"));
    expect(runnerStore.cancel).toHaveBeenCalledTimes(1);
  });
});

describe("CreateBackupModal - close request when idle", () => {
  it("passes the cancel button straight to onClose", () => {
    const { onClose } = renderModal();
    expect(screen.getByTestId("modal-cancel")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("modal-cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps the dialog closable and mask-closable", () => {
    renderModal();
    const modal = screen.getByTestId("backup-modal");
    expect(modal.getAttribute("data-closable")).toBe("true");
    expect(modal.getAttribute("data-mask-closable")).toBe("true");
  });
});
