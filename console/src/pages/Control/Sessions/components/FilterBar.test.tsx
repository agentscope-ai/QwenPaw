// @vitest-environment jsdom
/**
 * FilterBar - the three-control filter row of Control > Sessions, rendered from
 * `pages/Control/Sessions/index.tsx:225` (imported at `:8`) inside the page
 * header's `extra` slot.
 *
 * Visible contract under test:
 *
 *   1. the row has exactly three controls in a fixed order - title input, user
 *      id input, channel select - each asking for its own translated
 *      placeholder, so a swapped pair of inputs is caught by the placeholder
 *      and not only by the value;
 *   2. every control is controlled: what it shows is exactly the prop it was
 *      given, and typing reports the raw event value through its own callback
 *      (no trim, no lowercasing, no cross-talk between the two inputs);
 *   3. `isMobile` is the ONLY thing that changes layout, and it changes all
 *      three controls at once: mobile gives every control a full-width style,
 *      desktop gives the two inputs a fixed 200px width with an 8px right
 *      margin and the select a fixed 180px width;
 *   4. the channel select normalises in BOTH directions - an empty
 *      `filterChannel` is handed to the widget as `undefined` (so the
 *      placeholder shows instead of a blank option) while a real channel is
 *      handed through untouched, and the widget reporting nothing (`undefined`)
 *      reaches the caller as the empty string, never as `undefined`;
 *   5. the option list mirrors `uniqueChannels` one-for-one and in order, an
 *      empty list renders no option at all, and picking an option reports that
 *      option's own value.
 *
 * Harness notes (measured, not assumed):
 *
 * - The shared `src/test/design-mock.ts` stub does NOT export `Select` (probed:
 *   it exports IconButton / Dropdown / Button / Input / Switch / Modal / Tag /
 *   Tooltip / Form / InputNumber / Spin / Tabs), and this product uses
 *   `Select.Option`, so this file overrides the design module with
 *   `importActual`: `Input` is wrapped by a recorder that then delegates to the
 *   real stub (a genuine `<input>`, so its inline style is observable), and
 *   `Select` becomes a widget that exposes the props it received plus one
 *   button per option. The shared stub is untouched.
 * - `allowClear` cannot be read off the DOM (React drops the camelCase
 *   attribute), which is exactly why the Input props are recorded rather than
 *   scraped: the assertions in (1) and (3) read the recorded props.
 * - `t` returns the key verbatim and records its call order. Keys checked
 *   present in `src/locales/en.json`: `sessions.filterTitle`,
 *   `sessions.filterUserId`, `sessions.filterChannel`.
 * - The product also puts the stable class names `sessions-filter-input` (twice)
 *   and `sessions-filter-select` on the controls; those are asserted because
 *   they are the only hooks a browser-level test could use, and they are what
 *   keeps the two inputs distinguishable for callers.
 */
import { cleanup, fireEvent, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type RecordedInput = Record<string, unknown>;

const h = vi.hoisted(() => ({
  stableT: (key: string) => {
    h.tCalls.push(key);
    return key;
  },
  stableI18n: { language: "en" },
  tCalls: [] as string[],
  // Props of every rendered Input, in DOM order (title first, then user id).
  inputProps: [] as RecordedInput[],
  // Props the Select received on its most recent render.
  selectProps: null as RecordedInput | null,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: h.stableT, i18n: h.stableI18n }),
}));

