/**
 * Unit tests for AgentMultiSelect, the controlled agent-id picker used inside
 * BackupScopeForm.
 *
 * Facts that shaped this suite (each one measured with throwaway probes that
 * were deleted before this file landed):
 *
 * 1. antd renders for real here. The component imports `Checkbox, Select`
 *    straight from `antd` (no design-system alias is involved), so the option
 *    list, the checkbox markup and the search filtering are the genuine
 *    article and can be asserted directly.
 * 2. The dropdown only exists after a `mouseDown` on `.ant-select-selector`.
 *    Before that, `.ant-select-item-option` count is 0. Options render inside a
 *    portal under `document.body`, so every assertion about the option list is
 *    scoped to the dropdown that belongs to the render under test, and
 *    `afterEach` wipes `document.body` so a portal left behind by an earlier
 *    case cannot be counted by the next one.
 * 3. The component is controlled, and a `vi.fn()` parent never re-renders: it
 *    would keep handing the same `value` prop back, so "the sentinel flips
 *    from select-all to deselect-all after you use it" would pass for the
 *    wrong reason. Those cases therefore drive real state through `Harness`
 *    and read the state back out of a rendered `<output>` node instead of
 *    trusting the spy's arguments.
 * 4. Option labels come from the mocked `t`, so they are the raw i18n keys
 *    (`backup.selectAll` / `backup.deselectAll` / `Name-a1 (a1)`). Asserting
 *    keys rather than English copy keeps these tests from breaking when the
 *    locale files change wording.
 * 5. `optionRender` puts `pointer-events: none` on the inner checkbox *label*,
 *    not on the checkbox span. That inline style is the whole point of the
 *    comment in the component (the Select owns the click), so it is pinned as
 *    a contract: if it disappears, the inner Checkbox starts swallowing
 *    clicks and a plain "click an option" assertion would still look green.
 * 6. `maxTagCount="responsive"` collapses two selected tags into a single
 *    `+ 1 ...` node under jsdom, because jsdom reports zero width for
 *    everything. The tag area is therefore asserted by "it collapses", never
 *    by a literal tag count.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, fireEvent, cleanup } from "@testing-library/react";
import { useState } from "react";

vi.mock("react-i18next", () => {
  // Built once per factory call, so `t` keeps a stable identity.
  const t = (key: string, opts?: Record<string, unknown>) =>
    opts ? `${key}:${JSON.stringify(opts)}` : key;
  return {
    useTranslation: () => ({
      t,
      i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
    }),
  };
});

import AgentMultiSelect from "./AgentMultiSelect";
import type { AgentSummary } from "@/api/types/agents";

const SELECT_ALL = "backup.selectAll";
const DESELECT_ALL = "backup.deselectAll";
const PLACEHOLDER = "backup.agentsPlaceholder";

function makeAgent(id: string): AgentSummary {
  // Full object literal on purpose: the component only reads `id` and `name`,
  // but a partial literal would not satisfy AgentSummary and the type guard is
  // what keeps these props honest.
  return {
    id,
    name: `Name-${id}`,
    description: "",
    workspace_dir: "",
    enabled: true,
    backend: "react",
  };
}

const AGENTS = [makeAgent("a1"), makeAgent("a2"), makeAgent("a3")];
const ALL_IDS = ["a1", "a2", "a3"];

afterEach(() => {
  cleanup();
  // Options live in a body-level portal; drop everything so the next case
  // starts from an empty document.
  document.body.innerHTML = "";
});

/** Stateful parent: the only way to observe `allSelected` actually flipping. */
function Harness({
  agents,
  initial,
}: {
  agents: AgentSummary[];
  initial: string[];
}) {
  const [value, setValue] = useState<string[]>(initial);
  return (
    <>
      <AgentMultiSelect agents={agents} value={value} onChange={setValue} />
      <output data-testid="value">{JSON.stringify(value)}</output>
    </>
  );
}

function selector(): HTMLElement {
  const el = document.querySelector(".ant-select-selector");
  if (!el) throw new Error("select was not rendered");
  return el as HTMLElement;
}

function dropdown(): HTMLElement {
  const nodes = document.querySelectorAll(".ant-select-dropdown");
  if (nodes.length !== 1) {
    throw new Error(`expected exactly one dropdown, found ${nodes.length}`);
  }
  return nodes[0] as HTMLElement;
}

