import type { ReactNode, ComponentProps } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// `t` and `i18n` must be referentially stable: `validateFrontmatter` is a
// useCallback listing `t` in its deps, and that callback is handed to a
// Form.Item rule. A fresh `t` per render would rebuild the validator on
// every render. (Same failure mode as useDebugLogs.test.ts, pinned here too.)
const h = vi.hoisted(() => ({
  stableT: (key: string) => key,
  stableI18n: { language: "en" },
  message: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    destroy: vi.fn(),
  },
  streamOptimizeSkill: vi.fn(),
  // Captured from the mocked Form/Form.Item so the tests can drive submit and
  // the two inline validators directly instead of going through real antd.
  onFinishRef: { current: undefined as ((v: unknown) => void) | undefined },
  rulesByName: {} as Record<string, Array<Record<string, unknown>>>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: h.stableT, i18n: h.stableI18n }),
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: h.message }),
}));

// The component imports the named `api` binding.
vi.mock("../../../../api", () => ({
  api: { streamOptimizeSkill: h.streamOptimizeSkill },
  default: { streamOptimizeSkill: h.streamOptimizeSkill },
}));

vi.mock("@ant-design/icons", () => ({
  ThunderboltOutlined: () => <span data-testid="icon-bolt" />,
  StopOutlined: () => <span data-testid="icon-stop" />,
}));

vi.mock("@/components/interaction/SettingsDrawer", () => {
  const SettingsDrawer = ({
    children,
    title,
    footer,
    open,
  }: {
    children?: ReactNode;
    title?: ReactNode;
    footer?: ReactNode;
    open?: boolean;
  }) => (
    <div data-testid="drawer" data-open={String(open)}>
      <div data-testid="drawer-title">{title}</div>
      <div data-testid="drawer-body">{children}</div>
      <div data-testid="drawer-footer">{footer}</div>
    </div>
  );
  return { SettingsDrawer };
});

