// @vitest-environment jsdom
/**
 * ImportConflictModal - the HTTP 409 branch of "import a backup zip". The zip's
 * ID already exists in the store, so the user is shown the EXISTING backup's
 * metadata and asked to overwrite or walk away.
 *
 * Rendered from one place, checked by grep before this suite was written:
 *   - `pages/Settings/Backups/index.tsx:21` (import) + `:115` (JSX), wired to
 *     `useImportFlow`'s `conflictMeta` / `handleConflictChoice` /
 *     `clearConflict`.
 *   `import/useImportFlow.ts:48` is where the 409 is turned into
 *   `setConflictMeta(conflict.existing)` and `:63` is the overwrite retry, so
 *   this modal is the only thing standing between a 409 and a destructive
 *   re-upload. Nothing else mounts it, so it is not dead code.
 *
 * Visible contract under test:
 *
 *   1. `conflictMeta` is the ONLY open switch, and null renders NOTHING into the
 *      document. The page keeps this modal mounted permanently, so "closed" has
 *      to mean "absent", otherwise a leftover 409 dialog would sit behind the
 *      backups table;
 *   2. the body carries the EXISTING backup's identity - name, ID and creation
 *      time - because "overwrite" is only a safe choice if the user can tell
 *      which backup is about to be replaced. All three fields are pinned, plus
 *      the fact that the ID is set in monospace (it is the one value a user is
 *      expected to read character by character);
 *   3. the metadata block is gated on `conflictMeta &&`, so it is the same
 *      condition that opens the dialog - asserted through the open/closed pair
 *      rather than by finding a third state;
 *   4. `onChoice` takes NO argument: the pending conflict token lives in
 *      `useImportFlow`'s ref, so the modal must not try to route the backup
 *      back. That is asserted on the call itself, because a future refactor
 *      that started passing the target would be silently ignored by the parent;
 *   5. two buttons only, in a fixed order, and the destructive one is the one
 *      carrying both `primary` and `dangerous` - antd's red-button treatment.
 *      Cancel is reachable two ways that are NOT the same prop: the footer
 *      button and the dialog's own close control;
 *   6. `created_at` goes through dayjs with an explicit format, so what the
 *      user sees is `YYYY-MM-DD HH:mm:ss` in THEIR clock, not the raw ISO
 *      string from the API. Pinned with a fixture whose formatted value was
 *      probed under two different TZ settings (Asia/Shanghai and
 *      America/New_York) so the assertion cannot be timezone-fragile;
 *   7. every visible string is an i18n key - the modal hard-codes no English,
 *      with the single deliberate exception of the literal label `ID:`, which
 *      the component writes out itself (asserted as such, so the exception is
 *      documented rather than discovered later).
 *
 * Harness notes (measured facts, not guesses):
 *
 * - antd renders for real here (`Button, Modal` straight from `antd`;
 *   `vite.config.ts` does not alias antd). Probe `/tmp/b96_probe1.txt` gave:
 *   open -> 3 buttons (index 0 = `.ant-modal-close`, 1..2 = footer), the
 *   replace one carries `ant-btn-primary ant-btn-dangerous`, and
 *   `.ant-btn-dangerous` count is exactly 1. Closed after having been open ->
 *   the shell stays but `role="dialog"` is dropped and the wrapper gets
 *   `display: none` (`/tmp/b96_probe8.txt`). Never opened -> container is
 *   0 bytes.
 * - antd's leave transition never finishes under jsdom (no rAF loop), so the
 *   open -> closed case runs inside `ConfigProvider` with `motion: false`.
 *   Probed: without it `queryByRole("dialog")` stays non-null after close.
 * - `react-i18next` IS mocked with `t` returning the key verbatim, so
 *   assertions pin the i18n key the product asks for. Keys read back from
 *   `src/locales/en.json`: `backup.importConflictTitle` / `...Desc` /
 *   `backup.importReplace` / `backup.name` / `backup.createdAt` /
 *   `common.cancel`.
 * - the shared design stub `src/test/design-mock.ts` is NOT involved: this
 *   component never imports `@agentscope-ai/design`.
 * - dayjs is NOT mocked. It is the product's own formatting dependency, and
 *   mocking it would make assertion 6 tautological.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, fireEvent, cleanup } from "@testing-library/react";
import { ConfigProvider } from "antd";
import type { BackupMeta } from "@/api/types/backup";
import ImportConflictModal from "./ImportConflictModal";

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

/** See the harness notes: motion off is what makes "closed" observable under
 *  jsdom. It changes the test environment, not the component's props. */
const noMotion = (node: React.ReactNode) => (
  <ConfigProvider theme={{ token: { motion: false } }}>{node}</ConfigProvider>
);

