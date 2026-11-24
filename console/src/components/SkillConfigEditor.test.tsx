// @vitest-environment jsdom
/**
 * SkillConfigEditor - the single text area where a skill's YAML/JSON front-matter
 * config is edited. Rendered from two places, and both are checked by this suite
 * because the component is shared by two pages:
 *   - `pages/Agent/Skills/components/SkillDrawer.tsx:388` (imported at `:16`)
 *   - `pages/Settings/SkillPool/components/PoolSkillDrawer.tsx:305` (imported at `:23`)
 *
 * Visible contract under test:
 *
 *   1. the text area is reachable by its accessible name, which is the translated
 *      `skills.config` key (not a hard-coded English string), so assistive tech
 *      finds the same label the UI shows;
 *   2. `rows` is pinned at 4 - it is the one layout attribute the product sets
 *      explicitly rather than through CSS;
 *   3. an EMPTY config object is normalized to an empty text area: `value.trim()
 *      === "{}"` renders "", so a freshly created skill never shows the user a
 *      literal `{}` they have to delete. The trim matters - `{}` padded with
 *      spaces or a trailing newline is normalized too;
 *   4. that normalization is deliberately NARROW: `{ }` (a space between the
 *      braces) and any non-empty config are shown verbatim, so a user's own
 *      formatting is never rewritten;
 *   5. every keystroke is forwarded as the RAW new value - the product unwraps
 *      `e.target.value` and hands the parent a plain string, never the event;
 *   6. the placeholder is a DERIVED schema built from `requirements.require_envs`:
 *      each required env var becomes a key whose value is the literal "...",
 *      pretty-printed with 2-space indent, so the user can copy the shape. The
 *      exact string is asserted against the same `JSON.stringify` call the
 *      product makes (measured via node, not typed from memory);
 *   7. the schema is absent - an empty placeholder, not a literal "undefined" -
 *      when `requirements` is omitted entirely, when `require_envs` is an empty
 *      array, or when `requirements` is present but has no `require_envs` key.
 *      All three shapes must behave alike because the product reads it through
 *      optional chaining;
 *   8. `require_bins` and `require_mcps` (the other two fields of
 *      SkillRequirements) must NOT leak into the placeholder;
 *   9. env var ORDER and DUPLICATES are preserved as the product built them
 *      (`Object.fromEntries` on the array in order), so a repeated name collapses
 *      to one key - pinned because it is the observable result of that call.
 *
 * Harness notes (measured facts):
 *
 * - the shared design stub (`src/test/design-mock.ts`) DOES export `Input.TextArea`
 *   and renders it as a real `<textarea>` forwarding every prop, so no local
 *   `vi.mock` of the design lib is needed and the stub is untouched.
 * - `styles.editor` is a CSS-module class; the wrapper is located through the
 *   imported styles object, matching `components/ApprovalCard/ApprovalCard.test.tsx`.
 * - `t` returns the key verbatim, so assertions pin the i18n key the product asks
 *   for. Key checked present in `src/locales/en.json`: `skills.config`
 *   (= "Config").
 * - expected placeholder strings are built here with the SAME
 *   `JSON.stringify(Object.fromEntries(...), null, 2)` call the product makes, so
 *   this suite pins the derivation rather than a hard-coded literal that would
 *   silently drift if the indent changed. One case also asserts a literal
 *   (measured with node: `{\n  "ONLY_ONE": "..."\n}`) to pin the indent itself.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SkillRequirements } from "../api/types/skill";

const h = vi.hoisted(() => ({
  stableT: (key: string, options?: Record<string, unknown>) => {
    h.tCalls.push([key, options ?? null]);
    return key;
  },
  stableI18n: { language: "en" },
  tCalls: [] as Array<[string, Record<string, unknown> | null]>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: h.stableT, i18n: h.stableI18n }),
}));

import { SkillConfigEditor } from "./SkillConfigEditor";
import styles from "./SkillConfigEditor.module.less";

/** The same derivation the product performs, kept in one place. */
function expectedPlaceholder(requireEnvs: string[]): string {
  return JSON.stringify(
    Object.fromEntries(requireEnvs.map((name) => [name, "..."])),
    null,
    2,
  );
}

function requirementsOf(
  overrides: Partial<SkillRequirements> = {},
): SkillRequirements {
  return {
    require_bins: [],
    require_envs: [],
    require_mcps: [],
    ...overrides,
  };
}

function renderEditor(
  value: string,
  onChange = vi.fn(),
  requirements?: SkillRequirements,
) {
  const utils = render(
    <SkillConfigEditor
      value={value}
      onChange={onChange}
      requirements={requirements}
    />,
  );
  return { value, onChange, requirements, ...utils };
}

const textArea = () => screen.getByLabelText("skills.config");

beforeEach(() => {
  h.tCalls.length = 0;
});

afterEach(() => {
  cleanup();
});

describe("SkillConfigEditor surface", () => {
  it("exposes the text area under the translated skills.config label", () => {
    renderEditor("");
    expect(textArea().tagName).toBe("TEXTAREA");
    expect(h.tCalls.map(([key]) => key)).toEqual(["skills.config"]);
  });

  it("pins the explicit row count at 4", () => {
    renderEditor("");
    expect(textArea()).toHaveAttribute("rows", "4");
  });

  it("wraps the field in the CSS-module editor container", () => {
    const { container } = renderEditor("");
    expect(container.querySelector(`.${styles.editor}`)).not.toBeNull();
    expect(
      container.querySelector(`.${styles.editor}`)?.querySelector("textarea"),
    ).not.toBeNull();
  });
});