vi.mock("@agentscope-ai/design", async () => {
  const actual = await vi.importActual<Record<string, unknown>>(
    "@agentscope-ai/design",
  );
  const RealInput = actual.Input as (props: RecordedInput) => React.ReactNode;

  const Input = (props: RecordedInput) => {
    h.inputProps.push(props);
    return <>{RealInput(props)}</>;
  };

  interface OptionProps {
    value: string;
    children?: React.ReactNode;
    onPick?: (value: string) => void;
  }
  const Option = ({ value, children, onPick }: OptionProps) => (
    <button
      type="button"
      data-testid={`channel-option-${value}`}
      data-value={value}
      onClick={() => onPick?.(value)}
    >
      {children}
    </button>
  );

  const Select = Object.assign(
    (props: RecordedInput) => {
      h.selectProps = props;
      const onPick = props.onChange as (value: string) => void;
      const children = props.children as React.ReactNode;
      return (
        <div
          data-testid="channel-select"
          className={String(props.className ?? "")}
          data-placeholder={String(props.placeholder)}
          data-value={String(props.value)}
          data-allow-clear={String(Boolean(props.allowClear))}
        >
          <button
            type="button"
            data-testid="channel-select-clear"
            onClick={() => onPick(undefined as unknown as string)}
          >
            clear
          </button>
          {React.Children.map(children, (child) =>
            React.isValidElement(child)
              ? React.cloneElement(child as React.ReactElement<OptionProps>, {
                  onPick,
                })
              : child,
          )}
        </div>
      );
    },
    { Option },
  );

  return { ...actual, Input, Select };
});

import { FilterBar } from "./FilterBar";
import styles from "../index.module.less";

type Props = React.ComponentProps<typeof FilterBar>;

function propsOf(overrides: Partial<Props> = {}): Props {
  return {
    filterUserId: "",
    filterChannel: "",
    filterTitle: "",
    uniqueChannels: [],
    onUserIdChange: vi.fn(),
    onChannelChange: vi.fn(),
    onTitleChange: vi.fn(),
    ...overrides,
  } as Props;
}

function renderBar(overrides: Partial<Props> = {}) {
  const props = propsOf(overrides);
  const utils = render(<FilterBar {...props} />);
  return { props, ...utils };
}

/** The two text inputs, in DOM order: title first, then user id. */
const inputsOf = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("input")) as HTMLInputElement[];

beforeEach(() => {
  h.tCalls.length = 0;
  h.inputProps.length = 0;
  h.selectProps = null;
});

afterEach(() => {
  cleanup();
});

describe("FilterBar controls", () => {
  it("renders the three controls in a fixed order with their own placeholders", () => {
    const { container, getByTestId } = renderBar();
    const [title, userId] = inputsOf(container);
    expect(title.getAttribute("placeholder")).toBe("sessions.filterTitle");
    expect(userId.getAttribute("placeholder")).toBe("sessions.filterUserId");
    expect(getByTestId("channel-select").dataset.placeholder).toBe(
      "sessions.filterChannel",
    );
    expect(h.tCalls).toEqual([
      "sessions.filterTitle",
      "sessions.filterUserId",
      "sessions.filterChannel",
    ]);
  });

  it("keeps the stable class names callers rely on", () => {
    const { container, getByTestId } = renderBar();
    const [title, userId] = inputsOf(container);
    expect(title.className).toBe("sessions-filter-input");
    expect(userId.className).toBe("sessions-filter-input");
    expect(getByTestId("channel-select").className).toBe(
      "sessions-filter-select",
    );
    expect(container.querySelector(`.${styles.filterBar}`)).not.toBeNull();
  });

  it("marks both inputs as clearable", () => {
    renderBar();
    expect(h.inputProps).toHaveLength(2);
    expect(h.inputProps[0].allowClear).toBe(true);
    expect(h.inputProps[1].allowClear).toBe(true);
  });
});

describe("FilterBar controlled values", () => {
  it("shows exactly the props it was given", () => {
    const { container } = renderBar({
      filterTitle: "nightly run",
      filterUserId: "user-42",
      filterChannel: "console",
      uniqueChannels: ["console"],
    });
    const [title, userId] = inputsOf(container);
    expect(title.value).toBe("nightly run");
    expect(userId.value).toBe("user-42");
    expect(h.selectProps!.value).toBe("console");
  });

  it("reports the raw title value through onTitleChange only", () => {
    const onTitleChange = vi.fn();
    const onUserIdChange = vi.fn();
    const { container } = renderBar({ onTitleChange, onUserIdChange });
    fireEvent.change(inputsOf(container)[0], {
      target: { value: "  Padded Title " },
    });
    expect(onTitleChange).toHaveBeenCalledTimes(1);
    expect(onTitleChange.mock.calls[0][0]).toBe("  Padded Title ");
    expect(onUserIdChange).not.toHaveBeenCalled();
  });

  it("reports the raw user id value through onUserIdChange only", () => {
    const onTitleChange = vi.fn();
    const onUserIdChange = vi.fn();
    const { container } = renderBar({ onTitleChange, onUserIdChange });
    fireEvent.change(inputsOf(container)[1], { target: { value: "MiXeD" } });
    expect(onUserIdChange).toHaveBeenCalledTimes(1);
    expect(onUserIdChange.mock.calls[0][0]).toBe("MiXeD");
    expect(onTitleChange).not.toHaveBeenCalled();
  });

  it("does not report anything before the user types", () => {
    const onTitleChange = vi.fn();
    const onUserIdChange = vi.fn();
    const onChannelChange = vi.fn();
    renderBar({ onTitleChange, onUserIdChange, onChannelChange });
    expect(onTitleChange).not.toHaveBeenCalled();
    expect(onUserIdChange).not.toHaveBeenCalled();
    expect(onChannelChange).not.toHaveBeenCalled();
  });
});

