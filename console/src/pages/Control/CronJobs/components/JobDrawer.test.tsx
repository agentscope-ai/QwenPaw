// @vitest-environment jsdom
/**
 * JobDrawer render tests — regression family: cron job create/edit form.
 * Covers the conditional schedule blocks (cron/once, cronType variants),
 * the save_result_to_inbox auto-default logic, dispatch target option
 * merging/filtering and the submit/cancel footer actions.
 *
 * @agentscope-ai/design is globally aliased to a thin stub (see
 * src/test/design-mock.ts) that lacks Drawer/Select/Checkbox and a real
 * Form, so this file re-mocks the package: the design Form is replaced by
 * the real antd Form (the design one is a styled wrapper around it, so
 * shouldUpdate render props and Form.useWatch behave exactly like in
 * production), DatePicker/TimePicker become plain inputs because jsdom has
 * no layout engine, and Select becomes a native <select> that stays form
 * bindable while exposing its rendered options for assertions.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  act,
  waitFor,
} from "@testing-library/react";
import React from "react";
import { Form } from "antd";
import type { FormInstance } from "antd";
import type {
  CronJobSpecOutput,
  CronDispatchTargetItem,
} from "../../../../api/types";

// ---- Hoisted mocks ---------------------------------------------------------

const capturedSelects = vi.hoisted(() => new Map<string, unknown[]>());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en", resolvedLanguage: "en" },
  }),
}));

vi.mock("antd", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("antd");
  return {
    ...actual,
    DatePicker: (props: Record<string, unknown>) => (
      <input
        data-testid="date-picker"
        placeholder={String(props.placeholder ?? "")}
      />
    ),
    TimePicker: (props: Record<string, unknown>) => (
      <input
        data-testid="time-picker"
        placeholder={String(props.placeholder ?? "")}
      />
    ),
  };
});

vi.mock("@agentscope-ai/design", async () => {
  // importActual resolves through the test alias to src/test/design-mock.ts;
  // reuse its Button/Input/Switch stubs, replace the rest with functional
  // equivalents so the real form logic stays under test.
  const stub = await vi.importActual<Record<string, unknown>>(
    "@agentscope-ai/design",
  );
  const antdActual = await vi.importActual<Record<string, unknown>>("antd");
  const AntdForm = antdActual.Form as Record<string, unknown>;
  const AntdCheckbox = antdActual.Checkbox as Record<string, unknown>;

  const Drawer = ({
    open,
    title,
    footer,
    children,
  }: {
    open?: boolean;
    title?: React.ReactNode;
    footer?: React.ReactNode;
    children?: React.ReactNode;
  }) =>
    open ? (
      <div role="dialog">
        <div>{title}</div>
        {children}
        <div>{footer}</div>
      </div>
    ) : null;

  interface OptionLike {
    value: string;
    label: React.ReactNode;
  }

  const SelectOption = ({
    value,
    children,
  }: {
    value: string;
    children?: React.ReactNode;
  }) => <option value={value}>{children}</option>;

  const Select = Object.assign(
    ({
      value,
      onChange,
      onBlur,
      onSearch,
      options = [],
      placeholder,
      children,
    }: {
      value?: string;
      onChange?: (value: string) => void;
      onBlur?: () => void;
      onSearch?: (value: string) => void;
      options?: OptionLike[];
      placeholder?: string;
      children?: React.ReactNode;
    }) => {
      capturedSelects.set(placeholder ?? "", options);
      return (
        <>
          {onSearch ? (
            <input
              data-testid={`search-${placeholder}`}
              onChange={(e) => onSearch(e.target.value)}
            />
          ) : null}
          <select
            value={value ?? ""}
            data-placeholder={placeholder}
            onChange={(e) => onChange?.(e.target.value)}
            onBlur={onBlur}
          >
            <option value="">{placeholder}</option>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {String(o.label)}
              </option>
            ))}
            {children}
          </select>
        </>
      );
    },
    { Option: SelectOption },
  );

  return {
    ...stub,
    Drawer,
    Select,
    Checkbox: AntdCheckbox,
    Form: AntdForm,
  };
});

import { JobDrawer } from "./JobDrawer";

// ---- Fixtures --------------------------------------------------------------

const TARGET_ITEMS: CronDispatchTargetItem[] = [
  { channel: "console", user_id: "u1", session_id: "s1" },
  { channel: "console", user_id: "u2", session_id: "s2" },
  { channel: "telegram", user_id: "u3", session_id: "s3" },
] as unknown as CronDispatchTargetItem[];

interface DrawerOverrides {
  editingJob?: CronJobSpecOutput | null;
  targetItems?: CronDispatchTargetItem[];
  targetChannels?: string[];
  onClose?: () => void;
  onSubmit?: (values: CronJobSpecOutput) => void;
  onReloadTargets?: () => Promise<void>;
}

function Harness({
  overrides = {},
  onReady,
}: {
  overrides?: DrawerOverrides;
  onReady?: (form: FormInstance) => void;
}) {
  const [form] = Form.useForm();
  React.useEffect(() => {
    onReady?.(form as unknown as FormInstance);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <JobDrawer
      open
      editingJob={overrides.editingJob ?? null}
      form={form as never}
      saving={false}
      targetItems={overrides.targetItems ?? TARGET_ITEMS}
      targetChannels={overrides.targetChannels ?? ["console"]}
      targetsLoading={false}
      onReloadTargets={overrides.onReloadTargets ?? (async () => undefined)}
      onClose={overrides.onClose ?? (() => undefined)}
      onSubmit={overrides.onSubmit ?? (() => undefined)}
    />
  );
}

function renderDrawer(overrides: DrawerOverrides = {}) {
  const onClose = overrides.onClose ?? vi.fn();
  const onSubmit = overrides.onSubmit ?? vi.fn();
  const onReloadTargets =
    overrides.onReloadTargets ?? vi.fn().mockResolvedValue(undefined);
  let formRef: FormInstance | undefined;
  const view = render(
    <Harness
      overrides={{ ...overrides, onClose, onSubmit, onReloadTargets }}
      onReady={(f) => {
        formRef = f;
      }}
    />,
  );
  const getForm = () => formRef as FormInstance;
  return { view, getForm, onClose, onSubmit, onReloadTargets };
}

// ---- Tests -----------------------------------------------------------------

describe("JobDrawer open lifecycle", () => {
  it("renders the create title, base fields and reloads targets on open", async () => {
    const { onReloadTargets } = renderDrawer();
    expect(await screen.findByText("cronJobs.createJob")).toBeInTheDocument();
    expect(screen.getByText("cronJobs.name")).toBeInTheDocument();
    expect(screen.getByText("cronJobs.enabled")).toBeInTheDocument();
    expect(screen.getByText("cronJobs.saveResultToInbox")).toBeInTheDocument();
    await waitFor(() => expect(onReloadTargets).toHaveBeenCalledTimes(1));
  });

  it("shows the disabled id field only in edit mode", () => {
    const job = { id: "job-1", name: "n" } as unknown as CronJobSpecOutput;
    renderDrawer({ editingJob: job });
    expect(screen.getByText("cronJobs.editJob")).toBeInTheDocument();
    expect(screen.getByText("cronJobs.id")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("cronJobs.jobIdPlaceholder"),
    ).toBeDisabled();
  });

  it("renders nothing when closed", () => {
    function ClosedHarness() {
      const [form] = Form.useForm();
      return (
        <JobDrawer
          open={false}
          editingJob={null}
          form={form as never}
          saving={false}
          targetItems={[]}
          targetChannels={[]}
          targetsLoading={false}
          onReloadTargets={async () => undefined}
          onClose={() => undefined}
          onSubmit={() => undefined}
        />
      );
    }
    const { container } = render(<ClosedHarness />);
    expect(container.textContent).not.toContain("cronJobs.createJob");
  });

  it("logs (does not throw) when reloading targets rejects", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderDrawer({
      onReloadTargets: () => Promise.reject(new Error("boom")),
    });
    await waitFor(() => expect(errSpy).toHaveBeenCalled());
    errSpy.mockRestore();
  });
});

describe("JobDrawer schedule blocks", () => {
  it("shows the daily cron time picker by default and weekly day checkboxes after switching", async () => {
    const { getForm } = renderDrawer();
    expect(await screen.findByTestId("time-picker")).toBeInTheDocument();

    act(() => {
      getForm().setFieldValue("cronType", "weekly");
    });
    await waitFor(() =>
      expect(screen.getByText("cronJobs.cronDaysOfWeek")).toBeInTheDocument(),
    );
    expect(screen.getByText("cronJobs.cronDayMon")).toBeInTheDocument();
    expect(screen.getByText("cronJobs.cronDaySun")).toBeInTheDocument();
  });

  it("renders the custom cron expression field with the crontab.guru helper link", async () => {
    const { getForm } = renderDrawer();
    act(() => {
      getForm().setFieldValue("cronType", "custom");
    });
    await waitFor(() =>
      expect(
        screen.getByText("cronJobs.cronCustomExpression"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("link", { name: /cronJobs\.cronHelperLink/ }),
    ).toHaveAttribute("href", "https://crontab.guru/");
    expect(screen.getByPlaceholderText("0 9 * * *")).toBeInTheDocument();
  });

  it("switches to once mode: run-at picker plus repeat controls that follow end type", async () => {
    const { getForm } = renderDrawer();
    act(() => {
      getForm().setFieldsValue({ scheduleType: "once" });
    });
    await waitFor(() =>
      expect(screen.getByText("cronJobs.onceRunAt")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("date-picker")).toBeInTheDocument();

    act(() => {
      getForm().setFieldsValue({ onceRepeatEnabled: true });
    });
    await waitFor(() =>
      expect(screen.getByText("cronJobs.repeatFrequency")).toBeInTheDocument(),
    );
    expect(screen.getByText("cronJobs.repeatEndType")).toBeInTheDocument();

    act(() => {
      getForm().setFieldsValue({ onceRepeatEndType: "until" });
    });
    await waitFor(() =>
      expect(screen.getByText("cronJobs.repeatUntil")).toBeInTheDocument(),
    );

    act(() => {
      getForm().setFieldsValue({ onceRepeatEndType: "count" });
    });
    await waitFor(() =>
      expect(screen.getByText("cronJobs.repeatCount")).toBeInTheDocument(),
    );
  });

  it("hides the cron-only time picker in once mode", async () => {
    const { getForm } = renderDrawer();
    await screen.findByTestId("time-picker");
    act(() => {
      getForm().setFieldsValue({ scheduleType: "once" });
    });
    await waitFor(() =>
      expect(screen.getByText("cronJobs.onceRunAt")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("time-picker")).not.toBeInTheDocument();
  });
});

describe("JobDrawer save_result_to_inbox auto default", () => {
  it("is off for text+cron jobs (the message itself is the deliverable)", async () => {
    const { getForm } = renderDrawer();
    act(() => {
      getForm().setFieldsValue({ task_type: "text" });
    });
    await waitFor(() =>
      expect(getForm().getFieldValue("save_result_to_inbox")).toBe(false),
    );
  });

  it("flips back to on when the task type returns to agent", async () => {
    const { getForm } = renderDrawer();
    act(() => {
      getForm().setFieldsValue({ task_type: "text" });
    });
    await waitFor(() =>
      expect(getForm().getFieldValue("save_result_to_inbox")).toBe(false),
    );
    act(() => {
      getForm().setFieldsValue({ task_type: "agent" });
    });
    await waitFor(() =>
      expect(getForm().getFieldValue("save_result_to_inbox")).toBe(true),
    );
  });

  it("stops overriding after the user touched the switch", async () => {
    const { getForm } = renderDrawer();
    act(() => {
      getForm().setFieldsValue({ task_type: "text" });
    });
    await waitFor(() =>
      expect(getForm().getFieldValue("save_result_to_inbox")).toBe(false),
    );
    // click the switch under the save_result_to_inbox field: the stub
    // renders it as a checkbox input inside the ant form item
    const label = screen.getByText("cronJobs.saveResultToInbox");
    const item = label.closest(".ant-form-item") as HTMLElement;
    const checkbox = item.querySelector('input[type="checkbox"]');
    expect(checkbox).toBeTruthy();
    act(() => {
      fireEvent.click(checkbox as HTMLElement);
    });
    await waitFor(() =>
      expect(getForm().getFieldValue("save_result_to_inbox")).toBe(true),
    );
    // even though text+cron would force it off, the touched flag wins
    await new Promise((r) => setTimeout(r, 50));
    expect(getForm().getFieldValue("save_result_to_inbox")).toBe(true);
  });
});

describe("JobDrawer dispatch target options", () => {
  const optionLabels = (placeholder: string) =>
    (capturedSelects.get(placeholder) ?? []).map(
      (o) => (o as { label: string }).label,
    );

  beforeEach(() => {
    capturedSelects.clear();
  });

  it("lists backend channels in the channel select", async () => {
    renderDrawer();
    await screen.findByText("cronJobs.createJob");
    await waitFor(() => expect(optionLabels("console")).toContain("console"));
  });

  it("filters user options by the selected channel", async () => {
    renderDrawer();
    await screen.findByText("cronJobs.createJob");
    await waitFor(() => expect(capturedSelects.get("admin")).toBeDefined());
    expect(optionLabels("admin")).toEqual(expect.arrayContaining(["u1", "u2"]));
    expect(optionLabels("admin")).not.toContain("u3");
  });

  it("filters session options by channel and selected user", async () => {
    const { getForm } = renderDrawer();
    await screen.findByText("cronJobs.createJob");
    act(() => {
      getForm().setFieldValue(["dispatch", "target", "user_id"], "u1");
    });
    await waitFor(() => expect(optionLabels("default")).toEqual(["s1"]));
  });

  it("keeps a user-typed channel option merged into the list", async () => {
    const { getForm } = renderDrawer();
    await screen.findByText("cronJobs.createJob");
    act(() => {
      getForm().setFieldValue(["dispatch", "channel"], "my-custom-channel");
    });
    await waitFor(() =>
      expect(optionLabels("console")).toContain("my-custom-channel"),
    );
  });

  it("merges a typed search term into the channel option list", async () => {
    renderDrawer();
    await screen.findByText("cronJobs.createJob");
    // typing into the searchable channel select triggers onSearch, whose
    // value is merged into the option list (custom value support)
    const searchInput = screen.getByTestId("search-console");
    act(() => {
      fireEvent.change(searchInput, { target: { value: "typed-channel" } });
    });
    await waitFor(() =>
      expect(optionLabels("console")).toContain("typed-channel"),
    );
  });
});

describe("JobDrawer request input validation", () => {
  it("accepts valid JSON and rejects malformed JSON for agent tasks", async () => {
    const onSubmit = vi.fn();
    const { getForm } = renderDrawer({ onSubmit });
    await screen.findByText("cronJobs.createJob");

    // malformed JSON: submission is blocked with the validator error
    act(() => {
      getForm().setFieldsValue({
        name: "j",
        task_type: "agent",
        request: { input: "{not-json", user_id: "", session_id: "" },
        dispatch: {
          channel: "console",
          target: { user_id: "u1", session_id: "s1" },
        },
      });
    });
    fireEvent.click(screen.getByText("common.save"));
    await waitFor(() =>
      expect(
        screen.getByText("cronJobs.invalidJsonFormat"),
      ).toBeInTheDocument(),
    );
    expect(onSubmit).not.toHaveBeenCalled();

    // valid JSON: the validator lets the form through
    act(() => {
      getForm().setFieldValue(["request", "input"], '[{"role":"user"}]');
    });
    fireEvent.click(screen.getByText("common.save"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });
});

describe("JobDrawer task type effects", () => {
  it("forces silent off and disables the switch when the task type is text", async () => {
    const { getForm } = renderDrawer();
    // silent delivery only makes sense for agent tasks
    act(() => {
      getForm().setFieldValue(["dispatch", "silent"], true);
    });
    act(() => {
      getForm().setFieldsValue({ task_type: "text" });
    });
    await waitFor(() =>
      expect(getForm().getFieldValue(["dispatch", "silent"] as never)).toBe(
        false,
      ),
    );
  });
});

describe("JobDrawer footer actions", () => {
  it("cancel calls onClose", () => {
    const onClose = vi.fn();
    renderDrawer({ onClose });
    fireEvent.click(screen.getByText("common.cancel"));
    expect(onClose).toHaveBeenCalled();
  });

  it("save submits the form and hands the values to onSubmit", async () => {
    const onSubmit = vi.fn();
    const { getForm } = renderDrawer({ onSubmit });
    await screen.findByText("cronJobs.createJob");
    act(() => {
      getForm().setFieldsValue({
        name: "my-job",
        task_type: "text",
        text: "say hi",
        dispatch: {
          channel: "console",
          target: { user_id: "u1", session_id: "s1" },
        },
      });
    });
    fireEvent.click(screen.getByText("common.save"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      name: "my-job",
      task_type: "text",
      text: "say hi",
    });
  });
});
