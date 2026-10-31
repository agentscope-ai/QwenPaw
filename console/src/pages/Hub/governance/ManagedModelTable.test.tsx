/**
 * Unit tests for ManagedModelTable, the hub-governance catalog of managed
 * models. It is a pure presentational table over props plus three local
 * filters (free text, provider, enabled state) and one async action.
 *
 * Three harness details are load bearing for the assertions below:
 *
 * 1. antd Table renders one extra `tbody tr.ant-table-measure-row` used for
 *    column measurement, so data rows must be selected with
 *    `tr.ant-table-row`; counting `tbody tr` is off by one.
 * 2. antd Select renders its dropdown into a document-level portal and, in
 *    jsdom, keeps the leaving dropdown mounted because `animationend` never
 *    fires there. `.ant-select-dropdown-hidden` alone therefore matches stale
 *    nodes; `liveDropdown()` filters on the enter/leave motion classes.
 * 3. There is no test for a rejecting `onTest`. The component wraps the call in
 *    `try { await onTest(m) } finally { ... }` with no `catch`, so its contract
 *    is that the caller handles failures; the real parent
 *    (`OrganizationModels.tsx`) does exactly that. A rejecting mock would only
 *    surface an unhandled rejection in the harness while exercising no extra
 *    product branch: the `finally` arm is already covered by the resolve path.
 * 4. `ProviderIcon` is deliberately NOT mocked. It is part of what the
 *    provider column renders, and the fallback chain the column feeds it
 *    (`provider_id || name || model name`) is only observable through the real
 *    icon's output.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, waitFor } from "@testing-library/react";
import type {
  ManagedModel,
  ModelConnection,
} from "../../../api/modules/hubGovernance";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { language: "en-US" },
  }),
}));

import ManagedModelTable from "./ManagedModelTable";
import tableStyles from "./ManagedModelTable.module.less";

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

function makeConnection(
  id: string,
  extra: Partial<ModelConnection> = {},
): ModelConnection {
  return {
    id,
    provider_id: "openai",
    name: `Conn ${id}`,
    base_url: "https://example.com/v1",
    enabled: true,
    quota_scope: "all",
    requests_per_minute: 60,
    concurrency: 4,
    has_key: true,
    revision: 1,
    ...extra,
  } as ModelConnection;
}

function makeModel(
  id: string,
  extra: Partial<ManagedModel> = {},
): ManagedModel {
  return {
    id,
    name: `Name ${id}`,
    description: "",
    connection_id: "c1",
    upstream_model: `up-${id}`,
    enabled: true,
    all_members: true,
    user_ids: [],
    input_token_limit: 1234567,
    output_token_limit: 8000,
    output_limit_field: "max_tokens",
    budget_verified: false,
    supports_image: false,
    requests_per_minute: 60,
    concurrency: 4,
    revision: 1,
    ...extra,
  } as ManagedModel;
}

type TableProps = React.ComponentProps<typeof ManagedModelTable>;

function defaultProps(extra: Partial<TableProps> = {}): TableProps {
  return {
    models: [makeModel("m1"), makeModel("m2")],
    connections: [makeConnection("c1")],
    defaultModel: null,
    onConfigure: vi.fn(),
    onToggle: vi.fn(),
    onTest: vi.fn(),
    ...extra,
  } as TableProps;
}

// ---------------------------------------------------------------------------
// dom helpers
// ---------------------------------------------------------------------------

/** antd's extra measurement row is not data; see file header, point 1. */
function dataRows(container: HTMLElement): Element[] {
  return Array.from(container.querySelectorAll("tbody tr.ant-table-row"));
}

function cellTexts(row: Element): string[] {
  return Array.from(row.querySelectorAll("td")).map(
    (td) => td.textContent ?? "",
  );
}

function nameButtons(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll(`button.${tableStyles.modelName}`),
  ) as HTMLElement[];
}

function actionButtons(container: HTMLElement, label: string): HTMLElement[] {
  return Array.from(
    container.querySelectorAll(`.${tableStyles.actions} button`),
  ).filter((b) => b.textContent === label) as HTMLElement[];
}

