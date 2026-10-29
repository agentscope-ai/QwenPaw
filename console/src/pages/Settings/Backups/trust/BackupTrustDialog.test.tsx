// @vitest-environment jsdom
/**
 * BackupTrustDialog - the shared "do you trust this archive?" gate that both
 * the import flow and the restore flow mount before the backend is allowed to
 * accept or sign an archive that does not verify against the local key.
 *
 * Rendered from two places, each checked by grep before this suite was written
 * (`grep -rn --include=*.ts --include=*.tsx BackupTrustDialog src | grep -v
 * "\.test\."`), so it is not dead code:
 *   - `pages/Settings/Backups/index.tsx:23` (import) + `:120` (JSX), driven by
 *     `import/useImportFlow.ts` (`trustFileName` / `trustMode` / `trustLoading`
 *     / `handleTrustConfirm` / `clearTrust`);
 *   - `pages/Settings/Backups/restore/RestoreBackupModal.tsx:35` (import) +
 *     `:582` (JSX), driven by that component's own `trustPrompt` state.
 * `trust/trustErrors.test.ts` covers the error-code -> mode mapping that feeds
 * the `mode` prop; this suite covers the dialog itself.
 *
 * Visible contract under test:
 *
 *   1. `open` is the only open switch, and the two closed shapes are NOT the
 *      same. A dialog that was never opened leaves the document empty (0 role
 *      =dialog, 0 modal wraps). A dialog that was opened and then closed keeps
 *      its shell but drops role =dialog and sets the wrap to display:none. Both
 *      were probed, and both matter: the two call sites keep this dialog
 *      mounted at all times, so "closed" has to mean "not interactable" even
 *      when a shell is still in the DOM;
 *   2. `mode` selects the wording of BOTH the title and the description, and
 *      the two modes are disjoint - legacy says the archive is older and will
 *      be signed before restore, foreign says it was signed elsewhere and that
 *      local security and MCP settings survive the restore. Asserted as whole
 *      i18n keys rather than as substrings, because a substring would also
 *      pass if the two modes were swapped by mistake;
 *   3. `backupName` is the Alert's message and falls back to a named i18n key
 *      when the caller has no file name yet (the restore flow always passes
 *      `backup.name`; the import flow passes `trustFileName ?? undefined`);
 *   4. the footer is exactly two buttons in a fixed order, cancel then
 *      confirm, and confirm alone carries the dangerous primary style. This is
 *      the user's read order for an irreversible decision, so it is pinned
 *      positionally;
 *   5. clicking confirm reaches `onConfirm` and clicking cancel reaches
 *      `onCancel`, and neither leaks into the other. Both call sites pass
 *      zero-argument functions, yet antd hands the click event through, so the
 *      arity is pinned as a fact of the current product (see the note below);
 *   6. the dialog's own close control and the mask are two separate escape
 *      hatches: the close control routes to `onCancel`, while the mask does
 *      NOT (the product never sets maskClosable, so antd's default applies and
 *      a stray click on the backdrop cannot dismiss a security prompt);
 *   7. the dialog is centered and 520px wide - a user-visible layout choice of
 *      a deliberately narrow "are you sure" gate;
 *   8. every visible string is an i18n key - the component hard-codes no
 *      English other than the `defaultValue` fallbacks it passes to `t`.
 *
 * Harness notes (measured facts, not guesses):
 *
 * - antd renders for real here: the component imports `Alert, Modal` straight
 *   from `antd`, and `vite.config.ts` does not alias antd (only
 *   `@agentscope-ai/design`, `@agentscope-ai/icons` and the two Tauri modules
 *   are aliased). The shared design stub `src/test/design-mock.ts` is not
 *   involved because this component never imports `@agentscope-ai/design`.
 * - `react-i18next` is mocked with `t` returning the key verbatim (and
 *   `key:JSON(opts)` when called with options), so every assertion pins the
 *   i18n key the product asks for together with the fallback text it ships.
 *   All five keys were read back from `src/locales/en.json:768-772` plus
 *   `common.confirm` / `common.cancel` at `:5-6`, not typed from memory.
 * - antd's leave transition never finishes under jsdom (there is no rAF loop to
 *   run it), so the open -> closed case runs inside `ConfigProvider` with
 *   `motion: false`. Measured: with motion on, `queryByRole("dialog")` is still
 *   non-null after close and the element stays in `ant-zoom-leave`. This
 *   changes the test environment only; the component's own props are untouched.
 * - DOM shapes quoted below came from probes run in this worktree, not from
 *   reading antd source: open -> 1 role =dialog, `.ant-modal` carries
 *   `style="width: 520px;"`, `.ant-modal-centered` present, footer has 2
 *   buttons (index 0 cancel, index 1 confirm, the latter carrying
 *   `.ant-btn-dangerous` and `.ant-btn-primary`), the Alert is
 *   `.ant-alert-warning.ant-alert-with-description` with an icon, and
 *   `getAllByRole("button")` returns 3 entries because index 0 is antd's own
 *   `.ant-modal-close` control.
 * - CRITICAL, NOT asserted deliberately: with `confirmLoading` set, clicking the
 *   cancel button or the close control did not reach `onCancel` in the probe
 *   (the native click listener on the very same element did fire, and
 *   `defaultPrevented` was false, while the React handler stayed silent). The
 *   mechanism is unconfirmed, so per the no-guessing rule this suite does not
 *   turn that observation into an expectation either way. `confirmLoading` is
 *   only asserted for what it visibly does: it puts the confirm button into the
 *   loading shape. Recorded for the team lead in the sprint progress file.
 * - `cleanup()` runs after every case, so each render starts from an empty
 *   document and the "never opened leaves nothing behind" assertion cannot be
 *   satisfied by a leftover portal from a previous case.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, fireEvent, cleanup, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import BackupTrustDialog from "./BackupTrustDialog";

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

afterEach(() => cleanup());

/** See the harness note above: motion has to be off for the closed state to be
 *  observable at all under jsdom. */