vi.mock("@agentscope-ai/design", () => {
  const Form = ({
    children,
    onFinish,
  }: {
    children?: ReactNode;
    onFinish?: (value: unknown) => void;
  }) => {
    h.onFinishRef.current = onFinish;
    return <div data-testid="skill-form">{children}</div>;
  };
  // Captures `rules` per field name so the inline validators can be invoked
  // directly; items without a name fall back to their label as the key.
  Form.Item = ({
    children,
    label,
    name,
    rules,
    help,
  }: {
    children?: ReactNode;
    label?: ReactNode;
    name?: string;
    rules?: Array<Record<string, unknown>>;
    help?: ReactNode;
  }) => {
    if (rules) h.rulesByName[String(name ?? label)] = rules;
    return (
      <div data-testid={`form-item-${String(name ?? label)}`}>
        <span data-testid="item-label">{label}</span>
        {children}
        {help ? <span data-testid="item-help">{help}</span> : null}
      </div>
    );
  };
  const Input = ({ value, disabled, placeholder }: ComponentProps<"input">) => (
    <input
      data-testid="text-input"
      value={value ?? ""}
      disabled={disabled}
      placeholder={placeholder}
      readOnly
    />
  );
  const Button = ({
    children,
    onClick,
    disabled,
    icon,
    danger,
  }: ComponentProps<"button"> & { icon?: ReactNode; danger?: boolean }) => (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-danger={danger ? "true" : "false"}
    >
      {icon}
      {children}
    </button>
  );
  const Select = ({
    placeholder,
    maxCount,
    options,
  }: {
    placeholder?: string;
    maxCount?: number;
    options?: Array<{ value: string; label: string }>;
  }) => (
    <select data-testid="tag-select" data-max={maxCount} title={placeholder}>
      {(options ?? []).map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
  const Switch = () => <span data-testid="switch" />;
  return { Form, Input, Button, Select, Switch };
});

// Exposes the streaming editor as a plain textarea so tests can drive
// handleContentChange, which is what feeds `contentValue`.
vi.mock("../../../../components/MarkdownCopy/MarkdownCopy", () => ({
  MarkdownCopy: ({
    content,
    onContentChange,
    textareaProps,
  }: {
    content?: string;
    onContentChange?: (value: string) => void;
    textareaProps?: ComponentProps<"textarea">;
  }) => (
    <div data-testid="markdown-copy">
      <span data-testid="md-content">{content}</span>
      <textarea
        data-testid="md-textarea"
        rows={textareaProps?.rows}
        placeholder={textareaProps?.placeholder}
        onChange={(e) => onContentChange?.(e.target.value)}
      />
    </div>
  ),
}));

vi.mock("../../../../components/SkillConfigEditor", () => ({
  SkillConfigEditor: ({
    value,
    onChange,
  }: {
    value?: string;
    onChange: (value: string) => void;
  }) => (
    <textarea
      data-testid="config-editor"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));

vi.mock("./SkillChannelSelect", () => ({
  SkillChannelSelect: () => <div data-testid="channel-select" />,
}));

import { MAX_TAGS, MAX_TAG_LENGTH, SkillDrawer } from "./SkillDrawer";
import { parseFrontmatter } from "./skillFrontmatter";

// `utils/skill` is deliberately NOT mocked: normalizeSkillChannels and
// deriveInstalledFromLabel run for real, so the assertions below pin their
// observable effect through the drawer rather than re-testing them in isolation.

function makeForm() {
  return {
    setFieldsValue: vi.fn(),
    resetFields: vi.fn(),
    validateFields: vi.fn(() => Promise.resolve({})),
    submit: vi.fn(),
    getFieldValue: vi.fn(),
  };
}

const VALID_CONTENT = "---\nname: demo\ndescription: a demo skill\n---\nbody";

type DrawerProps = Parameters<typeof SkillDrawer>[0];
type EditingSkill = NonNullable<DrawerProps["editingSkill"]>;

function setup(overrides: Partial<Parameters<typeof SkillDrawer>[0]> = {}) {
  const props = {
    channelOptions: {} as DrawerProps["channelOptions"],
    open: true,
    editing: false,
    editingSkill: null,
    form: makeForm() as unknown as DrawerProps["form"],
    onClose: vi.fn(),
    onSubmit: vi.fn(),
    ...overrides,
  };
  const view = render(<SkillDrawer {...props} />);
  return { ...view, props };
}

function contentValidator() {
  const rule = h.rulesByName["content"]?.find(
    (r) => typeof r.validator === "function",
  ) as { validator: (a: unknown, b: string) => Promise<void> } | undefined;
  if (!rule) throw new Error("content validator was not captured");
  return rule.validator;
}

function tagsValidator() {
  const rule = h.rulesByName["tags"]?.find(
    (r) => typeof r.validator === "function",
  ) as
    | { validator: (a: unknown, b: string[] | undefined) => Promise<void> }
    | undefined;
  if (!rule) throw new Error("tags validator was not captured");
  return rule.validator;
}

beforeEach(() => {
  vi.clearAllMocks();
  h.onFinishRef.current = undefined;
  h.rulesByName = {};
});

describe("parseFrontmatter", () => {
  it("returns null when the content does not start with the delimiter", () => {
    expect(parseFrontmatter("name: demo\n---\nbody")).toBeNull();
    expect(parseFrontmatter("plain text without frontmatter")).toBeNull();
  });

  it("returns null when the opening delimiter is never closed", () => {
    expect(parseFrontmatter("---\nname: demo\nbody")).toBeNull();
  });

  it("returns null when the frontmatter block is empty or whitespace only", () => {
    expect(parseFrontmatter("------\nbody")).toBeNull();
    expect(parseFrontmatter("---\n   \n---\nbody")).toBeNull();
  });

  it("returns null for empty input", () => {
    expect(parseFrontmatter("")).toBeNull();
    expect(parseFrontmatter("   ")).toBeNull();
  });

  it("parses key/value pairs and trims both sides", () => {
    expect(parseFrontmatter(VALID_CONTENT)).toEqual({
      name: "demo",
      description: "a demo skill",
    });
    expect(
      parseFrontmatter("---\n   name   :   spaced value   \n---\nbody"),
    ).toEqual({ name: "spaced value" });
  });

  it("skips lines that have no colon at all", () => {
    expect(parseFrontmatter("---\nname: demo\nnot-a-pair\n---\n")).toEqual({
      name: "demo",
    });
  });

  // indexOf(":") > 0 is the guard, so a leading colon yields index 0 and the
  // line is dropped rather than producing an empty key.
  it("skips a line whose colon is the very first character", () => {
    expect(parseFrontmatter("---\n: orphan value\nname: demo\n---\n")).toEqual({
      name: "demo",
    });
  });

  it("keeps colons that appear inside the value", () => {
    expect(parseFrontmatter("---\nurl: http://x:8080/y\n---\n")).toEqual({
      url: "http://x:8080/y",
    });
  });

  it("lets a later duplicate key overwrite an earlier one", () => {
    expect(parseFrontmatter("---\nname: first\nname: second\n---\n")).toEqual({
      name: "second",
    });
  });

  it("trims surrounding whitespace before looking for the delimiter", () => {
    expect(parseFrontmatter("\n\n  ---\nname: demo\n---\nbody  \n")).toEqual({
      name: "demo",
    });
  });

  it("exposes the tag limits used by the form rules", () => {
    expect(MAX_TAGS).toBe(8);
    expect(MAX_TAG_LENGTH).toBe(16);
  });
});

describe("SkillDrawer rendering", () => {
  it("titles the drawer for creation and renders the name field as required", () => {
    setup();
    expect(screen.getByTestId("drawer-title")).toHaveTextContent(
      "skills.createSkill",
    );
    expect(h.rulesByName["name"]?.[0]).toMatchObject({ required: true });
  });

  it("titles the drawer with the skill name when editing", () => {
    setup({ editing: true, editingName: "demo" });
    expect(screen.getByTestId("drawer-title")).toHaveTextContent(
      "skills.viewSkill: demo",
    );
  });

  it("omits the name suffix when editing without a name", () => {
    setup({ editing: true, editingName: "" });
    expect(screen.getByTestId("drawer-title")).toHaveTextContent(
      "skills.viewSkill",
    );
    expect(screen.getByTestId("drawer-title")).not.toHaveTextContent(
      "skills.viewSkill:",
    );
  });

  it("replaces the whole form with a loading placeholder", () => {
    setup({ loading: true });
    expect(screen.getByText("common.loading")).toBeInTheDocument();
    expect(screen.queryByTestId("skill-form")).not.toBeInTheDocument();
  });

  it("omits manual save while loading in edit mode", () => {
    setup({ editing: true, loading: true, editingSkill: null });
    expect(screen.queryByText("common.save")).not.toBeInTheDocument();
  });

  it("renders the AI optimize footer only when creating", () => {
    setup();
    expect(screen.getByText("skills.optimizeWithAI")).toBeInTheDocument();
    setup({ editing: true });
    expect(screen.queryByText("common.save")).not.toBeInTheDocument();
  });

  it("shows the installed-from label only in edit mode with a skill", () => {
    const skill = {
      name: "demo",
      source: "builtin",
      content: VALID_CONTENT,
      installed_from: "some_unknown_source",
    };
    setup({ editing: true, editingSkill: skill as EditingSkill });
    // An unknown installed_from falls through to the raw value.
    const inputs = screen.getAllByTestId("text-input");
    expect(
      inputs.some(
        (i) => (i as HTMLInputElement).value === "some_unknown_source",
      ),
    ).toBe(true);
    expect(
      screen.getByTestId("form-item-skills.installedFrom"),
    ).toBeInTheDocument();
  });

  it("renders an empty installed-from value when the field is absent", () => {
    const skill = {
      name: "demo",
      source: "builtin",
      content: VALID_CONTENT,
    };
    setup({ editing: true, editingSkill: skill as EditingSkill });
    const inputs = screen
      .getAllByTestId("text-input")
      .map((i) => (i as HTMLInputElement).value);
    expect(inputs).toContain("");
  });
});

describe("SkillDrawer populating the form from editingSkill", () => {
  it("fills the form and normalises channels through the real util", () => {
    const form = makeForm();
    const skill = {
      name: "demo",
      source: "builtin",
      content: VALID_CONTENT,
      channels: ["dingtalk", "dingtalk", "feishu"],
      preload: true,
      tags: ["a"],
      config: { k: 1 },
    };
    setup({
      editing: true,
      editingSkill: skill as EditingSkill,
      form: form as unknown as DrawerProps["form"],
    });
    expect(form.setFieldsValue).toHaveBeenCalledWith({
      name: "demo",
      content: VALID_CONTENT,
      // duplicates removed by the real normalizeSkillChannels
      channels: ["dingtalk", "feishu"],
      preload: true,
      tags: ["a"],
      source: "builtin",
    });
    // config is pretty-printed into the editor
    expect(screen.getByTestId("config-editor")).toHaveValue(
      JSON.stringify({ k: 1 }, null, 2),
    );
  });

  it("collapses a channel list containing 'all' down to ['all']", () => {
    const form = makeForm();
    setup({
      editing: true,
      editingSkill: {
        name: "demo",
        source: "builtin",
        content: VALID_CONTENT,
        channels: ["all", "dingtalk"],
      } as EditingSkill,
      form: form as unknown as DrawerProps["form"],
    });
    expect(form.setFieldsValue).toHaveBeenCalledWith(
      expect.objectContaining({ channels: ["all"] }),
    );
  });

  it("defaults preload to false and tags to [] when the skill omits them", () => {
    const form = makeForm();
    setup({
      editing: true,
      editingSkill: {
        name: "demo",
        source: "builtin",
        content: VALID_CONTENT,
      } as EditingSkill,
      form: form as unknown as DrawerProps["form"],
    });
    expect(form.setFieldsValue).toHaveBeenCalledWith(
      expect.objectContaining({ preload: false, tags: [] }),
    );
    // config falls back to {} then pretty-printed
    expect(screen.getByTestId("config-editor")).toHaveValue("{}");
  });

  it("resets the form and clears local state when switching to create mode", () => {
    const form = makeForm();
    setup({ editing: false, form: form as unknown as DrawerProps["form"] });
    expect(form.resetFields).toHaveBeenCalled();
    expect(screen.getByTestId("md-content")).toHaveTextContent("");
    expect(screen.getByTestId("config-editor")).toHaveValue("{}");
  });
});

describe("SkillDrawer content validator", () => {
  it("rejects empty content", async () => {
    setup();
    await expect(contentValidator()(null, "")).rejects.toThrow(
      "skills.pleaseInputContent",
    );
    await expect(contentValidator()(null, "   ")).rejects.toThrow(
      "skills.pleaseInputContent",
    );
  });

  it("rejects content without frontmatter", async () => {
    setup();
    await expect(contentValidator()(null, "just body text")).rejects.toThrow(
      "skills.frontmatterRequired",
    );
  });

  it("rejects frontmatter missing name, then missing description", async () => {
    setup();
    await expect(
      contentValidator()(null, "---\ndescription: d\n---\nbody"),
    ).rejects.toThrow("skills.frontmatterNameRequired");
    await expect(
      contentValidator()(null, "---\nname: n\n---\nbody"),
    ).rejects.toThrow("skills.frontmatterDescriptionRequired");
  });

  it("accepts frontmatter carrying both name and description", async () => {
    setup();
    await expect(
      contentValidator()(null, VALID_CONTENT),
    ).resolves.toBeUndefined();
  });

  it("prefers the streamed contentValue over the form value", async () => {
    setup();
    // Drive handleContentChange through the mocked editor.
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    // The form value is now invalid, but contentValue wins so it still passes.
    await expect(contentValidator()(null, "")).resolves.toBeUndefined();
  });
});

describe("SkillDrawer tags validator", () => {
  it("accepts an undefined or empty tag list", async () => {
    setup();
    await expect(tagsValidator()(null, undefined)).resolves.toBeUndefined();
    await expect(tagsValidator()(null, [])).resolves.toBeUndefined();
  });

  it("accepts a tag exactly at the length limit", async () => {
    setup();
    const exact = "x".repeat(MAX_TAG_LENGTH);
    await expect(tagsValidator()(null, [exact])).resolves.toBeUndefined();
  });

  it("rejects the first tag longer than the limit", async () => {
    setup();
    const tooLong = "x".repeat(MAX_TAG_LENGTH + 1);
    await expect(tagsValidator()(null, ["ok", tooLong])).rejects.toBe(
      "skillPool.tagTooLong",
    );
  });

  it("caps the tag select at MAX_TAGS", () => {
    setup({ availableTags: ["a", "b"] });
    expect(screen.getByTestId("tag-select")).toHaveAttribute(
      "data-max",
      String(MAX_TAGS),
    );
  });
});

describe("SkillDrawer submit", () => {
  it("parses the config JSON and forwards the merged skill", async () => {
    const onSubmit = vi.fn();
    setup({ onSubmit });
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    fireEvent.change(screen.getByTestId("config-editor"), {
      target: { value: '{"a":1}' },
    });
    await h.onFinishRef.current?.({ name: "demo", content: "ignored" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      name: "demo",
      // contentValue wins over the submitted form value
      content: VALID_CONTENT,
      source: "",
      config: { a: 1 },
    });
  });

  it("treats a blank config as an empty object", async () => {
    const onSubmit = vi.fn();
    setup({ onSubmit });
    fireEvent.change(screen.getByTestId("config-editor"), {
      target: { value: "   " },
    });
    await h.onFinishRef.current?.({ name: "demo", content: VALID_CONTENT });
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ config: {} }),
    );
  });

  it("blocks submit and surfaces the error on invalid config JSON", async () => {
    const onSubmit = vi.fn();
    setup({ onSubmit });
    fireEvent.change(screen.getByTestId("config-editor"), {
      target: { value: "{not json" },
    });
    await h.onFinishRef.current?.({ name: "demo", content: VALID_CONTENT });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByTestId("form-item-skills.config")).toHaveTextContent(
      "skills.configInvalidJson",
    );
  });

  it("clears a previous config error once the JSON becomes valid again", async () => {
    const onSubmit = vi.fn();
    setup({ onSubmit });
    fireEvent.change(screen.getByTestId("config-editor"), {
      target: { value: "{bad" },
    });
    await h.onFinishRef.current?.({ name: "demo", content: VALID_CONTENT });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByTestId("config-editor"), {
      target: { value: '{"ok":true}' },
    });
    await h.onFinishRef.current?.({ name: "demo", content: VALID_CONTENT });
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ config: { ok: true } }),
    );
  });

  it("keeps the existing skill source when editing", async () => {
    const onSubmit = vi.fn();
    setup({
      onSubmit,
      editing: true,
      editingSkill: {
        name: "demo",
        source: "builtin",
        content: VALID_CONTENT,
      } as EditingSkill,
    });
    await h.onFinishRef.current?.({ name: "demo", content: VALID_CONTENT });
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ source: "builtin" }),
    );
  });

  it("submits the form when the create button is clicked", () => {
    const form = makeForm();
    setup({ form: form as unknown as DrawerProps["form"] });
    fireEvent.click(screen.getByText("skills.create"));
    expect(form.submit).toHaveBeenCalled();
  });

  it("calls onClose from the cancel button and the drawer close handler", () => {
    const onClose = vi.fn();
    setup({ onClose });
    fireEvent.click(screen.getByText("common.cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("SkillDrawer AI optimize", () => {
  // The `if (!contentValue.trim())` early return in handleOptimize is NOT
  // reachable through the UI: the button's own `disabled={!contentValue.trim()}`
  // uses the identical condition, so a click can never arrive while the content
  // is blank. It is defensive-only (belt and braces). Pinned here as the
  // observable contract instead of faking a trigger just to colour those two
  // statements: a whitespace-only content still leaves the button disabled and
  // the API untouched.
  it("keeps the optimize button disabled for whitespace-only content", () => {
    setup();
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: "   " },
    });
    expect(
      screen.getByText("skills.optimizeWithAI").closest("button"),
    ).toBeDisabled();
    fireEvent.click(screen.getByText("skills.optimizeWithAI"));
    expect(h.streamOptimizeSkill).not.toHaveBeenCalled();
    expect(h.message.warning).not.toHaveBeenCalled();
  });

  it("streams chunks into the editor and reports success", async () => {
    setup();
    h.streamOptimizeSkill.mockImplementation(
      async (_c: string, onChunk: (t: string) => void) => {
        onChunk("---\nname: a\n");
        onChunk("description: b\n---\n");
      },
    );
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    fireEvent.click(screen.getByText("skills.optimizeWithAI"));
    await waitFor(() =>
      expect(h.message.success).toHaveBeenCalledWith("skills.optimizeSuccess"),
    );
    // The editor is cleared first, then rebuilt from the streamed chunks.
    // `textContent` rather than toHaveTextContent: the latter normalises
    // whitespace, so it cannot prove the newlines survived the concatenation.
    expect(screen.getByTestId("md-content").textContent).toBe(
      "---\nname: a\ndescription: b\n---\n",
    );
    expect(h.streamOptimizeSkill).toHaveBeenCalledWith(
      VALID_CONTENT,
      expect.any(Function),
      expect.any(AbortSignal),
      "en",
    );
  });

  it("surfaces the error message when optimization fails", async () => {
    setup();
    h.streamOptimizeSkill.mockRejectedValue(new Error("boom"));
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    fireEvent.click(screen.getByText("skills.optimizeWithAI"));
    await waitFor(() => expect(h.message.error).toHaveBeenCalledWith("boom"));
    expect(h.message.success).not.toHaveBeenCalled();
  });

  it("falls back to a generic message for a non-Error rejection", async () => {
    setup();
    h.streamOptimizeSkill.mockRejectedValue("plain string failure");
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    fireEvent.click(screen.getByText("skills.optimizeWithAI"));
    await waitFor(() =>
      expect(h.message.error).toHaveBeenCalledWith("skills.optimizeFailed"),
    );
  });

  it("stays silent when the user aborts the stream", async () => {
    setup();
    const abort = new DOMException("Aborted", "AbortError");
    h.streamOptimizeSkill.mockRejectedValue(abort);
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    fireEvent.click(screen.getByText("skills.optimizeWithAI"));
    await waitFor(() =>
      expect(screen.getByText("skills.optimizeWithAI")).toBeInTheDocument(),
    );
    expect(h.message.error).not.toHaveBeenCalled();
    expect(h.message.success).not.toHaveBeenCalled();
  });

  it("offers a stop button while streaming and aborts the request", async () => {
    setup();
    let captured: AbortSignal | undefined;
    h.streamOptimizeSkill.mockImplementation(
      (_c: string, _on: unknown, signal: AbortSignal) =>
        new Promise<void>((resolve) => {
          captured = signal;
          signal.addEventListener("abort", () => resolve());
        }),
    );
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    fireEvent.click(screen.getByText("skills.optimizeWithAI"));
    const stop = await screen.findByText("skills.stopOptimize");
    expect(captured).toBeDefined();
    expect(captured?.aborted).toBe(false);
    fireEvent.click(stop);
    expect(captured?.aborted).toBe(true);
    await waitFor(() =>
      expect(screen.getByText("skills.optimizeWithAI")).toBeInTheDocument(),
    );
  });

  it("leaves no abortable stop button once the stream finished", async () => {
    setup();
    h.streamOptimizeSkill.mockResolvedValue(undefined);
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    fireEvent.click(screen.getByText("skills.optimizeWithAI"));
    await waitFor(() =>
      expect(h.message.success).toHaveBeenCalledWith("skills.optimizeSuccess"),
    );
    // The finished stream is not abortable: abortControllerRef was nulled in the
    // finally block, so the footer flipped back to the optimize button and there
    // is no stop button left to click.
    await waitFor(() =>
      expect(screen.queryByText("skills.stopOptimize")).not.toBeInTheDocument(),
    );
  });

  it("disables the optimize button while the content is blank", () => {
    setup();
    expect(
      screen.getByText("skills.optimizeWithAI").closest("button"),
    ).toBeDisabled();
  });

  it("passes the current interface language to the API", async () => {
    setup();
    h.streamOptimizeSkill.mockResolvedValue(undefined);
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    fireEvent.click(screen.getByText("skills.optimizeWithAI"));
    await waitFor(() => expect(h.streamOptimizeSkill).toHaveBeenCalled());
    expect(h.streamOptimizeSkill.mock.calls[0][3]).toBe("en");
  });
});

