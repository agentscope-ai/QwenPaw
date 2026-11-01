/**
 * Unit tests for Invitations, the hub-governance invite-batch page. It loads
 * three endpoints in parallel (invite batches, the model directory and the hub
 * settings), renders one card per batch with a three-way status tag, revokes a
 * batch behind an antd confirm dialog, creates a new batch through a form that
 * embeds BudgetEditor, and finally shows the issued codes with a download
 * button.
 *
 * Harness details that are load bearing for the assertions below:
 *
 * 1. The component calls `App.useApp()`, so it must render inside antd's
 *    `<App>`; otherwise `message` and `modal` are undefined and both the load
 *    failure path and the revoke path throw.
 * 2. antd drives open/close through CSS motion, and jsdom never fires
 *    `animationend`. A closed Modal therefore keeps its wrap in the document
 *    forever with `ant-zoom-leave` still on the `.ant-modal` element, and
 *    `destroyOnHidden` never gets to destroy anything. Filtering on
 *    `.ant-modal-wrap` visibility, or on body text, would match closed dialogs.
 *    `liveModals()` filters on the motion class instead, which is what actually
 *    tracks the open dialog. The same holds for Select dropdowns
 *    (`liveDropdown()`) and for `modal.confirm` nodes (`liveConfirm()`).
 * 3. `modal.confirm` appends a brand new node on every call and the cancelled
 *    one stays behind, so two dialogs can carry the same title at once. The
 *    confirm helper therefore selects by motion class first and only then by
 *    title, and asserts a single live match.
 * 4. Expiry is decided by `new Date(batch.expires_at).getTime() < Date.now()`.
 *    The fixtures are built relative to the real clock rather than with fake
 *    timers, because fake timers also freeze the timers antd's motion depends
 *    on.
 * 5. BudgetEditor is deliberately NOT mocked: the mode/amount pair it renders
 *    is exactly what the create payload asserts on (`inherit_budget` and
 *    `token_limit`), and stubbing it would turn those assertions into
 *    assertions about the stub.
 * 6. `governanceErrorMessage` and `createClientMessageId` are deliberately NOT
 *    mocked either: the error assertions check the translated key the real
 *    mapping produces, and the request id is asserted by shape because the real
 *    generator is random.
 *
 * Inside the customization `<details>` there are exactly two comboboxes, in
 * source order: index 0 is the additional-grants Select, index 1 is
 * BudgetEditor's mode Select.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, waitFor, fireEvent, act } from "@testing-library/react";
import { App } from "antd";

import type { InviteBatch } from "../../../api/modules/hubGovernance";

const governanceRequest = vi.hoisted(() => vi.fn());
const getSettings = vi.hoisted(() => vi.fn());

/**
 * `t` and `i18n` must keep a stable identity across renders. The page wraps its
 * loader in `useCallback(..., [message, t])` and its effect in `[load]`, so a
 * fresh `t` on every render would recreate the loader, re-run the effect and
 * loop forever. The real `react-i18next` returns a stable `t`, so this mirrors
 * the production contract rather than working around a product bug.
 */
const i18nStub = vi.hoisted(() => {
  const stableT = (key: string, opts?: Record<string, unknown>) =>
    opts ? `${key}:${JSON.stringify(opts)}` : key;
  const stableI18n = { language: "en-US" };
  return { stableT, stableI18n };
});

vi.mock("../../../api/modules/hubGovernance", () => ({ governanceRequest }));
vi.mock("../../../api/modules/hub", () => ({ hubApi: { getSettings } }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: i18nStub.stableT, i18n: i18nStub.stableI18n }),
}));

import Invitations from "./Invitations";
import styles from "./governance.module.less";

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

const DAY = 24 * 60 * 60 * 1000;

/** An ISO timestamp `offsetMs` away from the real current clock. */
function at(offsetMs: number): string {
  return new Date(Date.now() + offsetMs).toISOString();
}

/**
 * Three batches that between them walk every arm of the status tag and of the
 * revoke button's `disabled` expression:
 *
 * - `b_active`: has a note, still valid, codes left (note arm, not-expired arm,
 *   active arm, `disabled` false)
 * - `b_done`: empty note, still valid, fully consumed (fallback-title arm,
 *   not-expired arm, completed arm, first half of the `disabled` `||`)
 * - `b_expired`: past expiry, codes left (expired arm, second half of `||`)
 */
function makeBatches(): InviteBatch[] {
  return [
    {
      id: "b_active",
      note: "Team offsite",
      total: 10,
      redeemed: 2,
      revoked: 1,
      expires_at: at(2 * DAY),
    },
    {
      id: "b_done",
      note: "",
      total: 3,
      redeemed: 2,
      revoked: 1,
      expires_at: at(3 * DAY),
    },
    {
      id: "b_expired",
      note: "Old drop",
      total: 5,
      redeemed: 1,
      revoked: 0,
      expires_at: at(-2 * DAY),
    },
  ] as InviteBatch[];
}

/** The card title used when a batch has no note. */
const FALLBACK_TITLE = "hub.governance.invitations.batchTitle";