function openDropdown(): HTMLElement {
  fireEvent.mouseDown(selector());
  return dropdown();
}

function options(): HTMLElement[] {
  return Array.from(
    dropdown().querySelectorAll<HTMLElement>(".ant-select-item-option"),
  );
}

function optionTexts(): string[] {
  return options().map((o) => o.textContent ?? "");
}

function checkedFlags(): boolean[] {
  return options().map(
    (o) => o.querySelector(".ant-checkbox-checked") !== null,
  );
}

describe("AgentMultiSelect closed state", () => {
  it("shows the translated placeholder and renders no options until opened", () => {
    render(<AgentMultiSelect agents={AGENTS} value={[]} onChange={vi.fn()} />);
    expect(
      document.querySelector(".ant-select-selection-placeholder")?.textContent,
    ).toBe(PLACEHOLDER);
    expect(document.querySelectorAll(".ant-select-item-option").length).toBe(0);
  });

  it("renders a multiple-mode select with a clear affordance once something is chosen", () => {
    render(
      <AgentMultiSelect agents={AGENTS} value={["a1"]} onChange={vi.fn()} />,
    );
    expect(selector().closest(".ant-select")?.className).toContain(
      "ant-select-multiple",
    );
    // allowClear only shows its node while there is something to clear.
    expect(document.querySelector(".ant-select-clear")).not.toBeNull();
  });
});

describe("AgentMultiSelect option list", () => {
  it("prepends the sentinel and labels every agent as name plus id", () => {
    render(<AgentMultiSelect agents={AGENTS} value={[]} onChange={vi.fn()} />);
    openDropdown();
    expect(optionTexts()).toEqual([
      SELECT_ALL,
      "Name-a1 (a1)",
      "Name-a2 (a2)",
      "Name-a3 (a3)",
    ]);
  });

  it("renders the sentinel even when there are no agents at all", () => {
    render(<AgentMultiSelect agents={[]} value={[]} onChange={vi.fn()} />);
    openDropdown();
    expect(optionTexts()).toEqual([SELECT_ALL]);
  });

  it("keeps the sentinel labelled select-all and unchecked while nothing is selected", () => {
    render(<AgentMultiSelect agents={AGENTS} value={[]} onChange={vi.fn()} />);
    openDropdown();
    expect(optionTexts()[0]).toBe(SELECT_ALL);
    expect(checkedFlags()).toEqual([false, false, false, false]);
  });

  it("flips the sentinel to deselect-all and checks every option once all agents are selected", () => {
    render(
      <AgentMultiSelect agents={AGENTS} value={ALL_IDS} onChange={vi.fn()} />,
    );
    openDropdown();
    expect(optionTexts()[0]).toBe(DESELECT_ALL);
    expect(checkedFlags()).toEqual([true, true, true, true]);
  });

  it("leaves the sentinel unchecked but keeps the chosen agent checked on a partial selection", () => {
    render(
      <AgentMultiSelect agents={AGENTS} value={["a2"]} onChange={vi.fn()} />,
    );
    openDropdown();
    expect(optionTexts()[0]).toBe(SELECT_ALL);
    expect(checkedFlags()).toEqual([false, false, true, false]);
  });

  it("treats an empty agent list as not-all-selected even though both lengths are zero", () => {
    // allSelected is `agents.length > 0 && value.length === agents.length`, so
    // the length guard is what stops "no agents" from reading as "all agents".
    render(<AgentMultiSelect agents={[]} value={[]} onChange={vi.fn()} />);
    openDropdown();
    expect(optionTexts()[0]).toBe(SELECT_ALL);
    expect(checkedFlags()).toEqual([false]);
  });

  it("keeps the option list virtualised so a long agent list does not render every row", () => {
    const many = Array.from({ length: 40 }, (_, i) => makeAgent(`agent-${i}`));
    render(<AgentMultiSelect agents={many} value={[]} onChange={vi.fn()} />);
    openDropdown();
    expect(dropdown().querySelector(".rc-virtual-list")).not.toBeNull();
    // 41 entries exist, but the virtual list renders only a window of them.
    expect(options().length).toBeLessThan(41);
    expect(options().length).toBeGreaterThan(0);
  });

  it("pins the pointer-events guard that stops the inner checkbox eating the click", () => {
    render(<AgentMultiSelect agents={AGENTS} value={[]} onChange={vi.fn()} />);
    openDropdown();
    const wrapper = options()[0].querySelector(".ant-checkbox-wrapper");
    expect(wrapper).not.toBeNull();
    expect((wrapper as HTMLElement).style.pointerEvents).toBe("none");
  });
});