const noMotion = (node: React.ReactNode) => (
  <ConfigProvider theme={{ token: { motion: false } }}>{node}</ConfigProvider>
);

// Typed to the component's own prop signature, following the precedent in
// `pages/Agent/Checkpoints/RestoreModal.test.tsx:154`. An untyped
// `ReturnType<typeof vi.fn>` does not satisfy `() => void` under vitest
// 4.1.10 (tsc reports TS2322).
type Handlers = {
  onConfirm: ReturnType<typeof vi.fn<() => void>>;
  onCancel: ReturnType<typeof vi.fn<() => void>>;
};

type Mode = "foreign" | "legacy";

const setup = (
  over: Partial<React.ComponentProps<typeof BackupTrustDialog>> = {},
) => {
  const h: Handlers = { onConfirm: vi.fn(), onCancel: vi.fn() };
  const view = render(
    noMotion(<BackupTrustDialog open mode="foreign" {...h} {...over} />),
  );
  return { ...view, ...h };
};

/** The two footer buttons in DOM order: [cancel, confirm]. Probed, not assumed;
 *  `getAllByRole("button")[0]` is antd's own close control, which is why this
 *  helper scopes to `.ant-modal-footer`. */
const footerButtons = (): HTMLButtonElement[] =>
  Array.from(
    document.querySelectorAll<HTMLButtonElement>(".ant-modal-footer button"),
  );

const titleText = () => document.querySelector(".ant-modal-title")?.textContent;
const alertMessage = () =>
  document.querySelector(".ant-alert-message")?.textContent;
const alertDescription = () =>
  document.querySelector(".ant-alert-description")?.textContent;

describe("BackupTrustDialog - open switch", () => {
  it("leaves the document empty when it was never opened", () => {
    render(
      <BackupTrustDialog
        open={false}
        mode="foreign"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    // Probed: 0 dialogs, 0 modal wraps, body innerHTML 11 bytes. A hidden shell
    // would be enough to fail this, which is the point - both call sites keep
    // the dialog mounted next to the backups table.
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.querySelectorAll(".ant-modal-wrap").length).toBe(0);
    expect(document.querySelector(".ant-modal")).toBeNull();
  });

  it("keeps the shell but drops the dialog role once it has been closed", () => {
    const { rerender } = render(
      noMotion(
        <BackupTrustDialog
          open
          mode="legacy"
          backupName="b.zip"
          onConfirm={() => {}}
          onCancel={() => {}}
        />,
      ),
    );
    expect(screen.queryByRole("dialog")).not.toBeNull();

    rerender(
      noMotion(
        <BackupTrustDialog
          open={false}
          mode="legacy"
          backupName="b.zip"
          onConfirm={() => {}}
          onCancel={() => {}}
        />,
      ),
    );

    // Probed: after close the wrap is still in the DOM with display:none and
    // role =dialog is gone. This is a different shape from "never opened", so
    // the two cases are pinned separately rather than sharing one assertion.
    expect(screen.queryByRole("dialog")).toBeNull();
    const wrap = document.querySelector<HTMLElement>(".ant-modal-wrap");
    expect(wrap).not.toBeNull();
    expect(getComputedStyle(wrap as HTMLElement).display).toBe("none");
  });
});

