// @vitest-environment jsdom
/**
 * PreRestoreConfirmModal - step 1 of the restore flow. It asks whether the
 * user wants an automatic snapshot before their data gets overwritten, and it
 * has THREE outcomes, which is why it earns its own suite:
 *   cancel     -> abort entirely
 *   no backup  -> straight to RestoreBackupModal
 *   yes backup -> SilentBackupModal first, then RestoreBackupModal
 *
 * Rendered from one place, checked by grep before this suite was written:
 *   - `pages/Settings/Backups/index.tsx:26` (import) + `:142` (JSX), wired to
 *     `useRestoreFlow`'s `preRestoreConfirmTarget` / `cancelPreRestore` /
 *     `confirmRestoreWithoutBackup` / `confirmRestoreWithBackup`.
 *   `restore/useRestoreFlow.ts` also names it in its step-by-step doc comment
 *   (`:6`), and `restore/RestoreBackupModal.test.tsx` covers step 2. Nothing
 *   else mounts it, so it is not dead code.
 *
 * Visible contract under test:
 *
 *   1. `target` is the ONLY open switch: a null target renders NOTHING into
 *      the document - not a hidden dialog, not an empty shell. Probed: the
 *      container is 0 bytes and `queryByRole("dialog")` is null. That matters
 *      because the page keeps this modal mounted at all times, so "closed" has
 *      to mean "absent", otherwise a stale dialog would sit in the DOM behind
 *      the backups table;
 *   2. the footer is a THREE-button list in a fixed order - cancel, no, yes -
 *      and `yes` alone carries the primary style. The order is the order the
 *      user reads the decision in, so it is asserted positionally rather than
 *      by hunting for each label;
 *   3. every outcome hands the parent the SAME backup object it was given, by
 *      reference. The flow stores that object and later feeds it to
 *      SilentBackupModal / RestoreBackupModal, so a copy would silently break
 *      the chain;
 *   4. `cancel` is reachable two ways that are NOT the same prop: the footer
 *      cancel button and the dialog's own close control both land on
 *      `onCancel`. Pinned separately, because they are two DOM elements;
 *   5. the `target &&` guard inside the no/yes handlers is real: with no
 *      target there is no button to click at all (see 1), and re-opening with
 *      a different backup routes the new one - the handlers never close over a
 *      stale target;
 *   6. the dialog is `centered` and 520px wide, and the body is a single
 *      paragraph. Both are user-visible layout choices of this step (it is the
 *      "are you sure" gate, deliberately narrow);
 *   7. every visible string is an i18n key - the modal hard-codes no English.
 *
 * Harness notes (measured facts, not guesses):
 *
 * - antd renders for real here: the component imports `Button, Modal` straight
 *   from `antd`, and `vite.config.ts` does not alias antd (only
 *   `@agentscope-ai/design`, `@agentscope-ai/icons` and the two Tauri modules
 *   are). Probe `/tmp/b96_probe1.txt` gave the DOM truth used below: open ->
 *   4 buttons (index 0 is `.ant-modal-close`, 1..3 are the footer), the
 *   primary one carries `.ant-btn-primary`, `.ant-modal-centered` is present,
 *   and `.ant-modal` has `style="width: 520px;"`. Closed -> container
 *   `innerHTML.length === 0`.
 * - `react-i18next` IS mocked with `t` returning the key verbatim (and
 *   `key:JSON(opts)` when called with options), so every assertion pins the
 *   i18n key the product asks for. Keys were read back from
 *   `src/locales/en.json`, not typed from memory: `backup.preRestoreBackupTitle`
 *   / `...Content` / `...No` / `...Yes` / `common.cancel`.
 * - the shared design stub `src/test/design-mock.ts` is NOT involved: this
 *   component never imports `@agentscope-ai/design`.
 * - `cleanup()` runs after every case, so each `render` starts from an empty
 *   document and the "closed renders nothing" assertion cannot be satisfied by
 *   a leftover portal from a previous case.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, fireEvent, cleanup, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import type { BackupMeta } from "@/api/types/backup";
import PreRestoreConfirmModal from "./PreRestoreConfirmModal";

vi.mock("react-i18next", () => {
  // Built once per factory call so `t` keeps a stable identity across renders.
  const t = (key: string, opts?: Record<string, unknown>) =>
    opts ? `${key}:${JSON.stringify(opts)}` : key;
  return {
    useTranslation: () => ({
      t,
      i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
    }),
  };
});

/** antd's leave transition never finishes under jsdom (there is no rAF loop to
 *  run it), so a closing modal would stay caught in `ant-zoom-leave` forever.
 *  Disabling motion makes the closed state observable. Measured by probe
 *  `/tmp/b96_probe7.txt`: with motion on, `queryByRole("dialog")` is still
 *  non-null after close; with motion off it is null. The modal's own props are
 *  untouched - this changes the test environment, not the component. */