function switches(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll("[role='switch']"),
  ) as HTMLElement[];
}

function switchFor(container: HTMLElement, modelName: string): HTMLElement {
  const found = switches(container).filter(
    (s) =>
      s.getAttribute("aria-label") ===
      `hub.governance.models.toggleModel:${JSON.stringify({
        name: modelName,
      })}`,
  );
  expect(found).toHaveLength(1);
  return found[0];
}

/** The dropdown that is actually open right now; see file header, point 2. */
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

async function openSelectByLabel(container: HTMLElement, label: string) {
  const combo = container.querySelector(
    `input[role='combobox'][aria-label='${label}']`,
  ) as HTMLInputElement;
  expect(combo, `combobox ${label} not found`).toBeTruthy();
  fireEvent.mouseDown(combo.closest(".ant-select-selector") as HTMLElement);
  await waitFor(() => expect(combo.getAttribute("aria-expanded")).toBe("true"));
  await waitFor(() => expect(liveDropdown()).toBeTruthy());
  return liveDropdown();
}

async function pickSelectOption(
  container: HTMLElement,
  label: string,
  option: string,
) {
  const dd = await openSelectByLabel(container, label);
  const found = Array.from(
    dd.querySelectorAll(".ant-select-item-option"),
  ).filter((n) => n.textContent === option);
  expect(
    found,
    `option ${option} not in ${optionsOf(dd).join("|")}`,
  ).toHaveLength(1);
  fireEvent.click(found[0] as HTMLElement);
}

function searchInput(container: HTMLElement): HTMLInputElement {
  const found = container.querySelector(
    "input[aria-label='modelSelector.searchModels']",
  ) as HTMLInputElement;
  expect(found).toBeTruthy();
  return found;
}

/** Real column headers only; antd adds `ant-table-measure-cell` siblings. */
function headerTexts(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("thead th.ant-table-cell"))
    .filter((th) => !th.className.includes("ant-table-measure-cell"))
    .map((th) => th.textContent ?? "");
}

// ---------------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------------