describe("BackupTrustDialog - mode wording", () => {
  it("asks about a foreign archive when mode is foreign", () => {
    setup({ mode: "foreign" });
    expect(titleText()).toBe(
      'backup.trustForeignTitle:{"defaultValue":"Trust this backup?"}',
    );
    expect(alertDescription()).toBe(
      'backup.trustForeignDesc:{"defaultValue":"This backup was not signed by ' +
        "this instance. Only continue if you trust the source; local security " +
        'and MCP settings will be preserved by default when restored."}',
    );
  });

  it("asks about a legacy archive when mode is legacy", () => {
    setup({ mode: "legacy" });
    expect(titleText()).toBe(
      'backup.trustLegacyTitle:{"defaultValue":"Trust legacy backup?"}',
    );
    expect(alertDescription()).toBe(
      'backup.trustLegacyDesc:{"defaultValue":"This older backup has no local ' +
        "signature. Only continue if you trust where it came from; this " +
        'instance will sign it before restore."}',
    );
  });

  it("never mixes the two modes' wording", () => {
    // Guard against a swapped ternary: in foreign mode neither legacy key may
    // appear anywhere in the dialog, and vice versa. Whole-key equality above
    // would also catch a swap, but this pins the absence explicitly so a
    // partial swap (title fixed, description not) cannot slip through.
    setup({ mode: "foreign" });
    const foreign =
      document.querySelector(".ant-modal-root")?.textContent ?? "";
    expect(foreign).not.toContain("backup.trustLegacyTitle");
    expect(foreign).not.toContain("backup.trustLegacyDesc");
    cleanup();

    setup({ mode: "legacy" });
    const legacy = document.querySelector(".ant-modal-root")?.textContent ?? "";
    expect(legacy).not.toContain("backup.trustForeignTitle");
    expect(legacy).not.toContain("backup.trustForeignDesc");
  });

  it("renders a warning alert with an icon for both modes", () => {
    for (const mode of ["foreign", "legacy"] as Mode[]) {
      setup({ mode });
      const alert = document.querySelector(".ant-alert");
      expect(alert?.className).toContain("ant-alert-warning");
      expect(alert?.className).toContain("ant-alert-with-description");
      expect(alert?.querySelector(".ant-alert-icon")).not.toBeNull();
      // Exposed to assistive tech as an alert, so a screen reader announces the
      // warning rather than reading it as plain body text.
      expect(screen.queryByRole("alert")).not.toBeNull();
      cleanup();
    }
  });
});

describe("BackupTrustDialog - archive name", () => {
  it("shows the caller's archive name as the alert message", () => {
    setup({ backupName: "nightly-2026-10-02.zip" });
    expect(alertMessage()).toBe("nightly-2026-10-02.zip");
  });

  it("falls back to the unknown-name key when no name is given", () => {
    setup();
    expect(alertMessage()).toBe(
      'backup.unknownBackupName:{"defaultValue":"Backup archive"}',
    );
  });

  it("treats an empty name as missing and uses the fallback", () => {
    // `backupName || t(...)` means an empty string takes the fallback branch,
    // which is what the import flow produces before a file is picked.
    setup({ backupName: "" });
    expect(alertMessage()).toBe(
      'backup.unknownBackupName:{"defaultValue":"Backup archive"}',
    );
  });
});