const noMotion = (node: React.ReactNode) => (
  <ConfigProvider theme={{ token: { motion: false } }}>{node}</ConfigProvider>
);

/** A backup row as the backups table hands it over. Field names come from
 *  `src/api/types/backup.ts:10` (BackupMeta), read back rather than recalled. */
const makeMeta = (over: Partial<BackupMeta> = {}): BackupMeta => ({
  id: "bk-2026-10-02",
  name: "Nightly snapshot",
  description: "auto",
  created_at: "2026-10-02T12:00:00.000Z",
  // BackupScope is four include_* booleans (`src/api/types/backup.ts:1`), read
  // back off the type - a `{ mode, agents }` shape was invented from memory and
  // tsc rejected it (TS2352), which is what pinned this fixture.
  scope: {
    include_agents: true,
    include_global_config: true,
    include_secrets: false,
    include_skill_pool: true,
  },
  agent_count: 3,
  ...over,
});

// Typed to the component's own prop signatures, following the precedent in
// `pages/Agent/Checkpoints/RestoreModal.test.tsx:154`. An untyped
// `ReturnType<typeof vi.fn>` does not satisfy `() => void` in this vitest
// version (tsc TS2322), and typing it this way keeps the payload assertions
// (`mock.calls[0][0]` is a BackupMeta) checked rather than `any`.
type Handlers = {
  onCancel: ReturnType<typeof vi.fn<() => void>>;
  onNoBackup: ReturnType<typeof vi.fn<(target: BackupMeta) => void>>;
  onYesBackup: ReturnType<typeof vi.fn<(target: BackupMeta) => void>>;
};

const setup = (target: BackupMeta | null) => {
  const h: Handlers = {
    onCancel: vi.fn(),
    onNoBackup: vi.fn(),
    onYesBackup: vi.fn(),
  };
  const view = render(<PreRestoreConfirmModal target={target} {...h} />);
  return { ...view, ...h };
};

/** The three footer buttons, in DOM order. Index 0 of `getAllByRole("button")`
 *  is antd's own `.ant-modal-close` control, so the footer starts at 1 - that
 *  offset was measured (`PROBE_OPEN_btn_count 4`, `PROBE_OPEN_footer_btn_count
 *  3`), not assumed. */