describe("FilterBar layout switch", () => {
  it("gives every control a full width style on mobile", () => {
    renderBar({ isMobile: true });
    expect(h.inputProps[0].style).toEqual({ width: "100%" });
    expect(h.inputProps[1].style).toEqual({ width: "100%" });
    expect(h.selectProps!.style).toEqual({ width: "100%" });
  });

  it("gives the inputs a fixed width plus a right margin on desktop", () => {
    renderBar({ isMobile: false });
    expect(h.inputProps[0].style).toEqual({ width: 200, marginRight: 8 });
    expect(h.inputProps[1].style).toEqual({ width: 200, marginRight: 8 });
    expect(h.selectProps!.style).toEqual({ width: 180 });
  });

  it("defaults to the desktop layout when isMobile is omitted", () => {
    const { container } = renderBar();
    const [title] = inputsOf(container);
    expect(title.style.width).toBe("200px");
    expect(title.style.marginRight).toBe("8px");
  });
});

describe("FilterBar channel select", () => {
  it("hands an empty channel to the widget as undefined", () => {
    renderBar({ filterChannel: "" });
    expect(h.selectProps!.value).toBeUndefined();
  });

  it("hands a real channel through untouched", () => {
    renderBar({ filterChannel: "dingtalk", uniqueChannels: ["dingtalk"] });
    expect(h.selectProps!.value).toBe("dingtalk");
  });

  it("reports the picked option's own value", () => {
    const onChannelChange = vi.fn();
    const { getByTestId } = renderBar({
      filterChannel: "",
      uniqueChannels: ["console", "dingtalk"],
      onChannelChange,
    });
    fireEvent.click(getByTestId("channel-option-dingtalk"));
    expect(onChannelChange).toHaveBeenCalledTimes(1);
    expect(onChannelChange.mock.calls[0][0]).toBe("dingtalk");
  });

  it("normalises a cleared selection to the empty string", () => {
    const onChannelChange = vi.fn();
    const { getByTestId } = renderBar({
      filterChannel: "console",
      uniqueChannels: ["console"],
      onChannelChange,
    });
    fireEvent.click(getByTestId("channel-select-clear"));
    expect(onChannelChange).toHaveBeenCalledTimes(1);
    expect(onChannelChange.mock.calls[0][0]).toBe("");
  });

  it("marks the select as clearable", () => {
    renderBar({ uniqueChannels: [] });
    expect(h.selectProps!.allowClear).toBe(true);
  });
});

describe("FilterBar option list", () => {
  it("renders one option per channel, in the given order", () => {
    const { queryAllByTestId, container } = renderBar({
      uniqueChannels: ["console", "dingtalk", "web"],
    });
    const options = Array.from(
      container.querySelectorAll('[data-testid^="channel-option-"]'),
    );
    expect(options).toHaveLength(3);
    expect(options.map((option) => option.textContent)).toEqual([
      "console",
      "dingtalk",
      "web",
    ]);
    expect(queryAllByTestId("channel-option-console")).toHaveLength(1);
  });

  it("renders no option for an empty channel list", () => {
    const { container } = renderBar({ uniqueChannels: [] });
    expect(
      container.querySelectorAll('[data-testid^="channel-option-"]'),
    ).toHaveLength(0);
  });
});
