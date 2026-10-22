/**
 * Unit tests for OrganizationBudget, the hub-governance organization budget
 * page. It loads a model policy plus a usage report, mirrors both into two
 * BudgetEditor blocks, and writes them back through two different endpoints.
 *
 * Two harness details are load bearing for the assertions below:
 *
 * 1. The component calls `App.useApp()`, so it must render inside antd's
 *    `<App>`; otherwise `message` is undefined and every save path throws.
 * 2. antd Select renders its dropdown into a document-level portal and, in
 *    jsdom, keeps the leaving dropdown mounted because `animationend` never
 *    fires there. Filtering on `.ant-select-dropdown-hidden` alone therefore
 *    matches stale nodes. `liveDropdown()` filters on the enter/leave motion
 *    classes instead, which is what actually tracks the open dropdown.
 *
 * BudgetEditor is deliberately NOT mocked: the mode/amount pair it renders is
 * exactly what the save payloads assert on, and stubbing it would turn those
 * assertions into assertions about the stub.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, waitFor, fireEvent } from "@testing-library/react";
import { App } from "antd";

import type {
  ModelPolicy,
  UsageReport,
} from "../../../api/modules/hubGovernance";

const governanceRequest = vi.hoisted(() => vi.fn());

vi.mock("../../../api/modules/hubGovernance", () => ({ governanceRequest }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { language: "en-US" },
  }),
}));

import OrganizationBudget from "./OrganizationBudget";
import layout from "./OrganizationBudget.module.less";

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

function makePolicy(extra: Partial<ModelPolicy> = {}): ModelPolicy {
  return {
    default_model_id: "mm1",
    member_token_limit: 5000,
    timezone: "UTC",
    revision: 3,
    ...extra,
  } as ModelPolicy;
}

function makeUsage(orgLimit: number | null): UsageReport {
  return {
    timezone: "UTC",
    daily: [],
    organization: {
      subject: "org",
      period: "2026-09",
      token_limit: orgLimit,
      remaining: 10,
      charged: 5,
      actual: 5,
      reserved: 0,
      conservative: 0,
      requests: 0,
    },
    members: [],
    models: [],
  } as UsageReport;
}

/** Resolves `admin/model-policy` and `admin/usage` independently. */
function stubLoad(policy: unknown, usage: unknown) {
  governanceRequest.mockImplementation(async (path: string) => {
    if (path === "admin/model-policy") return policy;
    if (path === "admin/usage") return usage;
    throw new Error(`unexpected GET ${path}`);
  });
}

// ---------------------------------------------------------------------------
// dom helpers
// ---------------------------------------------------------------------------

/** The dropdown that is actually open right now (see file header, point 2). */
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
  expect(combo).toBeTruthy();
  fireEvent.mouseDown(combo.closest(".ant-select-selector") as HTMLElement);
  await waitFor(() => expect(combo.getAttribute("aria-expanded")).toBe("true"));
  await waitFor(() => {
    Array.from(document.querySelectorAll(".ant-select-dropdown")).filter(
      (n) => !n.className.includes("ant-slide-up-leave"),
    );
    expect(liveDropdown()).toBeTruthy();
  });
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

function sections(container: HTMLElement) {
  const found = container.querySelectorAll(`.${layout.section}`);
  expect(found).toHaveLength(2);
  return found;
}

/** The antd InputNumber inside a section; only present while mode is limited. */
function amountInput(section: Element): HTMLInputElement | null {
  return section.querySelector("input[role='spinbutton']");
}

function selectionLabels(scope: ParentNode): string[] {
  return Array.from(scope.querySelectorAll(".ant-select-selection-item")).map(
    (n) => n.textContent ?? "",
  );
}