/** A conflicting backup as `useImportFlow` stores it (`conflict.existing`).
 *  Field names read back from `src/api/types/backup.ts:10`. `created_at` is a
 *  LOCAL naive timestamp on purpose: probed under TZ=Asia/Shanghai and
 *  TZ=America/New_York, dayjs formats it to the same string in both, so this
 *  assertion does not depend on the machine's clock. A `Z`-suffixed instant was
 *  deliberately NOT used - it formats differently per TZ. */
const makeMeta = (over: Partial<BackupMeta> = {}): BackupMeta => ({
  id: "bk-2026-10-02",
  name: "Nightly snapshot",
  description: "auto",
  created_at: "2026-03-04T05:06:07",
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
// version (tsc TS2322). `onChoice` really takes no argument - that is asserted
// below as part of the contract.
type Handlers = {
  onChoice: ReturnType<typeof vi.fn<() => void>>;
  onCancel: ReturnType<typeof vi.fn<() => void>>;
};

const setup = (conflictMeta: BackupMeta | null) => {
  const h: Handlers = { onChoice: vi.fn(), onCancel: vi.fn() };
  const view = render(
    <ImportConflictModal conflictMeta={conflictMeta} {...h} />,
  );
  return { ...view, ...h };
};

/** Footer buttons in DOM order. Index 0 of `getAllByRole("button")` is antd's
 *  own close control (`PROBE_IC_btn_count 3` with 2 footer buttons). */
const footerButtons = (root: ParentNode) =>
  Array.from(root.querySelectorAll(".ant-modal-footer button"));

const bodyText = (root: ParentNode) =>
  root.querySelector(".ant-modal-body")?.textContent ?? "";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ImportConflictModal visibility", () => {
  it("renders nothing at all while there is no conflict", () => {
    const { container, baseElement, queryByRole } = setup(null);

    // The page keeps this modal mounted permanently, so "closed" must mean
    // "absent from the document", not "hidden".
    expect(container.innerHTML).toBe("");
    expect(queryByRole("dialog")).toBeNull();
    expect(baseElement.querySelectorAll(".ant-modal-root").length).toBe(0);
  });

  it("opens as a single dialog once a conflict is reported", () => {
    const { baseElement, getAllByRole } = setup(makeMeta());

    expect(getAllByRole("dialog")).toHaveLength(1);
    expect(baseElement.querySelector(".ant-modal-title")?.textContent).toBe(
      "backup.importConflictTitle",
    );
  });

  it("stops being a dialog when the conflict is cleared", () => {
    const h: Handlers = { onChoice: vi.fn(), onCancel: vi.fn() };
    const { rerender, queryByRole, baseElement } = render(
      noMotion(<ImportConflictModal conflictMeta={makeMeta()} {...h} />),
    );
    expect(queryByRole("dialog")).not.toBeNull();

    rerender(noMotion(<ImportConflictModal conflictMeta={null} {...h} />));

    // useImportFlow's clearConflict() / handleConflictChoice() both null the
    // meta, so this is the flow's own "user decided" path. antd keeps the shell
    // but drops the role and hides the wrapper - measured, not assumed.
    expect(queryByRole("dialog")).toBeNull();
    expect(
      baseElement.querySelector(".ant-modal-wrap")?.getAttribute("style"),
    ).toBe("display: none;");
  });
});

describe("ImportConflictModal conflicting backup identity", () => {
  it("shows the existing backup's name, ID and creation time", () => {
    const { baseElement } = setup(
      makeMeta({
        id: "bk-conflicting",
        name: "Weekly archive",
        created_at: "2026-03-04T05:06:07",
      }),
    );

    const text = bodyText(baseElement);
    expect(text).toContain("Weekly archive");
    expect(text).toContain("bk-conflicting");
    // dayjs with the component's own explicit format, in the runner's clock.
    // Value probed under two timezones (see makeMeta's note).
    expect(text).toContain("2026-03-04 05:06:07");
    // The raw ISO string must NOT leak: that is the whole point of formatting.
    expect(text).not.toContain("2026-03-04T05:06:07");
  });

  it("labels the three fields with their i18n keys and leaves ID hard-coded", () => {
    const { baseElement } = setup(makeMeta());

    const labels = Array.from(
      baseElement.querySelectorAll(".ant-modal-body strong"),
    ).map((s) => s.textContent);
    // Read back off the probe, in source order.
    expect(labels).toEqual(["backup.name:", "ID:", "backup.createdAt:"]);
  });

  it("sets the ID in monospace so it can be read character by character", () => {
    const { baseElement } = setup(makeMeta({ id: "bk-mono-check" }));

    const mono = baseElement.querySelector("span[style*='monospace']");
    expect(mono?.textContent).toBe("bk-mono-check");
    expect(mono?.getAttribute("style")).toContain("font-size: 12px");
    // Exactly one monospaced value: only the ID is treated as machine text.
    expect(
      baseElement.querySelectorAll("span[style*='monospace']").length,
    ).toBe(1);
  });

  it("explains what happened before asking for the decision", () => {
    const { baseElement } = setup(makeMeta());

    // The description is the first thing in the body, ahead of the metadata.
    expect(bodyText(baseElement).startsWith("backup.importConflictDesc")).toBe(
      true,
    );
    const paragraph = baseElement.querySelector(".ant-modal-body p");
    expect(paragraph?.textContent).toBe("backup.importConflictDesc");
  });

  it("renders no metadata block at all when there is no conflict", () => {
    const { baseElement } = setup(null);

    // The `conflictMeta &&` gate: with no conflict there is no dialog and hence
    // no name/ID/time shown anywhere in the document.
    expect(baseElement.textContent).toBe("");
  });
});

