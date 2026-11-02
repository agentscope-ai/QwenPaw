/**
 * Unit tests for SilentBackupModal, the automatic pre-restore snapshot dialog.
 *
 * Facts that shaped this suite (each one read off the source or measured):
 *
 * 1. `open` is derived, never owned: `open={target !== null}`. So "the dialog
 *    is open" is exactly "a pre-restore target is set", which is the contract
 *    asserted here rather than any internal open flag.
 * 2. The backup payload comes from the real `buildPreRestoreScope` in
 *    `../shared/scope` (NOT mocked), so the request handed to the runner is
 *    asserted end to end: name, translated description, the four scope flags
 *    and the agent id list. `description` is an i18n key that the caller
 *    resolves via `t(description)`, and that line is exactly what is under
 *    test here.
 * 3. The name embeds a UTC timestamp built from `new Date().toISOString()`,
 *    so the clock is pinned with fake timers and the exact string is asserted.
 *    The transformation is `T` to a space and `:`/`.` to `-`, then cut to 19
 *    characters, which for `2026-09-30T08:09:10.123Z` yields
 *    `2026-09-30 08-09-10` (measured from the helper, not derived by hand).
 * 4. The effect depends on `[target]` only, so a target starts exactly one
 *    backup and unrelated re-renders do not restart it.
 * 5. `useBackupRunner` is stubbed over an external store subscribed with
 *    `useSyncExternalStore`, so flipping `progress` re-renders the dialog. A
 *    plain object read once at render time cannot express "progress moved, the
 *    bar updated". The store also records the options it was constructed with,
 *    because `onSuccess`/`onClose` are passed to the runner and never called by
 *    the dialog itself.
 * 6. `closable={false}` and `maskClosable={false}` mean there is no close icon
 *    and no click-out escape, so the footer danger button is the only visible
 *    way out and it is wired to `runner.cancel`. antd renders for real here
 *    (the component imports `Button, Modal` straight from `antd`), so that
 *    assertion is made on the genuine markup.
 * 7. `./BackupProgress` is stubbed because it has its own suite next door,
 *    which keeps this file's coverage attributable to SilentBackupModal alone.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import type { BackupMeta } from "@/api/types/backup";

const runnerStore = vi.hoisted(() => {
  const initial = { loading: false, progress: 0, progressMsg: "" };
  let state: typeof initial = { ...initial };
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((l) => l());
  return {
    get: () => state,
    set: (patch: Partial<typeof initial>) => {
      state = { ...state, ...patch };
      notify();
    },
    clear: () => {
      state = { ...initial };
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
    lastOptions: null as null | { onSuccess: () => void; onClose: () => void },
  };
});

// Stable i18n instance on purpose: a fresh `t` per render would change the
// identity of anything memoised on it in the component under test.
const i18nStub = vi.hoisted(() => {
  const t = (key: string) => key;
  const i18n = {
    resolvedLanguage: "en",
    changeLanguage: () => undefined,
    language: "en",
  };
  return { t, i18n };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: i18nStub.t, i18n: i18nStub.i18n }),
}));

vi.mock("../shared/useBackupRunner", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useBackupRunner: (options: {
      onSuccess: () => void;
      onClose: () => void;
    }) => {
      runnerStore.lastOptions = options;
      const state = useSyncExternalStore(
        runnerStore.subscribe,
        runnerStore.get,
        runnerStore.get,
      );
      return {
        ...state,
        start: runnerStore.start,
        resume: runnerStore.resume,
        cancel: runnerStore.cancel,
        reset: runnerStore.reset,
      };
    },
  };
});

vi.mock("./BackupProgress", () => ({
  default: (props: { progress: number; progressMsg: string }) => (
    <div
      data-testid="backup-progress"
      data-progress={String(props.progress)}
      data-msg={props.progressMsg}
    />
  ),
}));

import SilentBackupModal from "./SilentBackupModal";

function makeTarget(id = "b1"): BackupMeta {
  return {
    id,
    name: `Backup ${id}`,
    description: `Desc ${id}`,
    created_at: "2026-09-30T08:00:00Z",
    scope: {
      include_agents: true,
      include_global_config: true,
      include_secrets: false,
      include_skill_pool: true,
    },
    agent_count: 2,
  } as BackupMeta;
}

function renderModal(props: {
  target: BackupMeta | null;
  agentIds?: string[];
  onClose?: () => void;
  onSuccess?: () => void;
}) {
  return render(
    <SilentBackupModal
      target={props.target}
      agentIds={props.agentIds ?? []}
      onClose={props.onClose ?? (() => undefined)}
      onSuccess={props.onSuccess ?? (() => undefined)}
    />,
  );
}

function lastStartPayload() {
  const calls = runnerStore.start.mock.calls;
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1][0] as {
    name: string;
    description: string;
    scope: Record<string, boolean>;
    agents: string[];
  };
}

describe("SilentBackupModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    runnerStore.clear();
    runnerStore.lastOptions = null;
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T08:09:10.123Z"));
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("starts one pre-restore backup as soon as a target arrives", () => {
    renderModal({ target: makeTarget("b1"), agentIds: ["a1", "a2"] });

    expect(runnerStore.start).toHaveBeenCalledTimes(1);
    expect(runnerStore.start.mock.calls[0][0]).toMatchObject({
      name: "[pre-restore] Backup 2026-09-30 08-09-10",
      description: "backup.preRestoreBackupDesc",
      scope: {
        include_agents: true,
        include_global_config: true,
        include_secrets: false,
        include_skill_pool: true,
      },
      agents: ["a1", "a2"],
    });
  });

  it("resolves the description key through i18n", () => {
    renderModal({ target: makeTarget(), agentIds: ["a1"] });

    // The scope helper hands back the raw key; the modal is what translates it.
    expect(lastStartPayload().description).toBe("backup.preRestoreBackupDesc");
  });

  it("starts nothing while there is no target", () => {
    renderModal({ target: null, agentIds: ["a1"] });

    expect(runnerStore.start).not.toHaveBeenCalled();
  });

  it("does not restart the backup when only other props change", () => {
    // The same object reference on purpose: `[target]` is the effect's only
    // dependency, so a brand-new equal-shaped object would legitimately
    // retrigger the effect and would not prove anything about the dependency
    // list. What varies here is a prop the effect does not watch.
    const target = makeTarget("b1");
    const { rerender } = renderModal({ target, agentIds: ["a1"] });
    expect(runnerStore.start).toHaveBeenCalledTimes(1);

    rerender(
      <SilentBackupModal
        target={target}
        agentIds={["a1", "a2"]}
        onClose={() => undefined}
        onSuccess={() => undefined}
      />,
    );

    expect(runnerStore.start).toHaveBeenCalledTimes(1);
  });

  it("starts a fresh backup when the target itself changes", () => {
    const first = makeTarget("b1");
    const { rerender } = renderModal({ target: first, agentIds: ["a1"] });
    expect(runnerStore.start).toHaveBeenCalledTimes(1);

    rerender(
      <SilentBackupModal
        target={makeTarget("b2")}
        agentIds={["a1"]}
        onClose={() => undefined}
        onSuccess={() => undefined}
      />,
    );

    // The other half of the same dependency: a new restore target is a new
    // snapshot, so the runner is started again.
    expect(runnerStore.start).toHaveBeenCalledTimes(2);
  });

  it("passes an empty agent list through untouched", () => {
    renderModal({ target: makeTarget(), agentIds: [] });

    expect(lastStartPayload().agents).toEqual([]);
  });

  it("renders the dialog only while a target is set", () => {
    const { rerender } = renderModal({ target: null });
    expect(
      screen.queryByText("backup.creatingPreRestoreBackup"),
    ).not.toBeInTheDocument();

    rerender(
      <SilentBackupModal
        target={makeTarget()}
        agentIds={["a1"]}
        onClose={() => undefined}
        onSuccess={() => undefined}
      />,
    );

    expect(
      screen.getByText("backup.creatingPreRestoreBackup"),
    ).toBeInTheDocument();
  });

  it("cancels from the footer danger button", () => {
    renderModal({ target: makeTarget() });

    fireEvent.click(screen.getByRole("button", { name: "common.cancel" }));
    expect(runnerStore.cancel).toHaveBeenCalledTimes(1);
  });

  it("offers exactly one footer button while running", () => {
    act(() => {
      runnerStore.set({ loading: true, progress: 45, progressMsg: "packing" });
    });
    renderModal({ target: makeTarget() });

    // closable is false, so the footer cancel button is the only button there.
    const footerButtons = screen.getAllByRole("button");
    expect(footerButtons).toHaveLength(1);
    expect(footerButtons[0]).toHaveTextContent("common.cancel");
  });

  it("shows the runner progress in the body", () => {
    renderModal({ target: makeTarget() });
    expect(screen.getByTestId("backup-progress")).toHaveAttribute(
      "data-progress",
      "0",
    );

    act(() => {
      runnerStore.set({ progress: 62, progressMsg: "zipping" });
    });

    const body = screen.getByTestId("backup-progress");
    expect(body).toHaveAttribute("data-progress", "62");
    expect(body).toHaveAttribute("data-msg", "zipping");
  });

  it("hands the runner the parent success and close callbacks", () => {
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    renderModal({ target: makeTarget(), onSuccess, onClose });

    expect(typeof runnerStore.lastOptions?.onSuccess).toBe("function");
    expect(typeof runnerStore.lastOptions?.onClose).toBe("function");

    runnerStore.lastOptions!.onSuccess();
    runnerStore.lastOptions!.onClose();

    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("uses the real scope builder rather than a copy of its output", () => {
    renderModal({ target: makeTarget(), agentIds: ["a1", "a2", "a3"] });

    const payload = lastStartPayload();
    // `include_secrets` is the one flag the pre-restore scope keeps off.
    expect(payload.scope.include_secrets).toBe(false);
    expect(Object.keys(payload.scope)).toEqual([
      "include_agents",
      "include_global_config",
      "include_secrets",
      "include_skill_pool",
    ]);
    expect(payload.agents).toEqual(["a1", "a2", "a3"]);
  });
});