function makeModels() {
  return [
    { id: "m1", name: "Alpha" },
    { id: "m2", name: "Beta" },
  ];
}

function makeSettings(mode: string) {
  return { config: { control_plane: { registration: { mode } } } };
}

interface StubOptions {
  batches?: InviteBatch[];
  models?: unknown;
  mode?: string;
  settingsImpl?: () => Promise<unknown>;
  codes?: { code: string }[];
  createImpl?: (body: unknown) => Promise<unknown>;
}

/**
 * Routes every governance GET by path and records POST calls so the payload
 * assertions can read them back. `codes` is what a successful create returns.
 */
function stubLoad(options: StubOptions = {}) {
  const posts: { path: string; method: string; body: unknown }[] = [];
  governanceRequest.mockImplementation(
    async (path: string, method = "GET", body?: unknown) => {
      if (method === "GET") {
        if (path === "admin/invite-batches")
          return options.batches ?? makeBatches();
        if (path === "admin/models") return options.models ?? makeModels();
        throw new Error(`unexpected GET ${path}`);
      }
      posts.push({ path, method, body });
      if (options.createImpl && path === "admin/invite-batches")
        return options.createImpl(body);
      if (path === "admin/invite-batches")
        return { codes: options.codes ?? [{ code: "CODE-1" }] };
      return undefined;
    },
  );
  getSettings.mockImplementation(
    options.settingsImpl ??
      (async () => makeSettings(options.mode ?? "invite")),
  );
  return posts;
}

// ---------------------------------------------------------------------------
// dom helpers
// ---------------------------------------------------------------------------

/** True for elements antd is currently animating out (see header, point 2). */
function isLeaving(node: Element): boolean {
  return node.className.includes("ant-zoom-leave");
}

/** Every Modal that is actually open right now. */
function liveModals(): Element[] {
  return Array.from(document.querySelectorAll(".ant-modal-wrap"))
    .map((w) => w.querySelector(".ant-modal"))
    .filter((m): m is Element => !!m && !isLeaving(m));
}

function modalsTitled(title: string): Element[] {
  return liveModals().filter(
    (m) => m.querySelector(".ant-modal-title")?.textContent === title,
  );
}

/** The single open Modal with this title. */
function visibleModal(title: string): Element {
  const found = modalsTitled(title);
  expect(
    found,
    `expected one live modal titled ${title}, live titles are ${liveModals()
      .map((m) => m.querySelector(".ant-modal-title")?.textContent)
      .join("|")}`,
  ).toHaveLength(1);
  return found[0];
}

/** How many open Modals carry this title (0 once it has been dismissed). */
function visibleModalCount(title: string): number {
  return modalsTitled(title).length;
}

function modalOk(modal: Element): HTMLElement {
  const found = Array.from(
    modal.querySelectorAll(".ant-modal-footer .ant-btn"),
  ).find((b) => b.className.includes("ant-btn-primary")) as HTMLElement;
  expect(found, "modal ok button missing").toBeTruthy();
  return found;
}

function modalCancel(modal: Element): HTMLElement {
  const found = Array.from(
    modal.querySelectorAll(".ant-modal-footer .ant-btn"),
  ).find((b) => !b.className.includes("ant-btn-primary")) as HTMLElement;
  expect(found, "modal cancel button missing").toBeTruthy();
  return found;
}

/** The one open `modal.confirm` dialog with this title (header, point 3). */
function liveConfirmsTitled(title: string): Element[] {
  return Array.from(document.querySelectorAll(".ant-modal-confirm")).filter(
    (n) =>
      !isLeaving(n) &&
      n.querySelector(".ant-modal-confirm-title")?.textContent === title,
  );
}

function liveConfirm(title: string): Element {
  const found = liveConfirmsTitled(title);
  expect(
    found,
    `expected one live confirm titled ${title}, live confirm titles are ${Array.from(
      document.querySelectorAll(".ant-modal-confirm"),
    )
      .filter((n) => !isLeaving(n))
      .map((n) => n.querySelector(".ant-modal-confirm-title")?.textContent)
      .join("|")}`,
  ).toHaveLength(1);
  return found[0];
}

/**
 * How many open confirm dialogs carry this title. Note that a confirm dialog
 * puts its title in `.ant-modal-confirm-title`, not `.ant-modal-title`, so
 * `visibleModalCount` cannot see it.
 */
function liveConfirmCount(title: string): number {
  return liveConfirmsTitled(title).length;
}

function confirmButton(dialog: Element, primary: boolean): HTMLElement {
  const found = Array.from(dialog.querySelectorAll(".ant-btn")).find((b) =>
    primary
      ? b.className.includes("ant-btn-primary")
      : !b.className.includes("ant-btn-primary"),
  ) as HTMLElement;
  expect(found, "confirm button missing").toBeTruthy();
  return found;
}