function saveButtons(container: HTMLElement): HTMLElement[] {
  const found = Array.from(container.querySelectorAll("button")).filter(
    (b) => b.textContent === "common.save",
  );
  expect(found).toHaveLength(2);
  return found as HTMLElement[];
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

// ---------------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------------

describe("OrganizationBudget", () => {
  beforeEach(() => {
    governanceRequest.mockReset();
    document.body.innerHTML = "";
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  function renderPage() {
    return render(
      <App>
        <OrganizationBudget />
      </App>,
    );
  }

  describe("initial load", () => {
    it("shows a skeleton until both requests settle", () => {
      let releasePolicy: (value: unknown) => void = () => {};
      governanceRequest.mockImplementation(
        (path: string) =>
          new Promise((resolve) => {
            if (path === "admin/model-policy") releasePolicy = resolve;
            else resolve(makeUsage(90000));
          }),
      );
      const { container } = renderPage();
      expect(container.querySelectorAll(".ant-skeleton")).toHaveLength(1);
      expect(container.querySelectorAll(`.${layout.section}`)).toHaveLength(0);
      // Resolving the second half still leaves the skeleton: both are awaited
      // through Promise.all before anything is set.
      releasePolicy(makePolicy());
    });

    it("requests the policy and the usage report together", async () => {
      stubLoad(makePolicy(), makeUsage(90000));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      expect(governanceRequest).toHaveBeenCalledTimes(2);
      expect(governanceRequest).toHaveBeenCalledWith("admin/model-policy");
      expect(governanceRequest).toHaveBeenCalledWith("admin/usage");
      // Both loads are GETs: no method argument is passed.
      expect(
        governanceRequest.mock.calls.every((call) => call.length === 1),
      ).toBe(true);
    });

    it("renders both budget sections with their own headings", async () => {
      stubLoad(makePolicy(), makeUsage(90000));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      expect(
        Array.from(container.querySelectorAll("h3")).map((n) => n.textContent),
      ).toEqual([
        "hub.governance.budget.organizationMonthly",
        "hub.governance.budget.defaultMember",
      ]);
      const [org, member] = sections(container);
      expect(container.querySelectorAll(`.${layout.settings}`)).toHaveLength(1);
      expect(container.querySelectorAll(`.${layout.controls}`)).toHaveLength(2);
      expect(container.querySelectorAll(`.${layout.actions}`)).toHaveLength(2);
      // Only the member section carries the timezone field.
      expect(org.querySelectorAll("label")).toHaveLength(0);
      expect(
        Array.from(member.querySelectorAll("label")).map((n) => n.textContent),
      ).toEqual(["hub.governance.budget.timezone"]);
    });
  });

  describe("mapping the loaded limits onto the editors", () => {
    it("maps a positive organization limit to custom mode plus that amount", async () => {
      stubLoad(makePolicy({ member_token_limit: 7000 }), makeUsage(90000));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      const [org, member] = sections(container);
      expect(selectionLabels(org)[0]).toBe("hub.governance.budget.custom");
      expect(selectionLabels(member)[0]).toBe("hub.governance.budget.custom");
      expect(amountInput(org)?.getAttribute("value")).toBe("90000");
      expect(amountInput(member)?.getAttribute("value")).toBe("7000");
    });

    it("maps a null organization limit to unlimited and drops the amount input", async () => {
      stubLoad(makePolicy({ member_token_limit: null }), makeUsage(null));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      const [org, member] = sections(container);
      expect(selectionLabels(org)[0]).toBe("hub.governance.budget.unlimited");
      expect(selectionLabels(member)[0]).toBe(
        "hub.governance.budget.unlimited",
      );
      expect(amountInput(org)).toBeNull();
      expect(amountInput(member)).toBeNull();
    });

    it("maps a zero organization limit to paused without an amount input", async () => {
      stubLoad(makePolicy({ member_token_limit: 0 }), makeUsage(0));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      const [org, member] = sections(container);
      expect(selectionLabels(org)[0]).toBe("hub.governance.budget.pause");
      expect(selectionLabels(member)[0]).toBe("hub.governance.budget.pause");
      expect(
        container.querySelectorAll("input[role='spinbutton']"),
      ).toHaveLength(0);
    });

    it("maps each side independently when the two limits differ in kind", async () => {
      stubLoad(makePolicy({ member_token_limit: 0 }), makeUsage(42000));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      const [org, member] = sections(container);
      expect(selectionLabels(org)[0]).toBe("hub.governance.budget.custom");
      expect(amountInput(org)?.getAttribute("value")).toBe("42000");
      expect(selectionLabels(member)[0]).toBe("hub.governance.budget.pause");
      expect(amountInput(member)).toBeNull();
      expect(
        container.querySelectorAll("input[role='spinbutton']"),
      ).toHaveLength(1);
    });

    it("shows the policy timezone in the timezone select", async () => {
      stubLoad(makePolicy({ timezone: "Asia/Tokyo" }), makeUsage(10));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      const [, member] = sections(container);
      // The section holds the budget-mode select first, the timezone second.
      expect(selectionLabels(member)[1]).toBe("Asia/Tokyo");
    });

    it("lists the policy timezone first and de-duplicates it against UTC", async () => {
      stubLoad(makePolicy({ timezone: "UTC" }), makeUsage(10));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      const [, member] = sections(container);
      const dd = await openSelect(member, 1);
      // "UTC" appears once even though it is both the policy value and a preset.
      expect(optionsOf(dd)).toEqual([
        "UTC",
        "Asia/Shanghai",
        "America/New_York",
        "Europe/London",
        "Asia/Tokyo",
      ]);
    });

    it("keeps an unknown policy timezone alongside the presets", async () => {
      stubLoad(makePolicy({ timezone: "Mars/Olympus" }), makeUsage(10));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      const [, member] = sections(container);
      const dd = await openSelect(member, 1);
      expect(optionsOf(dd)).toEqual([
        "Mars/Olympus",
        "Asia/Shanghai",
        "UTC",
        "America/New_York",
        "Europe/London",
        "Asia/Tokyo",
      ]);
    });
  });

  describe("error state", () => {
    it("replaces the page with an alert carrying a mapped message", async () => {
      governanceRequest.mockRejectedValue(new Error("Hub request failed"));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("[role='alert']")).toHaveLength(1),
      );
      const alert = container.querySelector("[role='alert']") as HTMLElement;
      expect(alert.textContent).toContain(
        "hub.governance.errors.requestFailed",
      );
      expect(alert.querySelectorAll("button")).toHaveLength(1);
      expect(alert.querySelector("button")?.textContent).toBe("common.retry");
      // The budget sections are gone, not merely hidden.
      expect(container.querySelectorAll(`.${layout.section}`)).toHaveLength(0);
      expect(container.querySelectorAll(".ant-skeleton")).toHaveLength(0);
    });

    it("passes an unmapped message through verbatim", async () => {
      governanceRequest.mockRejectedValue(new Error("boom-42"));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("[role='alert']")).toHaveLength(1),
      );
      expect(container.querySelector("[role='alert']")?.textContent).toContain(
        "boom-42",
      );
    });

    it("retries from the alert and recovers into the loaded page", async () => {
      governanceRequest.mockRejectedValueOnce(new Error("Failed to fetch"));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("[role='alert']")).toHaveLength(1),
      );
      stubLoad(makePolicy({ member_token_limit: 250 }), makeUsage(300));
      fireEvent.click(
        container.querySelector("[role='alert'] button") as HTMLElement,
      );
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      expect(container.querySelectorAll("[role='alert']")).toHaveLength(0);
      const [org, member] = sections(container);
      expect(amountInput(org)?.getAttribute("value")).toBe("300");
      expect(amountInput(member)?.getAttribute("value")).toBe("250");
      // Initial attempt plus the retry: two loads, two requests each.
      expect(governanceRequest).toHaveBeenCalledTimes(4);
    });
  });

  describe("saving the organization budget", () => {
    async function loaded() {
      stubLoad(makePolicy({ member_token_limit: 5000 }), makeUsage(90000));
      const view = renderPage();
      await waitFor(() =>
        expect(view.container.querySelectorAll("h3")).toHaveLength(2),
      );
      return view;
    }

    it("PUTs the untouched custom limit back with inherit false", async () => {
      const { container } = await loaded();
      governanceRequest.mockClear();
      governanceRequest.mockResolvedValue(undefined);
      fireEvent.click(saveButtons(container)[0]);
      await waitFor(() => expect(governanceRequest).toHaveBeenCalledTimes(1));
      expect(governanceRequest).toHaveBeenCalledWith(
        "admin/budgets/organization",
        "PUT",
        {
          inherit: false,
          token_limit: 90000,
        },
      );
      await expectMessage("hub.governance.budget.saved");
    });

    it("PUTs an edited amount rather than the loaded one", async () => {
      const { container } = await loaded();
      const [org] = sections(container);
      fireEvent.change(amountInput(org) as HTMLElement, {
        target: { value: "12345" },
      });
      await waitFor(() =>
        expect(amountInput(org)?.getAttribute("value")).toBe("12345"),
      );
      governanceRequest.mockClear();
      governanceRequest.mockResolvedValue(undefined);
      fireEvent.click(saveButtons(container)[0]);
      await waitFor(() =>
        expect(governanceRequest).toHaveBeenCalledWith(
          "admin/budgets/organization",
          "PUT",
          {
            inherit: false,
            token_limit: 12345,
          },
        ),
      );
    });

    it("PUTs null when the organization budget is switched to unlimited", async () => {
      const { container } = await loaded();
      const [org] = sections(container);
      await pickOption(org, 0, "hub.governance.budget.unlimited");
      await waitFor(() => expect(amountInput(org)).toBeNull());
      governanceRequest.mockClear();
      governanceRequest.mockResolvedValue(undefined);
      fireEvent.click(saveButtons(container)[0]);
      await waitFor(() =>
        expect(governanceRequest).toHaveBeenCalledWith(
          "admin/budgets/organization",
          "PUT",
          {
            inherit: false,
            token_limit: null,
          },
        ),
      );
    });

    it("PUTs zero when the organization budget is paused", async () => {
      const { container } = await loaded();
      const [org] = sections(container);
      await pickOption(org, 0, "hub.governance.budget.pause");
      await waitFor(() => expect(amountInput(org)).toBeNull());
      governanceRequest.mockClear();
      governanceRequest.mockResolvedValue(undefined);
      fireEvent.click(saveButtons(container)[0]);
      await waitFor(() =>
        expect(governanceRequest).toHaveBeenCalledWith(
          "admin/budgets/organization",
          "PUT",
          {
            inherit: false,
            token_limit: 0,
          },
        ),
      );
    });

    it("refuses to save a custom organization limit that was cleared", async () => {
      const { container } = await loaded();
      const [org] = sections(container);
      fireEvent.change(amountInput(org) as HTMLElement, {
        target: { value: "" },
      });
      await waitFor(() =>
        expect((amountInput(org) as HTMLInputElement).value).toBe(""),
      );
      governanceRequest.mockClear();
      fireEvent.click(saveButtons(container)[0]);
      await expectMessage("hub.governance.budget.positiveLimit");
      expect(governanceRequest).not.toHaveBeenCalled();
    });

    it("reports a rejected organization save through the message API", async () => {
      const { container } = await loaded();
      governanceRequest.mockClear();
      governanceRequest.mockRejectedValue(
        new Error("Policy changed; refresh before saving"),
      );
      fireEvent.click(saveButtons(container)[0]);
      await expectMessage("hub.governance.errors.changed");
      expect(governanceRequest).toHaveBeenCalledWith(
        "admin/budgets/organization",
        "PUT",
        {
          inherit: false,
          token_limit: 90000,
        },
      );
    });

    it("does not let a rejected organization save rewrite the member policy", async () => {
      const { container } = await loaded();
      governanceRequest.mockClear();
      governanceRequest.mockRejectedValue(new Error("boom"));
      fireEvent.click(saveButtons(container)[0]);
      await expectMessage("boom");
      expect(
        governanceRequest.mock.calls.some(
          (call) => call[0] === "admin/model-policy",
        ),
      ).toBe(false);
    });
  });

  describe("saving the member default", () => {
    async function loaded() {
      stubLoad(makePolicy({ member_token_limit: 5000 }), makeUsage(90000));
      const view = renderPage();
      await waitFor(() =>
        expect(view.container.querySelectorAll("h3")).toHaveLength(2),
      );
      return view;
    }

    it("PUTs the whole policy with the edited member limit", async () => {
      const { container } = await loaded();
      const [, member] = sections(container);
      fireEvent.change(amountInput(member) as HTMLElement, {
        target: { value: "6000" },
      });
      await waitFor(() =>
        expect(amountInput(member)?.getAttribute("value")).toBe("6000"),
      );
      governanceRequest.mockClear();
      governanceRequest.mockResolvedValue(
        makePolicy({ member_token_limit: 6000, revision: 4 }),
      );
      fireEvent.click(saveButtons(container)[1]);
      await waitFor(() =>
        expect(governanceRequest).toHaveBeenCalledWith(
          "admin/model-policy",
          "PUT",
          {
            default_model_id: "mm1",
            member_token_limit: 6000,
            timezone: "UTC",
            revision: 3,
          },
        ),
      );
      await expectMessage("hub.governance.budget.saved");
    });

    it("adopts the returned policy so the next save carries the new revision", async () => {
      const { container } = await loaded();
      governanceRequest.mockClear();
      governanceRequest.mockResolvedValue(
        makePolicy({
          member_token_limit: 5000,
          revision: 9,
          default_model_id: "mm2",
        }),
      );
      fireEvent.click(saveButtons(container)[1]);
      await expectMessage("hub.governance.budget.saved");
      governanceRequest.mockClear();
      governanceRequest.mockResolvedValue(undefined);
      fireEvent.click(saveButtons(container)[1]);
      await waitFor(() =>
        expect(governanceRequest).toHaveBeenCalledWith(
          "admin/model-policy",
          "PUT",
          {
            default_model_id: "mm2",
            member_token_limit: 5000,
            timezone: "UTC",
            revision: 9,
          },
        ),
      );
    });

    it("PUTs zero when the member default is paused", async () => {
      const { container } = await loaded();
      const [, member] = sections(container);
      await pickOption(member, 0, "hub.governance.budget.pause");
      await waitFor(() => expect(amountInput(member)).toBeNull());
      governanceRequest.mockClear();
      governanceRequest.mockResolvedValue(
        makePolicy({ member_token_limit: 0 }),
      );
      fireEvent.click(saveButtons(container)[1]);
      await waitFor(() =>
        expect(governanceRequest).toHaveBeenCalledWith(
          "admin/model-policy",
          "PUT",
          expect.objectContaining({ member_token_limit: 0 }),
        ),
      );
    });

    it("refuses to save a custom member limit that was cleared", async () => {
      const { container } = await loaded();
      const [, member] = sections(container);
      fireEvent.change(amountInput(member) as HTMLElement, {
        target: { value: "" },
      });
      await waitFor(() =>
        expect((amountInput(member) as HTMLInputElement).value).toBe(""),
      );
      governanceRequest.mockClear();
      fireEvent.click(saveButtons(container)[1]);
      await expectMessage("hub.governance.budget.positiveLimit");
      expect(governanceRequest).not.toHaveBeenCalled();
    });

    it("still saves the member default while the organization side is invalid", async () => {
      const { container } = await loaded();
      const [org] = sections(container);
      fireEvent.change(amountInput(org) as HTMLElement, {
        target: { value: "" },
      });
      await waitFor(() =>
        expect((amountInput(org) as HTMLInputElement).value).toBe(""),
      );
      governanceRequest.mockClear();
      governanceRequest.mockResolvedValue(makePolicy());
      fireEvent.click(saveButtons(container)[1]);
      await waitFor(() =>
        expect(governanceRequest).toHaveBeenCalledWith(
          "admin/model-policy",
          "PUT",
          expect.objectContaining({ member_token_limit: 5000 }),
        ),
      );
      // The invalid organization side was never submitted.
      expect(
        governanceRequest.mock.calls.some(
          (call) => call[0] === "admin/budgets/organization",
        ),
      ).toBe(false);
    });

    it("reports a rejected member save through the message API", async () => {
      const { container } = await loaded();
      governanceRequest.mockClear();
      governanceRequest.mockRejectedValue(
        new Error("Budget timezone is fixed after first use"),
      );
      fireEvent.click(saveButtons(container)[1]);
      await expectMessage("hub.governance.errors.timezoneFixed");
      expect(governanceRequest).toHaveBeenCalledWith(
        "admin/model-policy",
        "PUT",
        expect.objectContaining({ member_token_limit: 5000 }),
      );
      // A rejected save leaves the editor on the value it had before.
      const [, member] = sections(container);
      expect(amountInput(member)?.getAttribute("value")).toBe("5000");
    });

    it("sends the edited timezone with the policy", async () => {
      const { container } = await loaded();
      const [, member] = sections(container);
      await pickOption(member, 1, "Asia/Shanghai");
      await waitFor(() =>
        expect(selectionLabels(member)[1]).toBe("Asia/Shanghai"),
      );
      governanceRequest.mockClear();
      governanceRequest.mockResolvedValue(
        makePolicy({ timezone: "Asia/Shanghai" }),
      );
      fireEvent.click(saveButtons(container)[1]);
      await waitFor(() =>
        expect(governanceRequest).toHaveBeenCalledWith(
          "admin/model-policy",
          "PUT",
          expect.objectContaining({ timezone: "Asia/Shanghai" }),
        ),
      );
    });
  });

  describe("busy state", () => {
    it("marks both save buttons loading while a save is in flight", async () => {
      stubLoad(makePolicy(), makeUsage(90000));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      let release: (value: unknown) => void = () => {};
      governanceRequest.mockClear();
      governanceRequest.mockImplementation(
        () =>
          new Promise((resolve) => {
            release = resolve;
          }),
      );
      const [orgSave, memberSave] = saveButtons(container);
      fireEvent.click(orgSave);
      await waitFor(() => {
        expect(orgSave.className).toContain("ant-btn-loading");
        expect(memberSave.className).toContain("ant-btn-loading");
      });
      // antd marks a loading button with the class only; it does not set the
      // `disabled` attribute. What it does guarantee is that clicks are
      // swallowed, so assert the observable behaviour instead.
      expect(orgSave.hasAttribute("disabled")).toBe(false);
      fireEvent.click(orgSave);
      fireEvent.click(memberSave);
      expect(governanceRequest).toHaveBeenCalledTimes(1);
      release(undefined);
      await waitFor(() => {
        expect(orgSave.className).not.toContain("ant-btn-loading");
        expect(memberSave.className).not.toContain("ant-btn-loading");
      });
      await expectMessage("hub.governance.budget.saved");
    });

    it("clears the busy state after a rejected save", async () => {
      stubLoad(makePolicy(), makeUsage(90000));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      governanceRequest.mockClear();
      governanceRequest.mockRejectedValue(new Error("boom"));
      const [orgSave] = saveButtons(container);
      fireEvent.click(orgSave);
      await expectMessage("boom");
      await waitFor(() =>
        expect(orgSave.className).not.toContain("ant-btn-loading"),
      );
      expect(orgSave).toBeEnabled();
    });
  });

  describe("editor interaction", () => {
    it("offers exactly the four modes that are valid for this page", async () => {
      stubLoad(makePolicy(), makeUsage(90000));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      const [org] = sections(container);
      const dd = await openSelect(org, 0);
      // No "inherit" option: OrganizationBudget never passes allowInherit.
      expect(optionsOf(dd)).toEqual([
        "hub.governance.budget.unlimited",
        "hub.governance.budget.custom",
        "hub.governance.budget.pause",
      ]);
    });

    it("reveals the amount input only for custom mode", async () => {
      stubLoad(makePolicy({ member_token_limit: null }), makeUsage(null));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      const [org] = sections(container);
      expect(amountInput(org)).toBeNull();
      await pickOption(org, 0, "hub.governance.budget.custom");
      await waitFor(() => expect(amountInput(org)).not.toBeNull());
      expect(amountInput(org)?.getAttribute("aria-label")).toBe(
        "hub.governance.budget.monthlyLimit",
      );
      // A freshly revealed custom limit starts empty, so saving is refused.
      expect((amountInput(org) as HTMLInputElement).value).toBe("");
      await pickOption(org, 0, "hub.governance.budget.unlimited");
      await waitFor(() => expect(amountInput(org)).toBeNull());
    });

    it("keeps the two editors independent", async () => {
      stubLoad(makePolicy({ member_token_limit: 5000 }), makeUsage(90000));
      const { container } = renderPage();
      await waitFor(() =>
        expect(container.querySelectorAll("h3")).toHaveLength(2),
      );
      const [org, member] = sections(container);
      await pickOption(org, 0, "hub.governance.budget.pause");
      await waitFor(() => expect(amountInput(org)).toBeNull());
      expect(selectionLabels(org)[0]).toBe("hub.governance.budget.pause");
      expect(selectionLabels(member)[0]).toBe("hub.governance.budget.custom");
      expect(amountInput(member)?.getAttribute("value")).toBe("5000");
      expect(
        container.querySelectorAll("input[role='spinbutton']"),
      ).toHaveLength(1);
    });
  });
});