const footerButtons = (root: ParentNode) =>
  Array.from(root.querySelectorAll(".ant-modal-footer button"));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PreRestoreConfirmModal visibility", () => {
  it("renders nothing at all while target is null", () => {
    const { container, baseElement, queryByRole } = setup(null);

    // The page keeps this modal mounted permanently, so "closed" must mean
    // "absent from the document", not "hidden".
    expect(container.innerHTML).toBe("");
    expect(queryByRole("dialog")).toBeNull();
    expect(baseElement.querySelectorAll(".ant-modal-root").length).toBe(0);
    expect(baseElement.querySelectorAll(".ant-modal-wrap").length).toBe(0);
  });

  it("opens as a single centered 520px dialog once a target is set", () => {
    const { baseElement, getAllByRole } = setup(makeMeta());

    expect(getAllByRole("dialog")).toHaveLength(1);
    expect(baseElement.querySelectorAll(".ant-modal-centered").length).toBe(1);
    const modal = baseElement.querySelector(".ant-modal");
    expect(modal?.getAttribute("style")).toBe("width: 520px;");
  });

  it("stops being a dialog when the target goes back to null", () => {
    const h: Handlers = {
      onCancel: vi.fn(),
      onNoBackup: vi.fn(),
      onYesBackup: vi.fn(),
    };
    const { rerender, queryByRole, baseElement } = render(
      noMotion(<PreRestoreConfirmModal target={makeMeta()} {...h} />),
    );
    expect(queryByRole("dialog")).not.toBeNull();

    rerender(noMotion(<PreRestoreConfirmModal target={null} {...h} />));

    // Same mounted component, so this is the flow's own "user decided" path:
    // useRestoreFlow sets preRestoreConfirmTarget back to null on every branch.
    // NOTE the distinction measured by probe: a dialog that was never open
    // leaves NO DOM at all (the case above), while one that has been open keeps
    // antd's shell but loses `role="dialog"` and gets its wrapper hidden. What
    // the user sees is the same - no dialog on screen - so that is what is
    // pinned here, not "the element is gone from the tree".
    expect(queryByRole("dialog")).toBeNull();
    const wrap = baseElement.querySelector(".ant-modal-wrap");
    expect(wrap?.getAttribute("style")).toBe("display: none;");
    // And it is unreachable by the keyboard/AT for the same reason.
    expect(queryByRole("dialog", { hidden: true })).not.toBeNull();
    expect(baseElement.querySelectorAll(".ant-modal-wrap").length).toBe(1);
  });
});

describe("PreRestoreConfirmModal copy", () => {
  it("shows the title, the irreversibility paragraph and no other text", () => {
    const { baseElement } = setup(makeMeta());

    expect(baseElement.querySelector(".ant-modal-title")?.textContent).toBe(
      "backup.preRestoreBackupTitle",
    );
    const paragraphs = baseElement.querySelectorAll(".ant-modal-body p");
    expect(paragraphs).toHaveLength(1);
    expect(paragraphs[0].textContent).toBe("backup.preRestoreBackupContent");
    // The paragraph is the whole body: the metadata of the backup being
    // restored is deliberately NOT repeated here (that is RestoreBackupModal's
    // job), so the gate stays a yes/no question.
    expect(baseElement.querySelector(".ant-modal-body")?.textContent).toBe(
      "backup.preRestoreBackupContent",
    );
    expect(paragraphs[0].getAttribute("style")).toBe("line-height: 1.6;");
  });

  it("asks for every visible string through i18n keys", () => {
    const { baseElement } = setup(makeMeta());

    const labels = footerButtons(baseElement).map((b) => b.textContent);
    expect(labels).toEqual([
      "common.cancel",
      "backup.preRestoreBackupNo",
      "backup.preRestoreBackupYes",
    ]);

    // No hard-coded English anywhere in the dialog. The needles are the REAL
    // en.json translations (read back from `src/locales/en.json`), because the
    // i18n keys themselves contain those words - `backup.preRestoreBackupTitle`
    // would match a naive /restore/i and turn this assertion into a red herring.
    // That first attempt failing is exactly what pinned the needle set below.
    const rendered = baseElement.querySelector(".ant-modal")?.textContent ?? "";
    for (const english of [
      "Create Pre-Restore Backup",
      "The restore operation is irreversible.",
      "No, restore directly",
      "Yes, create backup first",
      "Cancel",
    ]) {
      expect(rendered).not.toContain(english);
    }
    // Positive control: the keys ARE there, so the loop above is not passing
    // because the modal rendered nothing.
    for (const key of [
      "backup.preRestoreBackupTitle",
      "backup.preRestoreBackupContent",
      "common.cancel",
    ]) {
      expect(rendered).toContain(key);
    }
  });
});