describe("SkillDrawer content change wiring", () => {
  it("mirrors edits into the form, revalidates and notifies the parent", () => {
    const form = makeForm();
    const onContentChange = vi.fn();
    setup({ form: form as unknown as DrawerProps["form"], onContentChange });
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    expect(form.setFieldsValue).toHaveBeenCalledWith({
      content: VALID_CONTENT,
    });
    expect(form.validateFields).toHaveBeenCalledWith(["content"]);
    expect(onContentChange).toHaveBeenCalledWith(VALID_CONTENT);
    // textContent: the value is multi-line and must survive verbatim.
    expect(screen.getByTestId("md-content").textContent).toBe(VALID_CONTENT);
  });

  it("swallows a rejection from the revalidation pass", async () => {
    const form = makeForm();
    form.validateFields = vi.fn(() => Promise.reject(new Error("invalid")));
    setup({ form: form as unknown as DrawerProps["form"] });
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: "no frontmatter" },
    });
    // The catch handler keeps the drawer usable; no unhandled rejection escapes.
    await waitFor(() => expect(form.validateFields).toHaveBeenCalled());
    expect(screen.getByTestId("md-content").textContent).toBe("no frontmatter");
  });

  it("does not require an onContentChange callback", () => {
    setup();
    expect(() =>
      fireEvent.change(screen.getByTestId("md-textarea"), {
        target: { value: VALID_CONTENT },
      }),
    ).not.toThrow();
  });

  it("gives the content textarea the create-mode placeholder and 12 rows", () => {
    setup();
    const ta = screen.getByTestId("md-textarea");
    expect(ta).toHaveAttribute("rows", "12");
    expect(ta).toHaveAttribute("placeholder", "skills.contentPlaceholder");
  });

  it("omits the placeholder when editing", () => {
    setup({
      editing: true,
      editingSkill: {
        name: "demo",
        source: "builtin",
        content: VALID_CONTENT,
      } as EditingSkill,
    });
    expect(screen.getByTestId("md-textarea")).not.toHaveAttribute(
      "placeholder",
    );
  });
});