/** The dropdown that is actually open right now (header, point 2). */
function liveDropdown(): Element {
  const nodes = Array.from(
    document.querySelectorAll(".ant-select-dropdown"),
  ).filter(
    (n) =>
      !n.className.includes("ant-slide-up-leave") &&
      !n.className.includes("ant-select-dropdown-hidden"),
  );
  expect(nodes).toHaveLength(1);
  return nodes[0];
}

function optionsOf(dd: Element): string[] {
  return Array.from(dd.querySelectorAll(".ant-select-item-option")).map(
    (n) => n.textContent ?? "",
  );
}

/** Opens the `index`-th Select inside `scope` and returns its live dropdown. */
async function openSelect(scope: ParentNode, index = 0): Promise<Element> {
  const combo = scope.querySelectorAll("input[role='combobox']")[
    index
  ] as HTMLInputElement;
  expect(combo, `combobox ${index} missing in scope`).toBeTruthy();
  fireEvent.mouseDown(combo.closest(".ant-select-selector") as HTMLElement);
  await waitFor(() => expect(combo.getAttribute("aria-expanded")).toBe("true"));
  await waitFor(() => expect(liveDropdown()).toBeTruthy());
  return liveDropdown();
}

async function pickOption(scope: ParentNode, index: number, label: string) {
  const dd = await openSelect(scope, index);
  const option = Array.from(
    dd.querySelectorAll(".ant-select-item-option"),
  ).find((n) => n.textContent === label);
  expect(
    option,
    `option ${label} not in ${optionsOf(dd).join("|")}`,
  ).toBeTruthy();
  fireEvent.click(option as HTMLElement);
  return dd;
}

/** The batch card whose title heading reads `title`. */
function cardOf(container: HTMLElement, title: string): Element {
  const found = Array.from(container.querySelectorAll(`.${styles.card}`)).find(
    (c) => c.querySelector("h3")?.textContent === title,
  );
  expect(
    found,
    `card ${title} missing among ${Array.from(
      container.querySelectorAll(`.${styles.card} h3`),
    )
      .map((h) => h.textContent)
      .join("|")}`,
  ).toBeTruthy();
  return found as Element;
}

function statusTag(card: Element): string {
  return card.querySelector(".ant-tag")?.textContent ?? "";
}

function revokeButton(card: Element): HTMLButtonElement {
  const found = Array.from(card.querySelectorAll("button")).find(
    (b) => b.textContent === "hub.governance.invitations.revoke",
  );
  expect(found, "revoke button missing").toBeTruthy();
  return found as HTMLButtonElement;
}

/** antd keeps rendered notices around, so look for one carrying `text`. */
async function expectMessage(text: string) {
  await waitFor(() => {
    const notices = Array.from(
      document.querySelectorAll(".ant-message-notice-content"),
    );
    expect(notices.map((n) => n.textContent)).toContain(text);
  });
}

function buttonByText(scope: ParentNode, text: string): HTMLElement {
  const found = Array.from(scope.querySelectorAll("button")).find(
    (b) => b.textContent === text,
  );
  expect(found, `button ${text} missing`).toBeTruthy();
  return found as HTMLElement;
}

const CREATE_TITLE = "hub.governance.invitations.createTitle";
const CODES_TITLE = "hub.governance.invitations.codesTitle";
const GENERATE = "hub.governance.invitations.generate";
const REVOKE_TITLE = "hub.governance.invitations.revokeTitle";

// ---------------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------------