describe("ImportConflictModal outcomes", () => {
  it("routes the overwrite button to onChoice with no argument", () => {
    const { baseElement, onChoice, onCancel } = setup(makeMeta());

    fireEvent.click(footerButtons(baseElement)[1]);

    expect(onChoice).toHaveBeenCalledTimes(1);
    // The pending conflict token lives in useImportFlow's ref, so the modal
    // must not try to route the backup back. A future refactor that started
    // passing it would be silently ignored by the parent - pinned here.
    expect(onChoice.mock.calls[0]).toEqual([]);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("routes the footer cancel button to onCancel and leaves overwrite silent", () => {
    const { baseElement, onChoice, onCancel } = setup(makeMeta());

    fireEvent.click(footerButtons(baseElement)[0]);

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onChoice).not.toHaveBeenCalled();
  });

  it("routes the dialog's own close control to onCancel too", () => {
    const { baseElement, onChoice, onCancel } = setup(makeMeta());

    const close = baseElement.querySelector(".ant-modal-close");
    expect(close).not.toBeNull();
    fireEvent.click(close as HTMLElement);

    // A second, independent path into the same handler: the X control is not
    // the footer cancel button.
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onChoice).not.toHaveBeenCalled();
  });

  it("marks the overwrite button destructive and the cancel button not", () => {
    const { baseElement } = setup(makeMeta());

    const [cancel, replace] = footerButtons(baseElement);
    expect(replace.textContent).toBe("backup.importReplace");
    expect(cancel.textContent).toBe("common.cancel");
    expect(replace.className).toContain("ant-btn-dangerous");
    expect(replace.className).toContain("ant-btn-primary");
    expect(cancel.className).not.toContain("ant-btn-dangerous");
    // Exactly one destructive control in the dialog.
    expect(baseElement.querySelectorAll(".ant-btn-dangerous").length).toBe(1);
    expect(footerButtons(baseElement)).toHaveLength(2);
  });

  it("hands over the new conflict after the dialog is re-opened with a different backup", () => {
    const h: Handlers = { onChoice: vi.fn(), onCancel: vi.fn() };
    const first = makeMeta({ id: "bk-first", name: "First" });
    const second = makeMeta({ id: "bk-second", name: "Second" });
    const { rerender, baseElement } = render(
      <ImportConflictModal conflictMeta={first} {...h} />,
    );

    rerender(<ImportConflictModal conflictMeta={null} {...h} />);
    rerender(<ImportConflictModal conflictMeta={second} {...h} />);

    // The user must be looking at the backup that is actually about to be
    // overwritten - the two conflicts arrive from two separate uploads.
    expect(bodyText(baseElement)).toContain("bk-second");
    expect(bodyText(baseElement)).not.toContain("bk-first");
    fireEvent.click(footerButtons(baseElement)[1]);
    expect(h.onChoice).toHaveBeenCalledTimes(1);
    expect(h.onChoice.mock.calls[0]).toEqual([]);
  });

  it("never mutates the conflicting backup it was given", () => {
    const meta = makeMeta();
    const snapshot = JSON.stringify(meta);
    const { baseElement, onChoice } = setup(meta);

    fireEvent.click(footerButtons(baseElement)[1]);

    expect(onChoice).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(meta)).toBe(snapshot);
  });

  it("asks for every visible string through i18n keys except the ID label", () => {
    const { baseElement } = setup(makeMeta());

    const rendered = baseElement.querySelector(".ant-modal")?.textContent ?? "";
    // Needles are the REAL en.json translations (read back from
    // `src/locales/en.json`), because the i18n keys themselves contain those
    // words - a naive /overwrite|cancel/i would match
    // `backup.importReplace`'s neighbours and turn this into a red herring.
    for (const english of [
      "Backup Already Exists",
      "A backup with the same ID already exists.",
      "Overwrite",
      "Cancel",
      "Name",
      "Created",
    ]) {
      expect(rendered).not.toContain(english);
    }
    // Positive control, so the loop above cannot pass on an empty dialog.
    for (const key of [
      "backup.importConflictTitle",
      "backup.importConflictDesc",
      "backup.importReplace",
      "backup.name:",
      "backup.createdAt:",
      "common.cancel",
    ]) {
      expect(rendered).toContain(key);
    }
    // The one documented exception: `ID:` is written by the component itself.
    expect(rendered).toContain("ID:");
  });
});