describe("SkillConfigEditor empty-object normalization", () => {
  it("shows an empty text area for a bare empty config object", () => {
    renderEditor("{}");
    expect(textArea()).toHaveValue("");
  });

  it("normalizes an empty object padded with spaces and a trailing newline", () => {
    for (const raw of ["  {}  ", "{}\n", "\n{}\t"]) {
      const { unmount } = renderEditor(raw);
      expect(textArea(), `value ${JSON.stringify(raw)}`).toHaveValue("");
      unmount();
    }
  });

  it("keeps a spaced-apart empty object verbatim because the guard is narrow", () => {
    renderEditor("{ }");
    expect(textArea()).toHaveValue("{ }");
  });

  it("keeps every non-empty config verbatim, including its own formatting", () => {
    const configs = [
      '{"a":1}',
      '{\n  "model": "qwen-max"\n}',
      "model: qwen-max",
      "{} extra",
    ];
    for (const raw of configs) {
      const { unmount } = renderEditor(raw);
      expect(textArea(), `value ${JSON.stringify(raw)}`).toHaveValue(raw);
      unmount();
    }
  });

  it("keeps the empty string empty rather than turning it into an object", () => {
    renderEditor("");
    expect(textArea()).toHaveValue("");
  });
});

describe("SkillConfigEditor change forwarding", () => {
  it("hands the parent the raw new string, not the event object", () => {
    const onChange = vi.fn();
    renderEditor("{}", onChange);
    fireEvent.change(textArea(), { target: { value: '{"a": 1}' } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('{"a": 1}');
    expect(typeof onChange.mock.calls[0][0]).toBe("string");
  });

  it("forwards an emptied field as the empty string", () => {
    const onChange = vi.fn();
    renderEditor('{"a": 1}', onChange);
    fireEvent.change(textArea(), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("forwards a bare empty object typed by the user unchanged", () => {
    const onChange = vi.fn();
    renderEditor("", onChange);
    fireEvent.change(textArea(), { target: { value: "{}" } });
    expect(onChange).toHaveBeenCalledWith("{}");
  });
});

describe("SkillConfigEditor placeholder schema", () => {
  it("builds the placeholder from require_envs with the product's own derivation", () => {
    const envs = ["OPENAI_API_KEY", "HTTP_PROXY"];
    renderEditor("", vi.fn(), requirementsOf({ require_envs: envs }));
    expect(textArea()).toHaveAttribute(
      "placeholder",
      expectedPlaceholder(envs),
    );
  });

  it("pins the literal shape and the 2-space indent for one env var", () => {
    renderEditor("", vi.fn(), requirementsOf({ require_envs: ["ONLY_ONE"] }));
    expect(textArea()).toHaveAttribute(
      "placeholder",
      '{\n  "ONLY_ONE": "..."\n}',
    );
  });

  it("keeps env var order as declared", () => {
    const envs = ["ZETA", "ALPHA", "MIDDLE"];
    renderEditor("", vi.fn(), requirementsOf({ require_envs: envs }));
    const placeholder = textArea().getAttribute("placeholder") ?? "";
    expect(placeholder.indexOf("ZETA")).toBeLessThan(
      placeholder.indexOf("ALPHA"),
    );
    expect(placeholder.indexOf("ALPHA")).toBeLessThan(
      placeholder.indexOf("MIDDLE"),
    );
    expect(placeholder).toBe(expectedPlaceholder(envs));
  });

  it("collapses a duplicated env var into a single key", () => {
    const envs = ["DUP", "OTHER", "DUP"];
    renderEditor("", vi.fn(), requirementsOf({ require_envs: envs }));
    const placeholder = textArea().getAttribute("placeholder") ?? "";
    expect(placeholder.match(/DUP/g) ?? []).toHaveLength(1);
    expect(placeholder).toBe(expectedPlaceholder(envs));
  });

  it("does not leak require_bins or require_mcps into the schema", () => {
    renderEditor(
      "",
      vi.fn(),
      requirementsOf({
        require_envs: ["ONLY_ENV"],
        require_bins: ["ffmpeg"],
        require_mcps: ["some-mcp"],
      }),
    );
    const placeholder = textArea().getAttribute("placeholder") ?? "";
    expect(placeholder).toContain("ONLY_ENV");
    expect(placeholder).not.toContain("ffmpeg");
    expect(placeholder).not.toContain("some-mcp");
    expect(placeholder).toBe(expectedPlaceholder(["ONLY_ENV"]));
  });
});

describe("SkillConfigEditor placeholder absence", () => {
  it("leaves the placeholder empty when requirements is omitted", () => {
    renderEditor("");
    expect(textArea()).toHaveAttribute("placeholder", "");
  });

  it("leaves the placeholder empty when require_envs is an empty array", () => {
    renderEditor("", vi.fn(), requirementsOf({ require_envs: [] }));
    expect(textArea()).toHaveAttribute("placeholder", "");
  });

  it("leaves the placeholder empty when requirements has no require_envs key", () => {
    const partial = {
      require_bins: ["ffmpeg"],
    } as unknown as SkillRequirements;
    renderEditor("", vi.fn(), partial);
    expect(textArea()).toHaveAttribute("placeholder", "");
  });

  it("never renders the words undefined or null into the placeholder", () => {
    renderEditor("");
    const placeholder = textArea().getAttribute("placeholder") ?? "";
    expect(placeholder).not.toContain("undefined");
    expect(placeholder).not.toContain("null");
  });
});