describe("Invitations", () => {
  beforeEach(() => {
    governanceRequest.mockReset();
    getSettings.mockReset();
    document.body.innerHTML = "";
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  function renderPage() {
    return render(
      <App>
        <Invitations />
      </App>,
    );
  }

  /**
   * Renders and waits for the three-way load to settle. The settle signal
   * depends on the fixture: with batches it is the card count, with none it is
   * the empty panel, because zero cards is also true before the load resolves.
   */
  async function renderLoaded(options: StubOptions = {}) {
    const posts = stubLoad(options);
    const view = renderPage();
    const batches = options.batches ?? makeBatches();
    if (batches.length === 0) {
      await waitFor(() =>
        expect(view.container.querySelector(`.${styles.empty}`)).toBeTruthy(),
      );
    } else {
      await waitFor(() =>
        expect(view.container.querySelectorAll(`.${styles.card}`)).toHaveLength(
          batches.length,
        ),
      );
    }
    return { ...view, posts };
  }

  /** Opens the create modal from a loaded page and returns both handles. */
  async function openCreateModal() {
    const { container, posts } = await renderLoaded();
    fireEvent.click(buttonByText(container, GENERATE));
    const modal = visibleModal(CREATE_TITLE);
    return { container, posts, modal };
  }

  /**
   * Creates a batch through the form so the codes modal opens, and returns the
   * codes dialog together with the recorded POST bodies.
   */
  async function openCodesModal(codes: { code: string }[]) {
    const posts = stubLoad({ codes });
    const { container } = renderPage();
    await waitFor(() =>
      expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
    );
    fireEvent.click(buttonByText(container, GENERATE));
    const create = visibleModal(CREATE_TITLE);
    await act(async () => {
      fireEvent.click(modalOk(create));
    });
    await waitFor(() => expect(visibleModalCount(CODES_TITLE)).toBe(1));
    return { posts, codes: visibleModal(CODES_TITLE) };
  }

  describe("initial load", () => {
    it("requests the batches and the model directory plus the hub settings", async () => {
      await renderLoaded();
      const paths = governanceRequest.mock.calls
        .filter((c) => (c[1] ?? "GET") === "GET")
        .map((c) => c[0])
        .sort();
      expect(paths).toEqual(["admin/invite-batches", "admin/models"]);
      expect(getSettings).toHaveBeenCalledTimes(1);
    });

    it("renders one card per batch with redeemed over total", async () => {
      const { container } = await renderLoaded();
      expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3);
      const active = cardOf(container, "Team offsite");
      expect(active.querySelector(`.${styles.metric}`)?.textContent).toBe(
        "2 / 10",
      );
      expect(active.textContent).toContain(
        "hub.governance.invitations.redeemedTotal",
      );
      expect(active.textContent).toContain(
        "hub.governance.invitations.revoked",
      );
      expect(active.textContent).toContain(
        "hub.governance.invitations.expires",
      );
      expect(active.querySelector(`.${styles.heading}`)).toBeTruthy();
    });

    it("reports a load failure and leaves the list empty", async () => {
      // A rejected settings call fails the whole Promise.all, so neither the
      // batches nor the registration mode are ever set. That is the falsy arm
      // of the notice guard.
      stubLoad({
        settingsImpl: () => Promise.reject(new Error("Failed to fetch")),
      });
      const { container } = renderPage();
      await expectMessage("hub.governance.errors.requestFailed");
      await waitFor(() =>
        expect(container.querySelector(`.${styles.empty}`)).toBeTruthy(),
      );
      expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(0);
      expect(container.querySelectorAll(`.${styles.notice}`)).toHaveLength(0);
    });

    it("shows an unmapped backend message verbatim", async () => {
      stubLoad({
        settingsImpl: () => Promise.reject(new Error("totally unknown reason")),
      });
      renderPage();
      await expectMessage("totally unknown reason");
      // The distinguishing point is that an unknown reason is passed through
      // as-is rather than being mapped onto a translation key.
      await waitFor(() => {
        const notices = Array.from(
          document.querySelectorAll(".ant-message-notice-content"),
        ).map((n) => n.textContent ?? "");
        expect(notices).toContain("totally unknown reason");
        expect(notices).not.toContain("hub.governance.errors.requestFailed");
      });
    });
  });

  describe("registration notice", () => {
    it("hides the notice when registration is invite only", async () => {
      const { container } = await renderLoaded({ mode: "invite" });
      expect(container.querySelectorAll(`.${styles.notice}`)).toHaveLength(0);
    });

    it("shows the translated mode for open registration", async () => {
      const { container } = await renderLoaded({ mode: "open" });
      const notice = container.querySelector(`.${styles.notice}`);
      expect(notice).toBeTruthy();
      expect(notice?.textContent).toContain(
        "hub.governance.settings.registration",
      );
      expect(notice?.textContent).toContain("hub.governance.settings.open");
      expect(notice?.querySelector("svg")).toBeTruthy();
    });

    it("shows the translated mode for closed registration", async () => {
      const { container } = await renderLoaded({ mode: "closed" });
      expect(
        container.querySelector(`.${styles.notice}`)?.textContent,
      ).toContain("hub.governance.settings.closed");
    });
  });

  describe("empty state", () => {
    it("renders the empty panel when there are no batches", async () => {
      const { container } = await renderLoaded({ batches: [] });
      const empty = container.querySelector(`.${styles.empty}`);
      expect(empty).toBeTruthy();
      expect(empty?.querySelector("strong")?.textContent).toBe(
        "hub.governance.invitations.emptyTitle",
      );
      expect(empty?.querySelector("svg")).toBeTruthy();
      expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(0);
      expect(container.querySelector(`.${styles.tablePanel}`)).toBeTruthy();
    });

    it("drops the empty panel once a batch exists", async () => {
      const { container } = await renderLoaded();
      expect(container.querySelectorAll(`.${styles.empty}`)).toHaveLength(0);
      expect(container.querySelector(`.${styles.tablePanel}`)).toBeNull();
    });
  });

  describe("batch status tags", () => {
    it("marks a fully consumed batch as completed", async () => {
      const { container } = await renderLoaded();
      // The card title falls back to the batch title when `note` is empty.
      const done = cardOf(container, FALLBACK_TITLE);
      expect(statusTag(done)).toBe("hub.governance.invitations.completed");
      expect(done.querySelector(`.${styles.metric}`)?.textContent).toBe(
        "2 / 3",
      );
    });

    it("marks a batch with codes left as active", async () => {
      const { container } = await renderLoaded();
      expect(statusTag(cardOf(container, "Team offsite"))).toBe(
        "hub.governance.invitations.active",
      );
    });

    it("marks a past-expiry batch as expired even with codes left", async () => {
      const { container } = await renderLoaded();
      const expired = cardOf(container, "Old drop");
      expect(statusTag(expired)).toBe("hub.governance.invitations.expired");
      expect(expired.querySelector(`.${styles.metric}`)?.textContent).toBe(
        "1 / 5",
      );
    });

    it("counts revocations towards consuming the batch", async () => {
      const { container } = await renderLoaded({
        batches: [
          {
            id: "b_revoked",
            note: "All revoked",
            total: 2,
            redeemed: 0,
            revoked: 2,
            expires_at: at(DAY),
          },
        ] as InviteBatch[],
      });
      const card = cardOf(container, "All revoked");
      expect(statusTag(card)).toBe("hub.governance.invitations.completed");
      expect(card.querySelector(`.${styles.metric}`)?.textContent).toBe(
        "0 / 2",
      );
      expect(revokeButton(card)).toBeDisabled();
    });

    it("formats the expiry with the current i18n language", async () => {
      const expiresAt = "2026-10-01T00:00:00.000Z";
      const { container } = await renderLoaded({
        batches: [
          {
            id: "b_fmt",
            note: "Formatted",
            total: 1,
            redeemed: 0,
            revoked: 0,
            expires_at: expiresAt,
          },
        ] as InviteBatch[],
      });
      const text = cardOf(container, "Formatted").textContent ?? "";
      expect(text).toContain(new Date(expiresAt).toLocaleString("en-US"));
    });
  });

  describe("revoke button state", () => {
    it("enables revoke only for a batch that is valid and has codes left", async () => {
      const { container } = await renderLoaded();
      expect(revokeButton(cardOf(container, "Team offsite"))).toBeEnabled();
      expect(revokeButton(cardOf(container, FALLBACK_TITLE))).toBeDisabled();
      expect(revokeButton(cardOf(container, "Old drop"))).toBeDisabled();
    });

    it("asks for confirmation before revoking", async () => {
      const posts = stubLoad();
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      fireEvent.click(revokeButton(cardOf(container, "Team offsite")));
      const dialog = await waitFor(() => liveConfirm(REVOKE_TITLE));
      expect(
        dialog.querySelector(".ant-modal-confirm-title")?.textContent,
      ).toBe(REVOKE_TITLE);
      // Nothing has been posted while the dialog is merely open.
      expect(posts).toHaveLength(0);
    });

    it("posts nothing when the confirmation is cancelled", async () => {
      const posts = stubLoad();
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      fireEvent.click(revokeButton(cardOf(container, "Team offsite")));
      const dialog = await waitFor(() => liveConfirm(REVOKE_TITLE));
      await act(async () => {
        fireEvent.click(confirmButton(dialog, false));
      });
      await waitFor(() => expect(liveConfirmCount(REVOKE_TITLE)).toBe(0));
      expect(posts).toHaveLength(0);
      expect(
        governanceRequest.mock.calls.filter((c) => c[1] === "POST"),
      ).toHaveLength(0);
      // The card list is untouched, so no reload happened either.
      expect(
        governanceRequest.mock.calls.filter(
          (c) => (c[1] ?? "GET") === "GET" && c[0] === "admin/invite-batches",
        ),
      ).toHaveLength(1);
    });

    it("revokes and reloads the list once confirmed", async () => {
      const posts = stubLoad();
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      fireEvent.click(revokeButton(cardOf(container, "Team offsite")));
      const dialog = await waitFor(() => liveConfirm(REVOKE_TITLE));
      await act(async () => {
        fireEvent.click(confirmButton(dialog, true));
      });
      await waitFor(() =>
        expect(posts.map((p) => p.path)).toEqual([
          "admin/invite-batches/b_active/revoke",
        ]),
      );
      expect(posts[0].method).toBe("POST");
      expect(posts[0].body).toBeUndefined();
      // `load()` runs again after the revoke resolves.
      await waitFor(() =>
        expect(
          governanceRequest.mock.calls.filter(
            (c) => (c[1] ?? "GET") === "GET" && c[0] === "admin/invite-batches",
          ).length,
        ).toBeGreaterThanOrEqual(2),
      );
    });

    it("targets the batch whose button was clicked", async () => {
      const posts = stubLoad({
        batches: [
          {
            id: "b_one",
            note: "First",
            total: 4,
            redeemed: 1,
            revoked: 0,
            expires_at: at(DAY),
          },
          {
            id: "b_two",
            note: "Second",
            total: 4,
            redeemed: 1,
            revoked: 0,
            expires_at: at(DAY),
          },
        ] as InviteBatch[],
      });
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(2),
      );
      fireEvent.click(revokeButton(cardOf(container, "Second")));
      const dialog = await waitFor(() => liveConfirm(REVOKE_TITLE));
      await act(async () => {
        fireEvent.click(confirmButton(dialog, true));
      });
      await waitFor(() =>
        expect(posts.map((p) => p.path)).toEqual([
          "admin/invite-batches/b_two/revoke",
        ]),
      );
    });
  });

  describe("create modal", () => {
    it("opens with the documented defaults when generate is clicked", async () => {
      const { container } = await renderLoaded();
      fireEvent.click(buttonByText(container, GENERATE));
      const modal = visibleModal(CREATE_TITLE);
      expect(modal.querySelector(".ant-modal-title")?.textContent).toBe(
        CREATE_TITLE,
      );
      // The two required numbers come from `initialValues`.
      const spins = Array.from(
        modal.querySelectorAll("input[role='spinbutton']"),
      ) as HTMLInputElement[];
      expect(spins.map((s) => s.value)).toEqual(["10", "7"]);
      const note = modal.querySelector(
        "input[maxlength='256']",
      ) as HTMLInputElement;
      expect(note).toBeTruthy();
      expect(note.value).toBe("");
      expect(modal.querySelector("svg")).toBeTruthy();
    });

    it("closes without posting when cancelled", async () => {
      const { container, posts, modal } = await openCreateModal();
      expect(container.querySelectorAll(`.${styles.card}`).length).toBe(3);
      fireEvent.click(modalCancel(modal));
      await waitFor(() => expect(visibleModalCount(CREATE_TITLE)).toBe(0));
      expect(posts).toHaveLength(0);
    });

    it("posts the defaults with inherit budget and a client request id", async () => {
      const posts = stubLoad({ codes: [{ code: "AAA" }, { code: "BBB" }] });
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      fireEvent.click(buttonByText(container, GENERATE));
      const modal = visibleModal(CREATE_TITLE);
      const note = modal.querySelector(
        "input[maxlength='256']",
      ) as HTMLInputElement;
      fireEvent.change(note, { target: { value: "Spring cohort" } });

      await act(async () => {
        fireEvent.click(modalOk(modal));
      });

      await waitFor(() => expect(posts).toHaveLength(1));
      expect(posts[0].path).toBe("admin/invite-batches");
      expect(posts[0].method).toBe("POST");
      const body = posts[0].body as Record<string, unknown>;
      expect(body.note).toBe("Spring cohort");
      expect(body.count).toBe(10);
      expect(body.valid_days).toBe(7);
      expect(body.model_ids).toEqual([]);
      // `inherit_budget` in `initialValues` is overwritten by the editor state.
      expect(body.inherit_budget).toBe(true);
      expect(body.token_limit).toBeNull();
      // `createClientMessageId` is real here, so assert its shape, not a value.
      expect(body.request_id as string).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
      );
    });

    it("uses a fresh request id each time the modal is opened", async () => {
      const posts = stubLoad();
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      for (let i = 0; i < 2; i += 1) {
        fireEvent.click(buttonByText(container, GENERATE));
        const modal = await waitFor(() => visibleModal(CREATE_TITLE));
        await act(async () => {
          fireEvent.click(modalOk(modal));
        });
        await waitFor(() => expect(posts).toHaveLength(i + 1));
        await waitFor(() => expect(visibleModalCount(CREATE_TITLE)).toBe(0));
      }
      const ids = posts.map(
        (p) => (p.body as Record<string, unknown>).request_id,
      ) as string[];
      expect(ids).toHaveLength(2);
      expect(ids[0]).not.toBe(ids[1]);
    });

    it("shows the issued codes and reloads the list after creating", async () => {
      stubLoad({ codes: [{ code: "AAA" }, { code: "BBB" }] });
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      fireEvent.click(buttonByText(container, GENERATE));
      const create = visibleModal(CREATE_TITLE);
      await act(async () => {
        fireEvent.click(modalOk(create));
      });
      await waitFor(() => expect(visibleModalCount(CODES_TITLE)).toBe(1));
      const codes = visibleModal(CODES_TITLE);
      expect(codes.querySelector("pre")?.textContent).toBe("AAA\nBBB");
      expect(visibleModalCount(CREATE_TITLE)).toBe(0);
      await waitFor(() =>
        expect(
          governanceRequest.mock.calls.filter(
            (c) => (c[1] ?? "GET") === "GET" && c[0] === "admin/invite-batches",
          ).length,
        ).toBeGreaterThanOrEqual(2),
      );
    });

    it("surfaces a backend failure and leaves the form open", async () => {
      stubLoad({
        createImpl: () =>
          Promise.reject(
            new Error("Batch already created; codes cannot replay"),
          ),
      });
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      fireEvent.click(buttonByText(container, GENERATE));
      const modal = visibleModal(CREATE_TITLE);
      await act(async () => {
        fireEvent.click(modalOk(modal));
      });
      await expectMessage("hub.governance.errors.batchExists");
      // `finally` cleared the busy flag, so the OK button is usable again.
      await waitFor(() => {
        const live = visibleModal(CREATE_TITLE);
        expect(modalOk(live).className).not.toContain("ant-btn-loading");
      });
      expect(visibleModalCount(CODES_TITLE)).toBe(0);
    });

    it("marks the OK button busy while the create request is in flight", async () => {
      let release: (value: unknown) => void = () => {};
      stubLoad({
        createImpl: () =>
          new Promise((resolve) => {
            release = resolve;
          }),
      });
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      fireEvent.click(buttonByText(container, GENERATE));
      const modal = visibleModal(CREATE_TITLE);
      // Before submitting nothing is in flight.
      expect(modalOk(modal).className).not.toContain("ant-btn-loading");
      await act(async () => {
        fireEvent.click(modalOk(modal));
      });
      // `confirmLoading={busy}` is what surfaces the pending request.
      await waitFor(() =>
        expect(modalOk(visibleModal(CREATE_TITLE)).className).toContain(
          "ant-btn-loading",
        ),
      );
      await act(async () => {
        release({ codes: [] });
      });
      await waitFor(() => expect(visibleModalCount(CREATE_TITLE)).toBe(0));
      // An empty code list must not open the codes dialog.
      expect(visibleModalCount(CODES_TITLE)).toBe(0);
    });
  });

  describe("budget guard in the create form", () => {
    /** Opens the customization <details> so both Selects are reachable. */
    function openDetails(modal: Element): HTMLDetailsElement {
      const details = modal.querySelector(
        `details.${styles.help}`,
      ) as HTMLDetailsElement;
      expect(details).toBeTruthy();
      details.open = true;
      expect(details.querySelector("summary")?.textContent).toBe(
        "hub.governance.invitations.customize",
      );
      return details;
    }

    it("offers the inherit option because allowInherit is set", async () => {
      const { modal } = await openCreateModal();
      const details = openDetails(modal);
      const dd = await openSelect(details, 1);
      expect(optionsOf(dd)).toEqual([
        "hub.governance.budget.inherit",
        "hub.governance.budget.unlimited",
        "hub.governance.budget.custom",
        "hub.governance.budget.pause",
      ]);
    });

    it("shows the amount input only in limited mode", async () => {
      const { modal } = await openCreateModal();
      const details = openDetails(modal);
      expect(details.querySelector("input[role='spinbutton']")).toBeNull();
      await pickOption(details, 1, "hub.governance.budget.custom");
      await waitFor(() =>
        expect(details.querySelector("input[role='spinbutton']")).toBeTruthy(),
      );
    });

    it("refuses to submit a limited budget without an amount", async () => {
      const posts = stubLoad();
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      fireEvent.click(buttonByText(container, GENERATE));
      const modal = visibleModal(CREATE_TITLE);
      const details = openDetails(modal);
      await pickOption(details, 1, "hub.governance.budget.custom");
      // `amount` is still null, so the guard fires and returns early.
      await act(async () => {
        fireEvent.click(modalOk(modal));
      });
      await expectMessage("hub.governance.budget.positiveLimit");
      expect(posts).toHaveLength(0);
      // The form stays open so the amount can be filled in.
      expect(visibleModalCount(CREATE_TITLE)).toBe(1);
    });

    it("submits the amount once a limited budget has one", async () => {
      const posts = stubLoad();
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      fireEvent.click(buttonByText(container, GENERATE));
      const modal = visibleModal(CREATE_TITLE);
      const details = openDetails(modal);
      await pickOption(details, 1, "hub.governance.budget.custom");
      const amount = details.querySelector(
        "input[role='spinbutton']",
      ) as HTMLInputElement;
      expect(amount).toBeTruthy();
      fireEvent.change(amount, { target: { value: "5000" } });
      fireEvent.blur(amount);
      await waitFor(() => expect(amount.value).toBe("5000"));

      await act(async () => {
        fireEvent.click(modalOk(modal));
      });
      await waitFor(() => expect(posts).toHaveLength(1));
      const body = posts[0].body as Record<string, unknown>;
      expect(body.inherit_budget).toBe(false);
      expect(body.token_limit).toBe(5000);
    });

    it.each([
      ["hub.governance.budget.inherit", true, null],
      ["hub.governance.budget.unlimited", false, null],
      ["hub.governance.budget.pause", false, 0],
    ] as const)(
      "maps %s onto the payload",
      async (label, inheritBudget, tokenLimit) => {
        const posts = stubLoad();
        const { container } = renderPage();
        await waitFor(() =>
          expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
        );
        fireEvent.click(buttonByText(container, GENERATE));
        const modal = visibleModal(CREATE_TITLE);
        const details = openDetails(modal);
        await pickOption(details, 1, label);
        await act(async () => {
          fireEvent.click(modalOk(modal));
        });
        await waitFor(() => expect(posts).toHaveLength(1));
        const body = posts[0].body as Record<string, unknown>;
        expect(body.inherit_budget).toBe(inheritBudget);
        expect(body.token_limit).toBe(tokenLimit);
      },
    );
  });

  describe("additional model grants", () => {
    it("lists the model directory in the multi select", async () => {
      const { modal } = await openCreateModal();
      const details = modal.querySelector(
        `details.${styles.help}`,
      ) as HTMLDetailsElement;
      details.open = true;
      // Index 0 is the grants select, index 1 is BudgetEditor's mode select.
      const dd = await openSelect(details, 0);
      expect(optionsOf(dd)).toEqual(["Alpha", "Beta"]);
    });

    it("reflects an empty model directory as no options", async () => {
      const { container } = await renderLoaded({ models: [] });
      fireEvent.click(buttonByText(container, GENERATE));
      const modal = visibleModal(CREATE_TITLE);
      const details = modal.querySelector(
        `details.${styles.help}`,
      ) as HTMLDetailsElement;
      details.open = true;
      const dd = await openSelect(details, 0);
      expect(optionsOf(dd)).toEqual([]);
    });

    it("posts the picked model ids", async () => {
      const posts = stubLoad();
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll(`.${styles.card}`)).toHaveLength(3),
      );
      fireEvent.click(buttonByText(container, GENERATE));
      const modal = visibleModal(CREATE_TITLE);
      const details = modal.querySelector(
        `details.${styles.help}`,
      ) as HTMLDetailsElement;
      details.open = true;
      const dd = await openSelect(details, 0);
      const beta = Array.from(
        dd.querySelectorAll(".ant-select-item-option"),
      ).find((n) => n.textContent === "Beta");
      expect(beta).toBeTruthy();
      fireEvent.click(beta as HTMLElement);
      await waitFor(() => {
        const picked = Array.from(
          details.querySelectorAll(".ant-select-selection-item"),
        ).map((n) => n.getAttribute("title") ?? n.textContent ?? "");
        expect(picked).toContain("Beta");
      });
      await act(async () => {
        fireEvent.click(modalOk(modal));
      });
      await waitFor(() => expect(posts).toHaveLength(1));
      expect((posts[0].body as Record<string, unknown>).model_ids).toEqual([
        "m2",
      ]);
    });
  });

  describe("codes modal", () => {
    it("joins the codes with newlines", async () => {
      const { codes } = await openCodesModal([
        { code: "ONE" },
        { code: "TWO" },
        { code: "THREE" },
      ]);
      expect(codes.querySelector("pre")?.textContent).toBe("ONE\nTWO\nTHREE");
      expect(codes.querySelector(`.${styles.codes}`)).toBeTruthy();
      expect(codes.querySelector(".ant-modal-title")?.textContent).toBe(
        CODES_TITLE,
      );
    });

    it("closes on OK", async () => {
      const { codes } = await openCodesModal([{ code: "ONE" }]);
      fireEvent.click(modalOk(codes));
      await waitFor(() => expect(visibleModalCount(CODES_TITLE)).toBe(0));
    });

    it("closes on cancel", async () => {
      const { codes } = await openCodesModal([{ code: "ONE" }]);
      fireEvent.click(modalCancel(codes));
      await waitFor(() => expect(visibleModalCount(CODES_TITLE)).toBe(0));
    });

    it("downloads the codes as a text file and revokes the object url", async () => {
      const { codes } = await openCodesModal([
        { code: "ONE" },
        { code: "TWO" },
      ]);
      const created: string[] = [];
      const revoked: string[] = [];
      const blobs: Blob[] = [];
      const origCreate = URL.createObjectURL;
      const origRevoke = URL.revokeObjectURL;
      URL.createObjectURL = vi.fn((blob: Blob) => {
        blobs.push(blob);
        const url = `blob:stub-${created.length}`;
        created.push(url);
        return url;
      }) as unknown as typeof URL.createObjectURL;
      URL.revokeObjectURL = vi.fn((url: string) => {
        revoked.push(url);
      }) as unknown as typeof URL.revokeObjectURL;
      const clicked: HTMLAnchorElement[] = [];
      const clickSpy = vi
        .spyOn(HTMLAnchorElement.prototype, "click")
        .mockImplementation(function (this: HTMLAnchorElement) {
          clicked.push(this);
        });
      try {
        fireEvent.click(
          buttonByText(codes, "hub.governance.invitations.download"),
        );
        expect(created).toEqual(["blob:stub-0"]);
        expect(blobs).toHaveLength(1);
        expect(blobs[0]).toBeInstanceOf(Blob);
        expect(blobs[0].type).toBe("text/plain");
        expect(await blobs[0].text()).toBe("ONE\nTWO");
        expect(clicked).toHaveLength(1);
        expect(clicked[0].download).toBe("hub-invitations.txt");
        expect(clicked[0].href).toContain("blob:stub-0");
        // The url is released again right after the click.
        expect(revoked).toEqual(["blob:stub-0"]);
      } finally {
        clickSpy.mockRestore();
        URL.createObjectURL = origCreate;
        URL.revokeObjectURL = origRevoke;
      }
    });
  });

  describe("page chrome", () => {
    it("renders the title and the generate action", async () => {
      const { container } = await renderLoaded();
      const title = Array.from(container.querySelectorAll("h3")).find(
        (h) => h.textContent === "hub.governance.invitations.title",
      );
      expect(title).toBeTruthy();
      const generate = buttonByText(container, GENERATE);
      expect(generate.className).toContain("ant-btn-primary");
      expect(generate.querySelector("svg")).toBeTruthy();
      expect(container.querySelector(`.${styles.panel}`)).toBeTruthy();
      expect(container.querySelector(`.${styles.grid}`)).toBeTruthy();
    });
  });
});