describe("ManagedModelTable", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.clearAllMocks();
  });

  describe("table frame", () => {
    it("renders the seven columns the catalog exposes", () => {
      const { container } = render(<ManagedModelTable {...defaultProps()} />);
      expect(
        container.querySelectorAll(`.${tableStyles.catalog}`),
      ).toHaveLength(1);
      expect(headerTexts(container)).toEqual([
        "tokenUsage.model",
        "models.provider",
        "models.maxInputLengthLabel",
        "models.maxTokensLabel",
        "hub.governance.models.access",
        "common.enabled",
        "",
      ]);
    });

    it("renders one row per model and nothing else", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [makeModel("m1"), makeModel("m2"), makeModel("m3")],
          })}
        />,
      );
      expect(dataRows(container)).toHaveLength(3);
      // The measurement row exists but is excluded by the helper.
      expect(container.querySelectorAll("tbody tr")).toHaveLength(4);
    });

    it("renders an empty table without inventing rows", () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models: [] })} />,
      );
      expect(dataRows(container)).toHaveLength(0);
      expect(container.querySelectorAll(".ant-empty")).toHaveLength(1);
    });

    it("renders the three filters with accessible names", () => {
      const { container } = render(<ManagedModelTable {...defaultProps()} />);
      expect(
        container.querySelectorAll(`.${tableStyles.filters}`),
      ).toHaveLength(1);
      expect(searchInput(container)).toBeTruthy();
      expect(
        container.querySelector(
          "input[role='combobox'][aria-label='models.provider']",
        ),
      ).toBeTruthy();
      expect(
        container.querySelector(
          "input[role='combobox'][aria-label='hub.table.status']",
        ),
      ).toBeTruthy();
      // No pagination while everything fits on one page.
      expect(container.querySelectorAll(".ant-pagination")).toHaveLength(0);
    });

    it("lists the provider options from the connections prop", async () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            connections: [
              makeConnection("c1"),
              makeConnection("c2", { name: "Second" }),
            ],
          })}
        />,
      );
      const dd = await openSelectByLabel(container, "models.provider");
      expect(optionsOf(dd)).toEqual(["Conn c1", "Second"]);
    });

    it("lists both status options", async () => {
      const { container } = render(<ManagedModelTable {...defaultProps()} />);
      const dd = await openSelectByLabel(container, "hub.table.status");
      expect(optionsOf(dd)).toEqual(["common.enabled", "common.disabled"]);
    });
  });

  describe("model column", () => {
    it("exposes the model name as a configure button", () => {
      const onConfigure = vi.fn();
      const models = [makeModel("m1"), makeModel("m2", { name: "Second" })];
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models, onConfigure })} />,
      );
      expect(nameButtons(container).map((b) => b.textContent)).toEqual([
        "Name m1",
        "Second",
      ]);
      fireEvent.click(nameButtons(container)[1]);
      expect(onConfigure).toHaveBeenCalledTimes(1);
      expect(onConfigure).toHaveBeenCalledWith(models[1]);
    });

    it("shows the upstream model only when it differs from the display name", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [
              makeModel("m1", { name: "Same", upstream_model: "Same" }),
              makeModel("m2", { name: "Shown", upstream_model: "different" }),
            ],
          })}
        />,
      );
      const rows = dataRows(container);
      expect(rows[0].querySelectorAll("small")).toHaveLength(0);
      expect(rows[1].querySelectorAll("small")).toHaveLength(1);
      expect(rows[1].querySelector("small")?.textContent).toBe("different");
    });

    it("badges only the model that is the organization default", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [makeModel("m1"), makeModel("m2")],
            defaultModel: "m2",
          })}
        />,
      );
      const rows = dataRows(container);
      expect(rows[0].querySelectorAll(".ant-tag")).toHaveLength(0);
      expect(rows[1].querySelectorAll(".ant-tag")).toHaveLength(1);
      expect(rows[1].querySelector(".ant-tag")?.textContent).toBe(
        "hub.governance.models.default",
      );
    });

    it("badges nothing when there is no default model", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [makeModel("m1"), makeModel("m2")],
            defaultModel: null,
          })}
        />,
      );
      expect(container.querySelectorAll(".ant-tag")).toHaveLength(0);
    });

    it("matches a default model id that is not in the list without badging", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [makeModel("m1")],
            defaultModel: "ghost",
          })}
        />,
      );
      expect(container.querySelectorAll(".ant-tag")).toHaveLength(0);
      expect(dataRows(container)).toHaveLength(1);
    });
  });

  describe("provider column", () => {
    it("renders the connection name next to a real provider icon", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            connections: [makeConnection("c1", { provider_id: "openai" })],
          })}
        />,
      );
      const row = dataRows(container)[0];
      expect(
        row.querySelector(`.${tableStyles.provider} > span`)?.textContent,
      ).toBe("Conn c1");
      // Known providers render the CDN image, tagged with the provider id.
      const icon = row.querySelector("[data-provider-id='openai']");
      expect(icon?.tagName).toBe("IMG");
    });

    it("falls back to the connection name when provider_id is null", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            connections: [
              makeConnection("c1", { provider_id: null, name: "OnlyName" }),
            ],
          })}
        />,
      );
      const row = dataRows(container)[0];
      expect(
        row.querySelector(`.${tableStyles.provider} > span`)?.textContent,
      ).toBe("OnlyName");
      // The fallback feeds the letter-avatar branch, which titles itself.
      expect(row.querySelector("[title='OnlyName']")).toBeTruthy();
    });

    it("falls back to the model name when the connection has neither", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [makeModel("m1", { name: "ModelName" })],
            connections: [
              makeConnection("c1", { provider_id: null, name: "" }),
            ],
          })}
        />,
      );
      const row = dataRows(container)[0];
      const avatar = row.querySelector("[title='ModelName']") as HTMLElement;
      // provider_id is null and the connection name is empty, so the fallback
      // chain lands on the model name and renders the letter-avatar branch.
      expect(avatar).not.toBeNull();
      expect(avatar.tagName).toBe("DIV");
      expect(avatar.textContent).toBe("M");
      expect(row.querySelectorAll("img")).toHaveLength(0);
      expect(
        row.querySelector(`.${tableStyles.provider} > span`)?.textContent,
      ).toBe("");
    });

    it("falls back to the model name for a model whose connection is missing", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [
              makeModel("m1", { name: "Orphan", connection_id: "ghost" }),
            ],
            connections: [makeConnection("c1")],
          })}
        />,
      );
      const row = dataRows(container)[0];
      // No connection row at all: the name cell is empty and the icon falls back.
      expect(
        row.querySelector(`.${tableStyles.provider} > span`)?.textContent,
      ).toBe("");
      expect(row.querySelector("[title='Orphan']")).toBeTruthy();
    });

    it("marks a disabled connection with an accessible dot", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            connections: [makeConnection("c1", { enabled: false })],
          })}
        />,
      );
      const row = dataRows(container)[0];
      const dot = row.querySelector(`.${tableStyles.disabledDot}`);
      expect(dot).toBeTruthy();
      expect(dot?.getAttribute("role")).toBe("img");
      expect(dot?.getAttribute("aria-label")).toBe(
        "hub.governance.models.connectionDisabled",
      );
    });

    it("marks a model whose connection is absent the same way", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [makeModel("m1", { connection_id: "ghost" })],
          })}
        />,
      );
      const row = dataRows(container)[0];
      const dot = row.querySelector(`.${tableStyles.disabledDot}`);
      // A missing connection is indistinguishable from a disabled one here,
      // because `!c?.enabled` is true when `c` is undefined.
      expect(dot).not.toBeNull();
      expect(dot?.getAttribute("role")).toBe("img");
      expect(dot?.getAttribute("aria-label")).toBe(
        "hub.governance.models.connectionDisabled",
      );
    });

    it("omits the dot for an enabled connection", () => {
      const { container } = render(<ManagedModelTable {...defaultProps()} />);
      expect(
        container.querySelectorAll(`.${tableStyles.disabledDot}`),
      ).toHaveLength(0);
    });

    it("renders the hub-managed provider as the paw glyph", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            connections: [makeConnection("c1", { provider_id: "hub-managed" })],
          })}
        />,
      );
      const row = dataRows(container)[0];
      expect(
        row.querySelector("[data-provider-id='hub-managed']")?.tagName,
      ).toBe("svg");
    });
  });

  describe("limit columns", () => {
    it("prints compact tokens with the full value as a title", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [
              makeModel("m1", {
                input_token_limit: 1234567,
                output_token_limit: 8000,
              }),
            ],
          })}
        />,
      );
      const cells = cellTexts(dataRows(container)[0]);
      expect(cells[2]).toBe("1.2M");
      expect(cells[3]).toBe("8K");
      const titles = Array.from(
        dataRows(container)[0].querySelectorAll("span[title]"),
      ).map((n) => n.getAttribute("title"));
      expect(titles).toContain("1,234,567");
      expect(titles).toContain("8,000");
    });

    it("prints zero limits as zero rather than as the provider default", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [
              makeModel("m1", { input_token_limit: 0, output_token_limit: 0 }),
            ],
          })}
        />,
      );
      const cells = cellTexts(dataRows(container)[0]);
      expect(cells[2]).toBe("0");
      expect(cells[3]).toBe("0");
    });

    it("substitutes the provider default label for a null output limit", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [makeModel("m1", { output_token_limit: null })],
          })}
        />,
      );
      const cells = cellTexts(dataRows(container)[0]);
      expect(cells[3]).toBe("models.providerDefault");
      // No title span is rendered in that branch.
      expect(
        dataRows(container)[0]
          .querySelectorAll("td")[3]
          .querySelectorAll("span[title]"),
      ).toHaveLength(0);
    });
  });

  describe("access column", () => {
    it("labels an all-member model as such and ignores user_ids", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [
              makeModel("m1", { all_members: true, user_ids: ["u1", "u2"] }),
            ],
          })}
        />,
      );
      expect(cellTexts(dataRows(container)[0])[4]).toBe(
        "hub.governance.models.allMembersLabel",
      );
    });

    it("reports the member count for a restricted model", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [
              makeModel("m1", {
                all_members: false,
                user_ids: ["u1", "u2", "u3"],
              }),
              makeModel("m2", { all_members: false, user_ids: [] }),
            ],
          })}
        />,
      );
      const rows = dataRows(container);
      expect(cellTexts(rows[0])[4]).toBe(
        `hub.governance.models.memberCount:${JSON.stringify({ count: 3 })}`,
      );
      expect(cellTexts(rows[1])[4]).toBe(
        `hub.governance.models.memberCount:${JSON.stringify({ count: 0 })}`,
      );
    });
  });

  describe("enabled column", () => {
    it("mirrors each model's enabled flag onto its switch", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [
              makeModel("m1", { enabled: true }),
              makeModel("m2", { enabled: false }),
            ],
          })}
        />,
      );
      expect(switchFor(container, "Name m1").getAttribute("aria-checked")).toBe(
        "true",
      );
      expect(switchFor(container, "Name m2").getAttribute("aria-checked")).toBe(
        "false",
      );
    });

    it("labels each switch with its own model name", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [
              makeModel("m1", { name: "Alpha" }),
              makeModel("m2", { name: "Beta" }),
            ],
          })}
        />,
      );
      expect(
        switches(container).map((s) => s.getAttribute("aria-label")),
      ).toEqual([
        `hub.governance.models.toggleModel:${JSON.stringify({
          name: "Alpha",
        })}`,
        `hub.governance.models.toggleModel:${JSON.stringify({ name: "Beta" })}`,
      ]);
    });

    it("passes the model and the next value to onToggle", () => {
      const onToggle = vi.fn();
      const models = [
        makeModel("m1", { enabled: true }),
        makeModel("m2", { enabled: false }),
      ];
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models, onToggle })} />,
      );
      fireEvent.click(switchFor(container, "Name m1"));
      expect(onToggle).toHaveBeenCalledTimes(1);
      expect(onToggle).toHaveBeenCalledWith(models[0], false);
      fireEvent.click(switchFor(container, "Name m2"));
      expect(onToggle).toHaveBeenCalledTimes(2);
      expect(onToggle).toHaveBeenLastCalledWith(models[1], true);
    });

    it("shows the updating model as loading and locks every other switch", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [makeModel("m1"), makeModel("m2"), makeModel("m3")],
            updatingItem: "model:m2",
          })}
        />,
      );
      const target = switchFor(container, "Name m2");
      expect(target.className).toContain("ant-switch-loading");
      expect(target.hasAttribute("disabled")).toBe(true);
      for (const name of ["Name m1", "Name m3"]) {
        expect(switchFor(container, name).hasAttribute("disabled")).toBe(true);
      }
    });

    it("unlocks the other switches once the update is for something else", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [makeModel("m1"), makeModel("m2")],
            updatingItem: "connection:c1",
          })}
        />,
      );
      // A non-model update still counts as an in-flight update, so the switches
      // stay locked; only a cleared updatingItem frees them.
      expect(switchFor(container, "Name m1").hasAttribute("disabled")).toBe(
        true,
      );
      const { container: free } = render(
        <ManagedModelTable
          {...defaultProps({ models: [makeModel("m1"), makeModel("m2")] })}
        />,
      );
      expect(switchFor(free, "Name m1").hasAttribute("disabled")).toBe(false);
      expect(switchFor(free, "Name m2").hasAttribute("disabled")).toBe(false);
      // The locked render above is the control: same models, same props, the
      // only difference is the `updatingItem` that is being reported.
      expect(switchFor(container, "Name m1").hasAttribute("disabled")).toBe(
        true,
      );
    });
  });

  describe("actions column", () => {
    it("offers configure and test-connection per row", () => {
      const { container } = render(<ManagedModelTable {...defaultProps()} />);
      expect(
        actionButtons(container, "hub.governance.models.configure"),
      ).toHaveLength(2);
      expect(
        actionButtons(container, "hub.governance.models.testConnection"),
      ).toHaveLength(2);
    });

    it("calls onConfigure from the action button as well", () => {
      const onConfigure = vi.fn();
      const models = [makeModel("m1"), makeModel("m2")];
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models, onConfigure })} />,
      );
      fireEvent.click(
        actionButtons(container, "hub.governance.models.configure")[1],
      );
      expect(onConfigure).toHaveBeenCalledWith(models[1]);
      expect(onConfigure).toHaveBeenCalledTimes(1);
    });

    it("disables test-connection for a disabled model", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [
              makeModel("m1", { enabled: true }),
              makeModel("m2", { enabled: false }),
            ],
          })}
        />,
      );
      const buttons = actionButtons(
        container,
        "hub.governance.models.testConnection",
      );
      expect(buttons[0].hasAttribute("disabled")).toBe(false);
      expect(buttons[1].hasAttribute("disabled")).toBe(true);
    });

    it("disables test-connection for a model on a disabled connection", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            connections: [makeConnection("c1", { enabled: false })],
          })}
        />,
      );
      const buttons = actionButtons(
        container,
        "hub.governance.models.testConnection",
      );
      expect(buttons.every((b) => b.hasAttribute("disabled"))).toBe(true);
    });

    it("disables test-connection for a model whose connection is missing", () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [makeModel("m1", { connection_id: "ghost" })],
          })}
        />,
      );
      expect(
        actionButtons(
          container,
          "hub.governance.models.testConnection",
        )[0].hasAttribute("disabled"),
      ).toBe(true);
    });

    it("awaits onTest and shows the spinner only on the tested row", async () => {
      const onTest = vi.fn();
      let release: (() => void) | null = null;
      onTest.mockImplementation(
        () =>
          new Promise<void>((resolve) => {
            release = resolve;
          }),
      );
      const models = [makeModel("m1"), makeModel("m2")];
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models, onTest })} />,
      );
      const buttons = actionButtons(
        container,
        "hub.governance.models.testConnection",
      );
      await act(async () => {
        fireEvent.click(buttons[0]);
      });
      expect(onTest).toHaveBeenCalledTimes(1);
      expect(onTest).toHaveBeenCalledWith(models[0]);
      const loading = actionButtons(
        container,
        "hub.governance.models.testConnection",
      );
      expect(loading[0].className).toContain("ant-btn-loading");
      expect(loading[1].className).not.toContain("ant-btn-loading");
      // The sibling row is locked while a test is in flight.
      expect(loading[1].hasAttribute("disabled")).toBe(true);
      await act(async () => {
        (release as unknown as () => void)();
      });
      await waitFor(() =>
        expect(
          actionButtons(
            container,
            "hub.governance.models.testConnection",
          ).every((b) => !b.className.includes("ant-btn-loading")),
        ).toBe(true),
      );
    });
  });

  describe("text filter", () => {
    const models = [
      makeModel("m1", { name: "Alpha", upstream_model: "gpt-4o" }),
      makeModel("m2", { name: "Beta", upstream_model: "claude-3" }),
      makeModel("m3", { name: "Gamma", upstream_model: "ALPHA-upstream" }),
    ];

    it("matches on the display name", async () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models })} />,
      );
      fireEvent.change(searchInput(container), { target: { value: "beta" } });
      await waitFor(() => expect(dataRows(container)).toHaveLength(1));
      expect(cellTexts(dataRows(container)[0])[0]).toContain("Beta");
    });

    it("matches on the upstream model too", async () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models })} />,
      );
      fireEvent.change(searchInput(container), { target: { value: "gpt-4o" } });
      await waitFor(() => expect(dataRows(container)).toHaveLength(1));
      expect(cellTexts(dataRows(container)[0])[0]).toContain("Alpha");
    });

    it("matches case-insensitively on either side", async () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models })} />,
      );
      fireEvent.change(searchInput(container), {
        target: { value: "ALPHA-UPSTREAM" },
      });
      await waitFor(() => expect(dataRows(container)).toHaveLength(1));
      expect(cellTexts(dataRows(container)[0])[0]).toContain("Gamma");
    });

    it("ignores surrounding whitespace in the query", async () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models })} />,
      );
      fireEvent.change(searchInput(container), {
        target: { value: "   beta   " },
      });
      await waitFor(() => expect(dataRows(container)).toHaveLength(1));
    });

    it("treats a whitespace-only query as no filter", async () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models })} />,
      );
      fireEvent.change(searchInput(container), { target: { value: "beta" } });
      await waitFor(() => expect(dataRows(container)).toHaveLength(1));
      fireEvent.change(searchInput(container), { target: { value: "   " } });
      await waitFor(() => expect(dataRows(container)).toHaveLength(3));
    });

    it("shows the empty state when nothing matches", async () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models })} />,
      );
      fireEvent.change(searchInput(container), {
        target: { value: "no-such-model" },
      });
      await waitFor(() =>
        expect(container.querySelectorAll(".ant-empty")).toHaveLength(1),
      );
      expect(dataRows(container)).toHaveLength(0);
    });

    it("clears the query through the allowClear affordance", async () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models })} />,
      );
      const input = searchInput(container);
      fireEvent.change(input, { target: { value: "beta" } });
      await waitFor(() => expect(dataRows(container)).toHaveLength(1));
      const clear = container.querySelector(".ant-input-clear-icon");
      expect(clear).toBeTruthy();
      fireEvent.click(clear as HTMLElement);
      await waitFor(() => expect(dataRows(container)).toHaveLength(3));
      expect(input.value).toBe("");
    });
  });

  describe("select filters", () => {
    const models = [
      makeModel("m1", { enabled: true, connection_id: "c1" }),
      makeModel("m2", { enabled: false, connection_id: "c2" }),
      makeModel("m3", { enabled: true, connection_id: "c2" }),
    ];
    const connections = [
      makeConnection("c1"),
      makeConnection("c2", { name: "Second" }),
    ];

    it("filters by provider", async () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models, connections })} />,
      );
      await pickSelectOption(container, "models.provider", "Second");
      await waitFor(() => expect(dataRows(container)).toHaveLength(2));
      expect(cellTexts(dataRows(container)[0])[1]).toBe("Second");
    });

    it("filters by enabled state", async () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models, connections })} />,
      );
      await pickSelectOption(container, "hub.table.status", "common.disabled");
      await waitFor(() => expect(dataRows(container)).toHaveLength(1));
      expect(cellTexts(dataRows(container)[0])[0]).toContain("Name m2");
    });

    it("combines provider, status and text filters", async () => {
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models, connections })} />,
      );
      await pickSelectOption(container, "models.provider", "Second");
      await waitFor(() => expect(dataRows(container)).toHaveLength(2));
      await pickSelectOption(container, "hub.table.status", "common.enabled");
      await waitFor(() => expect(dataRows(container)).toHaveLength(1));
      expect(cellTexts(dataRows(container)[0])[0]).toContain("Name m3");
      fireEvent.change(searchInput(container), { target: { value: "m2" } });
      await waitFor(() => expect(dataRows(container)).toHaveLength(0));
      expect(container.querySelectorAll(".ant-empty")).toHaveLength(1);
    });

    it("resets the page to one when a filter still matches several pages", async () => {
      // Zero-padded names so a substring match selects a predictable slice:
      // "m3" matches m30..m39 only, "m" matches all forty.
      const many = Array.from({ length: 40 }, (_, i) => {
        const key = String(i).padStart(2, "0");
        return makeModel(`m${key}`, {
          name: `Name m${key}`,
          upstream_model: `up-${key}`,
        });
      });
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: many,
            connections: [makeConnection("c1")],
          })}
        />,
      );
      expect(dataRows(container)).toHaveLength(15);
      expect(container.querySelectorAll(".ant-pagination-item")).toHaveLength(
        3,
      );
      fireEvent.click(
        container.querySelector(".ant-pagination-item-2") as HTMLElement,
      );
      await waitFor(() =>
        expect(
          container.querySelector(".ant-pagination-item-2")?.className,
        ).toContain("ant-pagination-item-active"),
      );
      expect(nameButtons(container)[0].textContent).toBe("Name m15");

      // A filter matching every row keeps the pager but must jump back to 1.
      fireEvent.change(searchInput(container), { target: { value: "m" } });
      await waitFor(() => expect(dataRows(container)).toHaveLength(15));
      expect(
        container.querySelector(".ant-pagination-item-1")?.className,
      ).toContain("ant-pagination-item-active");
      expect(nameButtons(container)[0].textContent).toBe("Name m00");
    });

    it("hides the pager when a filter narrows the result to one page", async () => {
      const many = Array.from({ length: 40 }, (_, i) => {
        const key = String(i).padStart(2, "0");
        return makeModel(`m${key}`, {
          name: `Name m${key}`,
          upstream_model: `up-${key}`,
        });
      });
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: many,
            connections: [makeConnection("c1")],
          })}
        />,
      );
      fireEvent.click(
        container.querySelector(".ant-pagination-item-2") as HTMLElement,
      );
      await waitFor(() =>
        expect(
          container.querySelector(".ant-pagination-item-2")?.className,
        ).toContain("ant-pagination-item-active"),
      );
      fireEvent.change(searchInput(container), { target: { value: "m3" } });
      await waitFor(() => expect(dataRows(container)).toHaveLength(10));
      await waitFor(() =>
        expect(container.querySelectorAll(".ant-pagination")).toHaveLength(0),
      );
      expect(nameButtons(container)[0].textContent).toBe("Name m30");
    });
  });

  describe("sorting", () => {
    it("sorts by display name when the header is clicked", async () => {
      const { container } = render(
        <ManagedModelTable
          {...defaultProps({
            models: [
              makeModel("m1", { name: "Charlie" }),
              makeModel("m2", { name: "alpha" }),
              makeModel("m3", { name: "Bravo" }),
            ],
          })}
        />,
      );
      const header = container.querySelector(
        "th.ant-table-column-has-sorters",
      ) as HTMLElement;
      expect(header).toBeTruthy();
      // Only the model column declares a sorter.
      expect(
        container.querySelectorAll("th.ant-table-column-has-sorters"),
      ).toHaveLength(1);
      expect(nameButtons(container).map((b) => b.textContent)).toEqual([
        "Charlie",
        "alpha",
        "Bravo",
      ]);
      fireEvent.click(header);
      await waitFor(() =>
        expect(header.className).toContain("ant-table-column-sort"),
      );
      // localeCompare is case-insensitive about ordering here: alpha < Bravo < Charlie.
      expect(nameButtons(container).map((b) => b.textContent)).toEqual([
        "alpha",
        "Bravo",
        "Charlie",
      ]);
      fireEvent.click(header);
      await waitFor(() =>
        expect(nameButtons(container).map((b) => b.textContent)).toEqual([
          "Charlie",
          "Bravo",
          "alpha",
        ]),
      );
    });
  });

  describe("pagination", () => {
    it("pages fifteen rows at a time and hides the pager on a single page", () => {
      const models = Array.from({ length: 16 }, (_, i) => makeModel(`m${i}`));
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models })} />,
      );
      expect(container.querySelectorAll(".ant-pagination-item")).toHaveLength(
        2,
      );
      expect(dataRows(container)).toHaveLength(15);
      const pager = container.querySelector(".ant-pagination") as HTMLElement;
      // The page size is fixed: no size changer is offered.
      expect(pager.querySelectorAll(".ant-pagination-options")).toHaveLength(0);
      fireEvent.click(
        container.querySelector(".ant-pagination-item-2") as HTMLElement,
      );
      expect(dataRows(container)).toHaveLength(1);
    });

    it("shows no pager at exactly fifteen rows", () => {
      const models = Array.from({ length: 15 }, (_, i) => makeModel(`m${i}`));
      const { container } = render(
        <ManagedModelTable {...defaultProps({ models })} />,
      );
      expect(dataRows(container)).toHaveLength(15);
      expect(container.querySelectorAll(".ant-pagination")).toHaveLength(0);
    });
  });
});