describe("BackupTrustDialog - footer", () => {
  it("offers exactly cancel then confirm, and only confirm looks dangerous", () => {
    setup();
    const [cancel, confirm] = footerButtons();
    expect(footerButtons().length).toBe(2);
    expect(cancel.textContent).toBe("common.cancel");
    expect(confirm.textContent).toBe("common.confirm");
    // okButtonProps={{ danger: true }} is the product telling the user this is
    // the destructive choice, so the style class is part of the contract.
    expect(confirm.className).toContain("ant-btn-dangerous");
    expect(confirm.className).toContain("ant-btn-primary");
    expect(cancel.className).not.toContain("ant-btn-dangerous");
    expect(cancel.className).not.toContain("ant-btn-primary");
  });

  it("is centered and 520px wide", () => {
    setup();
    expect(document.querySelector(".ant-modal-centered")).not.toBeNull();
    const modal = document.querySelector<HTMLElement>(".ant-modal");
    expect(modal?.getAttribute("style")).toContain("width: 520px");
  });

  it("puts the confirm button into the loading shape while confirming", () => {
    setup({ confirmLoading: true });
    const [, confirm] = footerButtons();
    expect(confirm.className).toContain("ant-btn-loading");
    expect(document.querySelectorAll(".ant-btn-loading-icon").length).toBe(1);
    cleanup();

    setup({ confirmLoading: false });
    const [, idle] = footerButtons();
    expect(idle.className).not.toContain("ant-btn-loading");
    expect(document.querySelectorAll(".ant-btn-loading-icon").length).toBe(0);
  });
});

describe("BackupTrustDialog - decisions", () => {
  it("routes the confirm button to onConfirm and leaves onCancel alone", () => {
    const { onConfirm, onCancel } = setup();
    fireEvent.click(footerButtons()[1]);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("routes the cancel button to onCancel and leaves onConfirm alone", () => {
    const { onConfirm, onCancel } = setup();
    fireEvent.click(footerButtons()[0]);
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("routes the dialog's own close control to onCancel", () => {
    // A third escape hatch, and a separate DOM element from the footer cancel
    // button, so it is pinned on its own.
    const { onConfirm, onCancel } = setup();
    const close = document.querySelector<HTMLElement>(".ant-modal-close");
    expect(close).not.toBeNull();
    fireEvent.click(close as HTMLElement);
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("does not dismiss on a stray backdrop click", () => {
    // The product never sets maskClosable, so a security prompt cannot be waved
    // away by clicking outside it. Probed: mask click left onCancel untouched.
    const { onConfirm, onCancel } = setup();
    const mask = document.querySelector<HTMLElement>(".ant-modal-mask");
    expect(mask).not.toBeNull();
    fireEvent.click(mask as HTMLElement);
    expect(onCancel).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("counts repeated confirms rather than debouncing them", () => {
    // The dialog stays open until the parent flips `open`, so a second click is
    // a second call. Both call sites guard that with their own loading flag.
    const { onConfirm } = setup();
    fireEvent.click(footerButtons()[1]);
    fireEvent.click(footerButtons()[1]);
    expect(onConfirm).toHaveBeenCalledTimes(2);
  });

  it("hands the click event through even though both call sites take no argument", () => {
    // Product fact, measured: the props type is `onConfirm: () => void` and both
    // real call sites (`useImportFlow.ts:84` and `RestoreBackupModal.tsx:300`)
    // are zero-argument async functions, yet antd passes the click event to the
    // handler. Harmless today because every caller ignores arguments; pinned so
    // that a future caller which starts reading `event` cannot silently change
    // what this dialog hands over.
    const { onConfirm, onCancel } = setup();
    fireEvent.click(footerButtons()[1]);
    expect(onConfirm.mock.calls[0].length).toBe(1);
    fireEvent.click(footerButtons()[0]);
    expect(onCancel.mock.calls[0].length).toBe(1);
  });

  it("keeps answering after the mode and name change underneath it", () => {
    // The restore flow re-renders this dialog while it stays open (trustPrompt
    // is set per row), so the handlers must not close over a stale mode.
    const { onConfirm, rerender } = setup({
      mode: "foreign",
      backupName: "a.zip",
    });
    rerender(
      noMotion(
        <BackupTrustDialog
          open
          mode="legacy"
          backupName="b.zip"
          onConfirm={onConfirm}
          onCancel={() => {}}
        />,
      ),
    );
    expect(titleText()).toBe(
      'backup.trustLegacyTitle:{"defaultValue":"Trust legacy backup?"}',
    );
    expect(alertMessage()).toBe("b.zip");
    fireEvent.click(footerButtons()[1]);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
