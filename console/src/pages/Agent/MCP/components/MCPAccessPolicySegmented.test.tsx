/**
 * MCPAccessPolicySegmented - the three-way ask/allow/deny picker shared by
 * both panels of the MCP access policy modal: the client panel renders it for
 * `policy.default_effect` (MCPAccessClientPanel.tsx:56) and the tool panel
 * renders one per tool group for `group.defaultEffect`
 * (MCPAccessToolPanel.tsx:70).
 *
 * Visible contract under test:
 *
 *   1. exactly three options, in ask / allow / deny order, whose labels come
 *      from the caller-supplied `effectLabel`; the component owns no wording of
 *      its own, so an option whose label stopped coming from `effectLabel`
 *      would be a real regression;
 *   2. the selected option is the `value` prop, i.e. the control is fully
 *      controlled and keeps no selection state of its own;
 *   3. picking another option reports that option's effect verbatim through
 *      `onChange` - the `as MCPAccessEffect` cast on the antd payload must not
 *      rewrite or widen the value;
 *   4. the three CSS custom properties the stylesheet consumes are re-derived
 *      from the CURRENT value, carrying the exact colour set the product
 *      declares per effect (ask amber / allow green / deny red);
 *   5. `effectLabel` is consulted for all three keys on every render,
 *      including the currently selected one (so a selected label cannot go
 *      stale);
 *   6. re-rendering with a different `effectLabel` or `value` updates both the
 *      labels and the colour set, i.e. nothing is memoised on first render.
 *
 * Harness notes (measured facts, not assumptions):
 *
 * - antd's real `<Segmented>` is used. The component imports it straight from
 *   "antd", and the shared stub `src/test/design-mock.ts` has no `Segmented`
 *   export, so there is neither a stub to override nor one that could silently
 *   swallow the assertions. antd renders each option as a radio input wrapped
 *   in its label, which is what the queries below drive.
 * - The module class name is read from the very same CSS-modules import the
 *   component uses, matching the sibling suite
 *   `src/pages/Settings/Models/components/cards/ProviderGroupCard.test.tsx`.
 * - No i18n stub is needed: this component never calls `useTranslation`, all
 *   wording arrives through the `effectLabel` prop.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MCPAccessEffect } from "../../../../api/types";
import styles from "../index.module.less";
import { MCPAccessPolicySegmented } from "./MCPAccessPolicySegmented";

/** The three effects, in the order the component lists them. */
const EFFECT_ORDER: MCPAccessEffect[] = ["ask", "allow", "deny"];

/**
 * Colour set declared per effect in the component's own
 * POLICY_SEGMENT_COLORS table, transcribed verbatim from the source.
 */
const EXPECTED_COLORS: Record<
  MCPAccessEffect,
  { bg: string; border: string; text: string }
> = {
  ask: {
    bg: "rgba(245, 158, 11, 0.24)",
    border: "rgba(217, 119, 6, 0.36)",
    text: "#8a4b00",
  },
  allow: {
    bg: "rgba(34, 197, 94, 0.22)",
    border: "rgba(22, 163, 74, 0.35)",
    text: "#17643a",
  },
  deny: {
    bg: "rgba(239, 68, 68, 0.2)",
    border: "rgba(220, 38, 38, 0.34)",
    text: "#9f1f26",
  },
};

/** CSS custom property names the stylesheet reads off the segmented root. */
const VAR_BG = "--mcp-policy-segment-bg";
const VAR_BORDER = "--mcp-policy-segment-border";
const VAR_TEXT = "--mcp-policy-segment-text";

/** Labels are always derived, so the rendered text reveals which key was asked. */
function labelFor(effect: MCPAccessEffect): string {
  return `effect-${effect}`;
}

function effectLabel(effect: MCPAccessEffect): string {
  return labelFor(effect);
}

/** The segmented root, i.e. the node the three CSS variables are set on. */
function segmentedRoot(container: HTMLElement): HTMLElement {
  const root = container.querySelector(`.${styles.accessPolicySegmented}`);
  expect(root, "segmented root with the module class name").not.toBeNull();
  return root as HTMLElement;
}

function renderSegmented(
  value: MCPAccessEffect,
  overrides: {
    onChange?: (effect: MCPAccessEffect) => void;
    effectLabel?: (effect: MCPAccessEffect) => string;
  } = {},
) {
  const onChange = overrides.onChange ?? vi.fn();
  const utils = render(
    <MCPAccessPolicySegmented
      value={value}
      onChange={onChange}
      effectLabel={overrides.effectLabel ?? effectLabel}
    />,
  );
  return { onChange, ...utils };
}

function optionOf(name: string): HTMLElement {
  return screen.getByRole("radio", { name });
}

/**
 * Visible label of a radio option.
 *
 * Read from a real render dump rather than assumed: antd renders each option as
 * `<label class="ant-segmented-item"><input type="radio"
 * class="ant-segmented-item-input"><div class="ant-segmented-item-label">TEXT
 * </div></label>`, so the accessible name resolves through the wrapping label
 * while the input node itself carries no text at all. Reading
 * `radio.textContent` therefore always yields the empty string.
 */
