// @vitest-environment jsdom
/**
 * SkillChannelSelect tests - the visible contract of the controlled channel
 * scope input.
 *
 * Design decisions:
 *
 * 1. The shared design stub (src/test/design-mock.ts) exports no `Select`, and
 *    that file is shared with every other suite, so this suite supplies its own
 *    `vi.mock("@agentscope-ai/design", ...)` factory instead of touching the
 *    shared stub. The stub renders one button per option (click = add that
 *    option to the current value) plus one removal button per selected value,
 *    because both directions are needed to reach every branch of the product's
 *    onChange handler. It also renders a search box that runs the product's own
 *    `filterOption` callback, so the filtering assertions test product code and
 *    not the stub.
 * 2. `t` returns the key, so assertions read the i18n keys the product chose.
 * 3. The "all" option is synthesised by the product, never passed in by the
 *    caller, so every case below passes only real channels in `options`.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

type Option = { value: string; label: string };

// The widget stub hands the product's own filterOption back to the test so the
// defensive branches can be driven directly. Every real option this component
// builds carries both a label and a value, so those branches are unreachable
// through the rendered list alone.
const design = vi.hoisted(() => ({
  filterOption: null as null | ((input: string, option?: Option) => boolean),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@agentscope-ai/design", () => {
  const Select = (props: {
    value: string[];
    options: Option[];
    onChange?: (next: string[]) => void;
    filterOption: (input: string, option?: Option) => boolean;
    disabled?: boolean;
    loading?: boolean;
    placeholder?: string;
    mode?: string;
    id?: string;
    [key: string]: unknown;
  }) => {
    design.filterOption = props.filterOption;
    const [query, setQuery] = useState("");
    const visible = query
      ? props.options.filter((option) => props.filterOption(query, option))
      : props.options;
    const rest: Record<string, unknown> = {};
    for (const key of Object.keys(props)) {
      if (key.startsWith("aria-") || key.startsWith("data-")) {
        rest[key] = props[key];
      }
    }
    return (
      <div
        data-testid="channel-select"
        data-mode={props.mode}
        data-disabled={String(Boolean(props.disabled))}
        data-loading={String(Boolean(props.loading))}
        data-placeholder={props.placeholder}
        id={props.id}
        {...rest}
      >
        {visible.map((option) => (
          <button
            key={option.value}
            type="button"
            data-testid={`option-${option.value}`}
            onClick={() => props.onChange?.([...props.value, option.value])}
          >
            {option.label}
          </button>
        ))}
        {props.value.map((selected) => (
          <button
            key={`remove-${selected}`}
            type="button"
            data-testid={`remove-${selected}`}
            onClick={() =>
              props.onChange?.(props.value.filter((item) => item !== selected))
            }
          >
            x
          </button>
        ))}
        <input
          type="search"
          data-testid="channel-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
    );
  };
  const Button = ({
    children,
    onClick,
  }: {
    children: ReactNode;
    onClick?: () => void;
  }) => (
    <button type="button" onClick={onClick}>
      {children}
    </button>
  );
  return { Select, Button };
});

import {
  SkillChannelSelect,
  type SkillChannelOptions,
} from "./SkillChannelSelect";

const CHANNELS: Option[] = [
  { value: "alpha", label: "Alpha Channel" },
  { value: "beta", label: "Second" },
];

function discovery(overrides: Partial<SkillChannelOptions> = {}) {
  return {
    options: CHANNELS,
    loading: false,
    loaded: true,
    error: false,
    onRetry: vi.fn(),
    ...overrides,
  };
}

afterEach(() => {
  design.filterOption = null;
  cleanup();
});

describe("SkillChannelSelect - option list", () => {
  it("always synthesises the 'all channels' entry ahead of the real ones", () => {
    render(<SkillChannelSelect {...discovery()} />);
    expect(screen.getByTestId("option-all")).toHaveTextContent(
      "skills.allChannels",
    );
    expect(screen.getByTestId("option-alpha")).toHaveTextContent(
      "Alpha Channel",
    );
    expect(screen.getByTestId("option-beta")).toHaveTextContent("Second");
  });

  it("keeps a selected channel that discovery still knows about, without duplicating it", () => {
    render(<SkillChannelSelect {...discovery()} value={["alpha"]} />);
    expect(screen.getAllByTestId("option-alpha")).toHaveLength(1);
  });

  it("marks an unknown selected channel as unavailable once discovery settled", () => {
    render(<SkillChannelSelect {...discovery()} value={["ghost"]} />);
    expect(screen.getByTestId("option-ghost")).toHaveTextContent(
      "ghost (skills.channelUnavailable)",
    );
  });

  it.each([
    ["still loading", { loading: true, loaded: false }],
    ["loaded but refreshing", { loading: true, loaded: true }],
    ["never loaded", { loading: false, loaded: false }],
    ["failed", { error: true, loaded: true }],
  ])(
    "shows the bare key for an unknown channel while discovery is %s",
    (_label, state) => {
      render(
        <SkillChannelSelect
          {...discovery(state as Partial<SkillChannelOptions>)}
          value={["ghost"]}
        />,
      );
      expect(screen.getByTestId("option-ghost")).toHaveTextContent("ghost");
      expect(screen.getByTestId("option-ghost").textContent).not.toContain(
        "skills.channelUnavailable",
      );
    },
  );

  it("never treats the synthetic 'all' value as an unknown channel", () => {
    render(
      <SkillChannelSelect {...discovery({ loaded: false })} value={["all"]} />,
    );
    expect(screen.getAllByTestId("option-all")).toHaveLength(1);
    expect(screen.getByTestId("option-all")).toHaveTextContent(
      "skills.allChannels",
    );
  });
});

describe("SkillChannelSelect - 'all' is exclusive", () => {
  it("collapses everything to ['all'] when the user adds 'all' to a selection", () => {
    const onChange = vi.fn();
    render(
      <SkillChannelSelect
        {...discovery()}
        value={["alpha"]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("option-all"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(["all"]);
  });

  it("drops 'all' as soon as a concrete channel is added", () => {
    const onChange = vi.fn();
    render(
      <SkillChannelSelect
        {...discovery()}
        value={["all"]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("option-beta"));
    expect(onChange).toHaveBeenCalledWith(["beta"]);
  });

  it("appends to an existing multi-selection", () => {
    const onChange = vi.fn();
    render(
      <SkillChannelSelect
        {...discovery()}
        value={["alpha"]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("option-beta"));
    expect(onChange).toHaveBeenCalledWith(["alpha", "beta"]);
  });

  it("keeps the remaining channels when one is removed", () => {
    const onChange = vi.fn();
    render(
      <SkillChannelSelect
        {...discovery()}
        value={["alpha", "beta"]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("remove-alpha"));
    expect(onChange).toHaveBeenCalledWith(["beta"]);
  });

  it("emits an empty scope when the last channel is removed", () => {
    const onChange = vi.fn();
    render(
      <SkillChannelSelect
        {...discovery()}
        value={["alpha"]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("remove-alpha"));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("stays inert when the caller did not pass an onChange handler", () => {
    render(<SkillChannelSelect {...discovery()} value={["alpha"]} />);
    expect(() =>
      fireEvent.click(screen.getByTestId("option-beta")),
    ).not.toThrow();
  });
});

describe("SkillChannelSelect - search", () => {
  it("matches case-insensitively against the label", () => {
    render(<SkillChannelSelect {...discovery()} />);
    fireEvent.change(screen.getByTestId("channel-search"), {
      target: { value: "SECOND" },
    });
    expect(screen.getByTestId("option-beta")).toBeInTheDocument();
    expect(screen.queryByTestId("option-alpha")).not.toBeInTheDocument();
  });

  it("matches against the channel key too, not only the label", () => {
    render(<SkillChannelSelect {...discovery()} />);
    fireEvent.change(screen.getByTestId("channel-search"), {
      target: { value: "alph" },
    });
    expect(screen.getByTestId("option-alpha")).toBeInTheDocument();
    expect(screen.queryByTestId("option-beta")).not.toBeInTheDocument();
  });

  it("keeps the synthetic entry reachable through its own label", () => {
    render(<SkillChannelSelect {...discovery()} />);
    fireEvent.change(screen.getByTestId("channel-search"), {
      target: { value: "skills.allChannels" },
    });
    expect(screen.getByTestId("option-all")).toBeInTheDocument();
  });
});

describe("SkillChannelSelect - defensive option filtering", () => {
  it("survives an option that carries neither label nor value", () => {
    render(<SkillChannelSelect {...discovery()} />);
    const filterOption = design.filterOption;
    expect(filterOption).not.toBeNull();
    // A missing option would throw on a plain property read; the component
    // guards it with optional chaining plus a nullish fallback.
    expect(() => filterOption?.("anything", undefined)).not.toThrow();
    expect(filterOption?.("anything", undefined)).toBe(false);
  });

  it("still matches an empty query against an empty option", () => {
    render(<SkillChannelSelect {...discovery()} />);
    // The guarded option stringifies to a single space, which contains the
    // empty query, so filtering by nothing keeps it.
    expect(design.filterOption?.("", undefined)).toBe(true);
  });

  it("treats a missing label as empty text while still matching the key", () => {
    render(<SkillChannelSelect {...discovery()} />);
    expect(design.filterOption?.("alpha", { value: "alpha" } as Option)).toBe(
      true,
    );
    expect(design.filterOption?.("zzz", { value: "alpha" } as Option)).toBe(
      false,
    );
  });
});

describe("SkillChannelSelect - disabled state", () => {
  it("is enabled while a settled discovery result is on screen", () => {
    render(<SkillChannelSelect {...discovery()} />);
    expect(screen.getByTestId("channel-select")).toHaveAttribute(
      "data-disabled",
      "false",
    );
  });

  it("is disabled while the very first discovery call is in flight", () => {
    render(
      <SkillChannelSelect {...discovery({ loading: true, loaded: false })} />,
    );
    expect(screen.getByTestId("channel-select")).toHaveAttribute(
      "data-disabled",
      "true",
    );
    expect(screen.getByTestId("channel-select")).toHaveAttribute(
      "data-loading",
      "true",
    );
  });

  it("stays usable during a background refresh of an already loaded list", () => {
    render(
      <SkillChannelSelect {...discovery({ loading: true, loaded: true })} />,
    );
    expect(screen.getByTestId("channel-select")).toHaveAttribute(
      "data-disabled",
      "false",
    );
  });

  it("is disabled when discovery failed", () => {
    render(<SkillChannelSelect {...discovery({ error: true })} />);
    expect(screen.getByTestId("channel-select")).toHaveAttribute(
      "data-disabled",
      "true",
    );
  });
});

describe("SkillChannelSelect - failure reporting", () => {
  it("announces the failure as a status region with a working retry", () => {
    const onRetry = vi.fn();
    render(<SkillChannelSelect {...discovery({ error: true, onRetry })} />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("skills.channelsLoadFailed");
    fireEvent.click(screen.getByText("common.retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders no status region while discovery is healthy", () => {
    render(<SkillChannelSelect {...discovery()} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders no status region while the first load is merely in flight", () => {
    render(
      <SkillChannelSelect {...discovery({ loading: true, loaded: false })} />,
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("SkillChannelSelect - plumbing", () => {
  it("defaults the scope to empty and asks for multiple selection", () => {
    render(<SkillChannelSelect {...discovery()} />);
    expect(screen.getByTestId("channel-select")).toHaveAttribute(
      "data-mode",
      "multiple",
    );
    expect(screen.getByTestId("channel-select")).toHaveAttribute(
      "data-placeholder",
      "skills.selectChannels",
    );
  });

  it("forwards the caller's id and aria attributes onto the widget", () => {
    render(
      <SkillChannelSelect
        {...discovery()}
        id="channel-scope"
        aria-label="Skill channels"
        aria-describedby="channel-help"
      />,
    );
    const widget = screen.getByTestId("channel-select");
    expect(widget).toHaveAttribute("id", "channel-scope");
    expect(widget).toHaveAttribute("aria-label", "Skill channels");
    expect(widget).toHaveAttribute("aria-describedby", "channel-help");
  });
});