describe("PreRestoreConfirmModal outcomes", () => {
  it("routes the footer cancel button to onCancel and leaves the other two silent", () => {
    const { baseElement, onCancel, onNoBackup, onYesBackup } = setup(
      makeMeta(),
    );

    fireEvent.click(footerButtons(baseElement)[0]);

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onNoBackup).not.toHaveBeenCalled();
    expect(onYesBackup).not.toHaveBeenCalled();
  });

  it('routes "No, restore directly" to onNoBackup with the very same object', () => {
    const target = makeMeta();
    const { baseElement, onCancel, onNoBackup, onYesBackup } = setup(target);

    fireEvent.click(footerButtons(baseElement)[1]);

    expect(onNoBackup).toHaveBeenCalledTimes(1);
    // By reference, not by copy: useRestoreFlow stores this object and hands it
    // to RestoreBackupModal next.
    expect(onNoBackup.mock.calls[0][0]).toBe(target);
    expect(onCancel).not.toHaveBeenCalled();
    expect(onYesBackup).not.toHaveBeenCalled();
  });

  it('routes "Yes, create backup first" to onYesBackup with the very same object', () => {
    const target = makeMeta({ id: "bk-other", name: "Other" });
    const { baseElement, onCancel, onNoBackup, onYesBackup } = setup(target);

    fireEvent.click(footerButtons(baseElement)[2]);

    expect(onYesBackup).toHaveBeenCalledTimes(1);
    expect(onYesBackup.mock.calls[0][0]).toBe(target);
    expect(onCancel).not.toHaveBeenCalled();
    expect(onNoBackup).not.toHaveBeenCalled();
  });

  it("routes the dialog's own close control to onCancel too", () => {
    const { baseElement, onCancel, onNoBackup, onYesBackup } = setup(
      makeMeta(),
    );

    const close = baseElement.querySelector(".ant-modal-close");
    expect(close).not.toBeNull();
    fireEvent.click(close as HTMLElement);

    // A second, independent path into the same handler: the X control is not
    // the footer cancel button.
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onNoBackup).not.toHaveBeenCalled();
    expect(onYesBackup).not.toHaveBeenCalled();
  });

  it("marks only the yes branch as the primary action", () => {
    const { baseElement } = setup(makeMeta());

    const [cancel, no, yes] = footerButtons(baseElement);
    expect(yes.className).toContain("ant-btn-primary");
    expect(cancel.className).not.toContain("ant-btn-primary");
    expect(no.className).not.toContain("ant-btn-primary");
    // The safe-by-default choice is NOT the visually promoted one on purpose:
    // creating the snapshot first is the reversible path.
    expect(baseElement.querySelectorAll(".ant-btn-primary").length).toBe(1);
  });

  it("hands the new target over after the dialog is re-opened with a different backup", () => {
    const h: Handlers = {
      onCancel: vi.fn(),
      onNoBackup: vi.fn(),
      onYesBackup: vi.fn(),
    };
    const first = makeMeta({ id: "bk-first" });
    const second = makeMeta({ id: "bk-second" });
    const { rerender, baseElement } = render(
      <PreRestoreConfirmModal target={first} {...h} />,
    );

    rerender(<PreRestoreConfirmModal target={null} {...h} />);
    rerender(<PreRestoreConfirmModal target={second} {...h} />);
    fireEvent.click(footerButtons(baseElement)[2]);

    // Pins the `target &&` guard against closing over a stale value: the row
    // the user confirmed is the row currently on screen.
    expect(h.onYesBackup).toHaveBeenCalledTimes(1);
    expect(h.onYesBackup.mock.calls[0][0]).toBe(second);
    expect(h.onYesBackup.mock.calls[0][0].id).toBe("bk-second");
  });

  it("emits nothing but the callback - the modal never mutates the target", () => {
    const target = makeMeta();
    const snapshot = JSON.stringify(target);
    const { baseElement, onNoBackup } = setup(target);

    fireEvent.click(footerButtons(baseElement)[1]);

    expect(onNoBackup).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(target)).toBe(snapshot);
    // And it renders no extra controls beyond close + the three outcomes.
    expect(screen.getAllByRole("button")).toHaveLength(4);
  });
});