function radioLabel(radio: HTMLElement): string {
  const label = radio.closest("label");
  expect(label, "radio wrapped in its segmented label").not.toBeNull();
  return label?.textContent ?? "";
}

describe("MCPAccessPolicySegmented", () => {
  it("lists exactly the three effects, in ask/allow/deny order, labelled via effectLabel", () => {
    const { container } = renderSegmented("ask");

    const radios = within(segmentedRoot(container)).getAllByRole("radio");
    expect(radios).toHaveLength(EFFECT_ORDER.length);
    expect(radios.map(radioLabel)).toEqual(EFFECT_ORDER.map(labelFor));
  });

  it("marks the value prop as the selected option", () => {
    const { container } = renderSegmented("allow");

    const selected = within(segmentedRoot(container))
      .getAllByRole("radio")
      .filter((node) => (node as HTMLInputElement).checked);
    expect(selected).toHaveLength(1);
    expect(radioLabel(selected[0])).toBe(labelFor("allow"));
  });

  it("keeps no selection state of its own: the same value stays selected across effects", () => {
    // Fully controlled: whatever `value` says is what is selected, so each of
    // the three effects can be the selected one and none of the others.
    for (const value of EFFECT_ORDER) {
      const { container, unmount } = renderSegmented(value);
      const checked = within(segmentedRoot(container))
        .getAllByRole("radio")
        .filter((node) => (node as HTMLInputElement).checked);
      expect(checked.map(radioLabel)).toEqual([labelFor(value)]);
      unmount();
    }
  });

  it.each([
    ["ask", "allow"],
    ["ask", "deny"],
    ["allow", "ask"],
    ["allow", "deny"],
    ["deny", "ask"],
    ["deny", "allow"],
  ])(
    "reports the picked effect verbatim when %s is the value and %s is clicked",
    (current, next) => {
      const onChange = vi.fn();
      renderSegmented(current as MCPAccessEffect, {
        onChange,
      });

      fireEvent.click(optionOf(labelFor(next as MCPAccessEffect)));

      expect(onChange).toHaveBeenCalledTimes(1);
      // Verbatim: the value must be the effect string itself, not an event
      // object, an index or a widened/upper-cased variant of it.
      expect(onChange).toHaveBeenCalledWith(next);
      expect(onChange.mock.calls[0][0]).toBe(next);
    },
  );

  it.each(EFFECT_ORDER)(
    "derives the three policy CSS variables from the %s value",
    (value) => {
      const { container } = renderSegmented(value);
      const root = segmentedRoot(container);
      const expected = EXPECTED_COLORS[value];

      expect(root.style.getPropertyValue(VAR_BG)).toBe(expected.bg);
      expect(root.style.getPropertyValue(VAR_BORDER)).toBe(expected.border);
      expect(root.style.getPropertyValue(VAR_TEXT)).toBe(expected.text);
    },
  );

  it("gives every effect its own colour set, so the three arms are distinguishable", () => {
    // Guards against a regression where all three effects resolve to one entry
    // of the colour table (the per-effect assertions above would still pass if
    // the table itself collapsed to identical values).
    const seen = EFFECT_ORDER.map((value) => {
      const { container, unmount } = renderSegmented(value);
      const root = segmentedRoot(container);
      const triple = [
        root.style.getPropertyValue(VAR_BG),
        root.style.getPropertyValue(VAR_BORDER),
        root.style.getPropertyValue(VAR_TEXT),
      ];
      unmount();
      return triple.join("|");
    });

    expect(new Set(seen).size).toBe(EFFECT_ORDER.length);
  });

  it("asks effectLabel for all three keys, including the selected one", () => {
    const spy = vi.fn(effectLabel);
    renderSegmented("deny", { effectLabel: spy });

    const asked = spy.mock.calls.map((call) => call[0]);
    for (const effect of EFFECT_ORDER) {
      expect(asked).toContain(effect);
    }
    // Nothing is skipped for the selected effect: it still has to be labelled.
    expect(spy).toHaveBeenCalledWith("deny");
  });

  it("re-derives labels and colours when the props change", () => {
    const firstLabel = vi.fn((effect: MCPAccessEffect) => `one-${effect}`);
    const secondLabel = vi.fn((effect: MCPAccessEffect) => `two-${effect}`);
    const { container, rerender } = render(
      <MCPAccessPolicySegmented
        value="ask"
        onChange={vi.fn()}
        effectLabel={firstLabel}
      />,
    );

    expect(screen.getByRole("radio", { name: "one-ask" })).toBeTruthy();
    expect(segmentedRoot(container).style.getPropertyValue(VAR_BG)).toBe(
      EXPECTED_COLORS.ask.bg,
    );

    rerender(
      <MCPAccessPolicySegmented
        value="deny"
        onChange={vi.fn()}
        effectLabel={secondLabel}
      />,
    );

    expect(screen.getByRole("radio", { name: "two-deny" })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "one-ask" })).toBeNull();
    const root = segmentedRoot(container);
    expect(root.style.getPropertyValue(VAR_BG)).toBe(EXPECTED_COLORS.deny.bg);
    expect(root.style.getPropertyValue(VAR_TEXT)).toBe(
      EXPECTED_COLORS.deny.text,
    );
  });
});