describe("AgentMultiSelect sentinel handling", () => {
  it("selects every agent when the sentinel is clicked on an empty selection", () => {
    const onChange = vi.fn();
    render(<AgentMultiSelect agents={AGENTS} value={[]} onChange={onChange} />);
    openDropdown();
    fireEvent.click(options()[0]);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toEqual(ALL_IDS);
  });

  it("clears the selection when the sentinel is clicked while everything is selected", () => {
    const onChange = vi.fn();
    render(
      <AgentMultiSelect agents={AGENTS} value={ALL_IDS} onChange={onChange} />,
    );
    openDropdown();
    fireEvent.click(options()[0]);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toEqual([]);
  });

  it("reports an empty selection when the sentinel is clicked with no agents to select", () => {
    // Same branch as select-all, but the mapped list is empty.
    const onChange = vi.fn();
    render(<AgentMultiSelect agents={[]} value={[]} onChange={onChange} />);
    openDropdown();
    fireEvent.click(options()[0]);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toEqual([]);
  });

  it("toggles between all and none across two real renders", () => {
    render(<Harness agents={AGENTS} initial={[]} />);
    const shown = () =>
      JSON.parse(
        document.querySelector<HTMLElement>('[data-testid="value"]')
          ?.textContent ?? "null",
      ) as string[];
    expect(shown()).toEqual([]);

    openDropdown();
    fireEvent.click(options()[0]);
    expect(shown()).toEqual(ALL_IDS);

    // The sentinel now reads deselect-all because the state really moved.
    openDropdown();
    expect(optionTexts()[0]).toBe(DESELECT_ALL);
    fireEvent.click(options()[0]);
    expect(shown()).toEqual([]);
  });
});

describe("AgentMultiSelect ordinary option handling", () => {
  it("passes a single id through untouched when one agent is picked", () => {
    const onChange = vi.fn();
    render(<AgentMultiSelect agents={AGENTS} value={[]} onChange={onChange} />);
    openDropdown();
    fireEvent.click(options()[1]);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toEqual(["a1"]);
  });

  it("accumulates ids when a second agent is picked on top of an existing one", () => {
    const onChange = vi.fn();
    render(
      <AgentMultiSelect agents={AGENTS} value={["a1"]} onChange={onChange} />,
    );
    openDropdown();
    fireEvent.click(options()[2]);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toEqual(["a1", "a2"]);
  });

  it("removes an id when an already-selected agent is clicked again", () => {
    const onChange = vi.fn();
    render(
      <AgentMultiSelect agents={AGENTS} value={["a1"]} onChange={onChange} />,
    );
    openDropdown();
    fireEvent.click(options()[1]);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toEqual([]);
  });

  it("filters the option list by label because optionFilterProp is label", () => {
    render(<AgentMultiSelect agents={AGENTS} value={[]} onChange={vi.fn()} />);
    openDropdown();
    const input = document.querySelector(
      ".ant-select-selection-search-input",
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "a2" } });
    expect(optionTexts()).toEqual(["Name-a2 (a2)"]);
  });

  it("emits an empty selection when the clear affordance is used", () => {
    const onChange = vi.fn();
    render(
      <AgentMultiSelect agents={AGENTS} value={["a1"]} onChange={onChange} />,
    );
    const clear = document.querySelector(".ant-select-clear");
    expect(clear).not.toBeNull();
    fireEvent.mouseDown(clear as HTMLElement);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toEqual([]);
  });

  it("collapses the tag area under responsive maxTagCount instead of listing every id", () => {
    render(
      <AgentMultiSelect
        agents={AGENTS}
        value={["a1", "a2"]}
        onChange={vi.fn()}
      />,
    );
    const items = Array.from(
      document.querySelectorAll(".ant-select-selection-item"),
    ).map((n) => n.textContent ?? "");
    // jsdom measures everything as zero width, so the responsive mode keeps a
    // single overflow node. Asserting the collapse (not a tag count) is what
    // survives a real browser.
    expect(items.length).toBe(1);
    expect(items[0]).toContain("+");
  });
});