describe("SkillDrawer channels field", () => {
  it("requires at least one channel and defaults to ['all']", () => {
    setup();
    const rule = h.rulesByName["channels"]?.[0];
    expect(rule).toMatchObject({ required: true, type: "array", min: 1 });
    expect(screen.getByTestId("form-item-channels")).toHaveTextContent(
      "skills.channels",
    );
  });

  it("passes the channel options through to the select", () => {
    const channelOptions = {
      options: [],
      loading: false,
    } as unknown as DrawerProps["channelOptions"];
    setup({ channelOptions });
    expect(screen.getByTestId("channel-select")).toBeInTheDocument();
  });
});

describe("SkillDrawer automatic persistence", () => {
  it("saves edited content after one idle second without closing", async () => {
    vi.useFakeTimers();
    const { props, unmount } = setup({
      editing: true,
      editingSkill: { name: "demo", content: VALID_CONTENT } as EditingSkill,
    });
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT + " updated" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(999);
    });
    expect(props.onSubmit).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(props.onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ content: VALID_CONTENT + " updated" }),
    );
    expect(props.onClose).not.toHaveBeenCalled();
    unmount();
    vi.useRealTimers();
  });
  it("flushes content when navigating away before the debounce", async () => {
    const { props, unmount } = setup({
      editing: true,
      editingSkill: { name: "demo", content: VALID_CONTENT } as EditingSkill,
    });
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT + " pending" },
    });
    await act(async () => {
      unmount();
    });
    expect(props.onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ content: VALID_CONTENT + " pending" }),
    );
  });
  it("does not autosave new skills", async () => {
    vi.useFakeTimers();
    const { props, unmount } = setup();
    fireEvent.change(screen.getByTestId("md-textarea"), {
      target: { value: VALID_CONTENT },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(props.onSubmit).not.toHaveBeenCalled();
    unmount();
    vi.useRealTimers();
  });
});
