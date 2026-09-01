// @vitest-environment jsdom
/**
 * CronJobsPage render tests — regression family: cron scheduling
 * (bug_insights retro P1 SC-CRN-002 heartbeat/misfire).
 * Covers list/calendar/mobile views, schedule filtering, one-time job
 * calendar expansion (timezone repeat logic) and execution history.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent, waitFor, act } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import dayjs from "dayjs";

// ---- Hoisted mocks ---------------------------------------------------------

const mockUseCronJobs = vi.hoisted(() => vi.fn());
const mockApi = vi.hoisted(() => ({
  getUserTimezone: vi.fn(),
  listCronDispatchTargets: vi.fn(),
  getCronJobHistory: vi.fn(),
}));
// Capture what the page passes to its child components so tests can
// drive the handlers (table column actions, drawer submit, template use).
const mockForm = vi.hoisted(() => ({
  resetFields: vi.fn(),
  setFieldsValue: vi.fn(),
}));
const mockConfirm = vi.hoisted(() => vi.fn());
const capturedColumns = vi.hoisted<{ handlers: any }>(() => ({
  handlers: null,
}));
const capturedDrawer = vi.hoisted<{ props: any }>(() => ({ props: null }));
const capturedTemplate = vi.hoisted<{ props: any }>(() => ({ props: null }));
const drawerSubmitValues = vi.hoisted<{ value: any }>(() => ({ value: {} }));
const templateValues = vi.hoisted<{ value: any }>(() => ({ value: {} }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../../api", () => ({
  default: mockApi,
}));

vi.mock("./components", () => ({
  createColumns: (handlers: Record<string, unknown>) => {
    capturedColumns.handlers = handlers;
    return [];
  },
  JobDrawer: (props: Record<string, unknown>) => {
    capturedDrawer.props = props;
    return props.open ? <div data-testid="job-drawer" /> : null;
  },
  TemplatePickerModal: (props: Record<string, unknown>) => {
    capturedTemplate.props = props;
    return props.open ? <div data-testid="template-modal" /> : null;
  },
  useCronJobs: () => mockUseCronJobs(),
  DEFAULT_FORM_VALUES: { schedule: { type: "cron" } },
}));

vi.mock("@ant-design/icons", () => ({
  CalendarOutlined: () => <span data-testid="icon-calendar" />,
  LeftOutlined: () => <span data-testid="icon-left" />,
  RightOutlined: () => <span data-testid="icon-right" />,
  UnorderedListOutlined: () => <span data-testid="icon-list" />,
  MoreOutlined: () => <span data-testid="icon-more" />,
}));

// design-mock lacks Table/Card/Select/Popover; provide render stubs
vi.mock("@agentscope-ai/design", async () => {
  const actual = await vi.importActual<object>("@agentscope-ai/design");
  return {
    ...actual,
    Table: ({ dataSource = [] }: { dataSource?: unknown[] }) => (
      <div data-testid="cron-table">{`rows:${dataSource.length}`}</div>
    ),
    Card: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="cron-card">{children}</div>
    ),
    Select: ({
      onChange,
      options = [],
      value,
    }: {
      onChange?: (v: string) => void;
      options?: { label: string; value: string }[];
      value?: string;
    }) => (
      <select
        data-testid="schedule-filter"
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    ),
    Popover: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    Form: Object.assign(
      ({ children }: { children?: React.ReactNode }) => <form>{children}</form>,
      { useForm: () => [mockForm] },
    ),
    Modal: Object.assign(
      ({ children, title }: { children?: React.ReactNode; title?: string }) => (
        <div data-testid="cron-modal" data-title={title}>
          {children}
        </div>
      ),
      { confirm: mockConfirm, error: vi.fn(), warning: vi.fn() },
    ),
    Dropdown: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    Button: ({
      children,
      onClick,
    }: {
      children?: React.ReactNode;
      onClick?: () => void;
    }) => <button onClick={onClick}>{children}</button>,
  };
});

import CronJobsPage from "./index";

// ---- Fixtures --------------------------------------------------------------

const recurringJob = {
  id: "job-1",
  name: "Daily Report",
  enabled: true,
  schedule: { type: "cron", cron: "0 9 * * *" },
  task_type: "text",
  text: "Generate report",
};

const oneTimeJob = {
  id: "job-2",
  name: "Once Task",
  enabled: true,
  schedule: {
    type: "once",
    run_at: dayjs().add(1, "day").format("YYYY-MM-DDTHH:mm:ss"),
    timezone: "UTC",
  },
  task_type: "text",
  text: "One shot",
};

const repeatingJob = {
  id: "job-3",
  name: "Repeat Every 3 Days",
  enabled: false,
  schedule: {
    type: "once",
    run_at: dayjs().subtract(6, "day").format("YYYY-MM-DDTHH:mm:ss"),
    timezone: "UTC",
    repeat_every_days: 3,
    repeat_end_type: "count",
    repeat_count: 5,
  },
  task_type: "text",
  text: "Repeat",
};

function mockHookReturn(overrides: Record<string, unknown> = {}) {
  mockUseCronJobs.mockReturnValue({
    jobs: [],
    loading: false,
    createJob: vi.fn().mockResolvedValue(undefined),
    updateJob: vi.fn().mockResolvedValue(undefined),
    deleteJob: vi.fn().mockResolvedValue(undefined),
    toggleEnabled: vi.fn(),
    executeNow: vi.fn(),
    ...overrides,
  });
}

beforeEach(() => {
  mockApi.getUserTimezone.mockResolvedValue({ timezone: "UTC" });
  mockApi.listCronDispatchTargets.mockResolvedValue({
    items: [],
    channels: ["console"],
  });
  mockApi.getCronJobHistory.mockResolvedValue([]);
  capturedColumns.handlers = null;
  capturedDrawer.props = null;
  capturedTemplate.props = null;
  drawerSubmitValues.value = {};
  templateValues.value = {};
  mockForm.resetFields.mockClear();
  mockForm.setFieldsValue.mockClear();
  mockConfirm.mockClear();
});

// matchMedia is read once on mount to pick the mobile layout. Restore the
// default desktop stub after every test so mobile-mode tests cannot leak
// into later ones.
function setMatchMedia(matches: boolean) {
  (window as unknown as { matchMedia: unknown }).matchMedia = vi.fn(
    (query: string) => ({
      matches,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  );
}

afterEach(() => {
  setMatchMedia(false);
  vi.restoreAllMocks();
});

// ---- Tests -----------------------------------------------------------------

describe("CronJobsPage", () => {
  it("renders the list view with an empty table", async () => {
    mockHookReturn();
    renderWithProviders(<CronJobsPage />);
    await waitFor(() => {
      expect(screen.getByTestId("cron-table")).toBeTruthy();
    });
    expect(screen.getByTestId("cron-table").textContent).toBe("rows:0");
  });

  it("renders recurring jobs into the table", async () => {
    mockHookReturn({ jobs: [recurringJob] });
    renderWithProviders(<CronJobsPage />);
    await waitFor(() => {
      expect(screen.getByTestId("cron-table").textContent).toBe("rows:1");
    });
  });

  it("switches to the calendar view and shows once-job events", async () => {
    mockHookReturn({ jobs: [oneTimeJob] });
    renderWithProviders(<CronJobsPage />);
    await waitFor(() => {
      expect(screen.getByTitle("cronJobs.calendarView")).toBeTruthy();
    });
    fireEvent.click(screen.getByTitle("cronJobs.calendarView"));
    // Calendar renders 42 day cells; the once-job appears as an event chip
    await waitFor(() => {
      expect(screen.getByText(/Once Task/)).toBeTruthy();
    });
  });

  it("renders repeating once-jobs across the month with count limits", async () => {
    mockHookReturn({ jobs: [repeatingJob] });
    renderWithProviders(<CronJobsPage />);
    fireEvent.click(screen.getByTitle("cronJobs.calendarView"));
    // repeat_every_days=3 starting 6 days ago with count=5 yields events
    await waitFor(() => {
      const chips = screen.getAllByText(/Repeat Every 3 Days/);
      expect(chips.length).toBeGreaterThan(0);
    });
  });

  it("shows the calendar empty hint when there are no one-time jobs", async () => {
    mockHookReturn({ jobs: [recurringJob] });
    renderWithProviders(<CronJobsPage />);
    fireEvent.click(screen.getByTitle("cronJobs.calendarView"));
    await waitFor(() => {
      expect(screen.getByText("cronJobs.calendarEmptyHint")).toBeTruthy();
    });
  });

  it("navigates calendar months forward and backward", async () => {
    mockHookReturn({ jobs: [] });
    renderWithProviders(<CronJobsPage />);
    fireEvent.click(screen.getByTitle("cronJobs.calendarView"));
    const [left, right] = [
      screen
        .getAllByRole("button")
        .find((b) => b.querySelector('[data-testid="icon-left"]')),
      screen
        .getAllByRole("button")
        .find((b) => b.querySelector('[data-testid="icon-right"]')),
    ];
    if (left) fireEvent.click(left);
    if (right) fireEvent.click(right);
    await waitFor(() => {
      expect(screen.getByTestId("cron-card")).toBeTruthy();
    });
  });

  it("opens the create drawer from the create button", async () => {
    mockHookReturn();
    renderWithProviders(<CronJobsPage />);
    const createBtn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("cronJobs.createJob"));
    expect(createBtn).toBeTruthy();
    fireEvent.click(createBtn!);
    await waitFor(() => {
      expect(screen.getByTestId("job-drawer")).toBeTruthy();
    });
  });

  it("opens the template picker modal", async () => {
    mockHookReturn();
    renderWithProviders(<CronJobsPage />);
    const templateBtn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("cronJobs.createFromTemplate"));
    fireEvent.click(templateBtn!);
    await waitFor(() => {
      expect(screen.getByTestId("template-modal")).toBeTruthy();
    });
  });

  it("renders the mobile card list when the viewport is narrow", async () => {
    setMatchMedia(true);
    mockHookReturn({ jobs: [recurringJob, oneTimeJob] });
    renderWithProviders(<CronJobsPage />);
    // Mobile view shows card per job with status text
    await waitFor(() => {
      expect(screen.getByText("Daily Report")).toBeTruthy();
      expect(screen.getByText("Once Task")).toBeTruthy();
    });
  });

  it("loads and displays execution history with error expansion", async () => {
    const longError = Array.from({ length: 10 }, (_, i) => `line ${i}`).join(
      "\n",
    );
    mockApi.getCronJobHistory.mockResolvedValue([
      {
        run_at: "2026-08-27T09:00:00Z",
        status: "success",
        trigger: "scheduled",
      },
      {
        run_at: "2026-08-27T10:00:00Z",
        status: "failed",
        trigger: "manual",
        error: longError,
      },
    ]);
    mockHookReturn({ jobs: [recurringJob] });
    renderWithProviders(<CronJobsPage />);

    // Drive the real handler captured from createColumns
    await waitFor(() => expect(capturedColumns.handlers).toBeTruthy());
    await act(async () => {
      await capturedColumns.handlers.onViewHistory(recurringJob);
    });

    expect(mockApi.getCronJobHistory).toHaveBeenCalledWith("job-1");
    // All four status labels and both trigger labels render
    expect(screen.getByText("cronJobs.historyStatusSuccess")).toBeTruthy();
    expect(screen.getByText("cronJobs.historyStatusFailed")).toBeTruthy();
    expect(screen.getByText("cronJobs.historyTriggerScheduled")).toBeTruthy();
    expect(screen.getByText("cronJobs.historyTriggerManual")).toBeTruthy();
    // The long error shows a collapsed preview with an expand toggle
    const expandBtn = screen.getByText("cronJobs.historyExpand");
    fireEvent.click(expandBtn);
    expect(screen.getByText("cronJobs.historyCollapse")).toBeTruthy();
    fireEvent.click(screen.getByText("cronJobs.historyCollapse"));
    expect(screen.getByText("cronJobs.historyExpand")).toBeTruthy();
  });

  it("shows the history empty state and tolerates fetch failures", async () => {
    mockApi.getCronJobHistory.mockRejectedValue(new Error("no history"));
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    mockHookReturn({ jobs: [recurringJob] });
    renderWithProviders(<CronJobsPage />);
    await waitFor(() => expect(capturedColumns.handlers).toBeTruthy());

    await act(async () => {
      await capturedColumns.handlers.onViewHistory(recurringJob);
    });

    expect(screen.getByText("cronJobs.historyEmpty")).toBeTruthy();
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it("renders running/cancelled statuses without error blocks", async () => {
    mockApi.getCronJobHistory.mockResolvedValue([
      {
        run_at: "2026-08-27T11:00:00Z",
        status: "running",
        trigger: "scheduled",
      },
      {
        run_at: "2026-08-27T12:00:00Z",
        status: "cancelled",
        trigger: "manual",
        error: "short",
      },
    ]);
    mockHookReturn({ jobs: [recurringJob] });
    renderWithProviders(<CronJobsPage />);
    await waitFor(() => expect(capturedColumns.handlers).toBeTruthy());

    await act(async () => {
      await capturedColumns.handlers.onViewHistory(recurringJob);
    });

    expect(screen.getByText("cronJobs.historyStatusRunning")).toBeTruthy();
    expect(screen.getByText("cronJobs.historyStatusCancelled")).toBeTruthy();
    // Short errors render but offer no expand toggle
    expect(screen.queryByText("cronJobs.historyExpand")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Column handlers: edit / delete / toggle / execute-now
// ---------------------------------------------------------------------------
describe("CronJobsPage column handlers", () => {
  async function renderPage(overrides: Record<string, unknown> = {}) {
    mockHookReturn(overrides);
    renderWithProviders(<CronJobsPage />);
    await waitFor(() => expect(capturedColumns.handlers).toBeTruthy());
    return capturedColumns.handlers;
  }

  it("handleDelete confirms and deletes on accept", async () => {
    const deleteJob = vi.fn().mockResolvedValue(true);
    const handlers = await renderPage({ jobs: [recurringJob], deleteJob });

    handlers.onDelete("job-1");
    expect(mockConfirm).toHaveBeenCalledTimes(1);
    const opts = mockConfirm.mock.calls[0][0];
    await act(async () => {
      await opts.onOk();
    });
    expect(deleteJob).toHaveBeenCalledWith("job-1");
  });

  it("handleExecuteNow confirms and runs on accept", async () => {
    const executeNow = vi.fn().mockResolvedValue(true);
    const handlers = await renderPage({ jobs: [recurringJob], executeNow });

    handlers.onExecuteNow(recurringJob);
    expect(mockConfirm).toHaveBeenCalledTimes(1);
    await act(async () => {
      await mockConfirm.mock.calls[0][0].onOk();
    });
    expect(executeNow).toHaveBeenCalledWith("job-1");
  });

  it("handleToggleEnabled delegates to the hook", async () => {
    const toggleEnabled = vi.fn();
    const handlers = await renderPage({ jobs: [recurringJob], toggleEnabled });
    await act(async () => {
      await handlers.onToggleEnabled(recurringJob);
    });
    expect(toggleEnabled).toHaveBeenCalledWith(recurringJob);
  });

  it("handleEdit prefills the form for a daily cron job", async () => {
    const handlers = await renderPage({ jobs: [recurringJob] });
    act(() => {
      handlers.onEdit(recurringJob);
    });

    expect(capturedDrawer.props.open).toBe(true);
    const values =
      mockForm.setFieldsValue.mock.calls[
        mockForm.setFieldsValue.mock.calls.length - 1
      ]?.[0];
    expect(values.scheduleType).toBe("cron");
    expect(values.cronType).toBe("daily");
    expect(values.request.input).toBe("");
    expect(values.cronTime.hour()).toBe(9);
    expect(values.cronTime.minute()).toBe(0);
  });

  it("handleEdit prefills weekly day-of-week and custom cron jobs", async () => {
    const weeklyJob = {
      ...recurringJob,
      id: "job-w",
      schedule: { type: "cron", cron: "30 8 * * mon,wed" },
    };
    const customJob = {
      ...recurringJob,
      id: "job-c",
      schedule: { type: "cron", cron: "*/15 * * * *" },
    };
    const handlers = await renderPage({ jobs: [weeklyJob, customJob] });

    act(() => {
      handlers.onEdit(weeklyJob);
    });
    let values =
      mockForm.setFieldsValue.mock.calls[
        mockForm.setFieldsValue.mock.calls.length - 1
      ]?.[0];
    expect(values.cronType).toBe("weekly");
    expect(values.cronDaysOfWeek).toEqual(["mon", "wed"]);
    expect(values.cronTime.hour()).toBe(8);
    expect(values.cronTime.minute()).toBe(30);

    act(() => {
      handlers.onEdit(customJob);
    });
    values =
      mockForm.setFieldsValue.mock.calls[
        mockForm.setFieldsValue.mock.calls.length - 1
      ]?.[0];
    expect(values.cronType).toBe("custom");
    expect(values.cronCustom).toBe("*/15 * * * *");
  });

  it("handleEdit prefills one-time jobs including repeat settings", async () => {
    const handlers = await renderPage({ jobs: [repeatingJob] });
    act(() => {
      handlers.onEdit(repeatingJob);
    });

    const values =
      mockForm.setFieldsValue.mock.calls[
        mockForm.setFieldsValue.mock.calls.length - 1
      ]?.[0];
    expect(values.scheduleType).toBe("once");
    expect(values.onceRepeatEnabled).toBe(true);
    expect(values.onceRepeatEveryDays).toBe(3);
    expect(values.onceRepeatEndType).toBe("count");
    expect(values.onceRepeatCount).toBe(5);
  });

  it("handleEdit serializes structured request input to pretty JSON", async () => {
    const withInput = {
      ...recurringJob,
      request: { input: { key: "value" } },
    };
    const handlers = await renderPage({ jobs: [withInput] });
    act(() => {
      handlers.onEdit(withInput);
    });
    const values =
      mockForm.setFieldsValue.mock.calls[
        mockForm.setFieldsValue.mock.calls.length - 1
      ]?.[0];
    expect(values.request.input).toBe(
      JSON.stringify({ key: "value" }, null, 2),
    );
  });
});

// ---------------------------------------------------------------------------
// Drawer submit: schedule building, task-type handling, create vs update
// ---------------------------------------------------------------------------
describe("CronJobsPage drawer submit", () => {
  async function renderPage(overrides: Record<string, unknown> = {}) {
    mockHookReturn(overrides);
    renderWithProviders(<CronJobsPage />);
    await waitFor(() => expect(capturedDrawer.props).toBeTruthy());
    return capturedDrawer.props;
  }

  it("builds a daily cron schedule and creates the job, closing the drawer on success", async () => {
    const createJob = vi.fn().mockResolvedValue(true);
    const drawer = await renderPage({ createJob });
    // open the drawer first
    const createBtn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("cronJobs.createJob"));
    fireEvent.click(createBtn!);
    await waitFor(() => expect(screen.getByTestId("job-drawer")).toBeTruthy());

    await act(async () => {
      await drawer.onSubmit({
        name: "New Job",
        task_type: "text",
        scheduleType: "cron",
        cronType: "daily",
        cronTime: dayjs().hour(7).minute(45),
        schedule: { timezone: "UTC" },
        request: { input: "{}" },
      });
    });

    expect(createJob).toHaveBeenCalledTimes(1);
    const submitted = createJob.mock.calls[0][0];
    expect(submitted.schedule).toEqual({
      timezone: "UTC",
      type: "cron",
      cron: "45 7 * * *",
    });
    // text tasks drop the request object and intermediate form keys
    expect(submitted.request).toBeUndefined();
    expect(submitted.scheduleType).toBeUndefined();
    expect(submitted.cronType).toBeUndefined();
    // success closes the drawer
    await waitFor(() => expect(screen.queryByTestId("job-drawer")).toBeNull());
  });

  it("builds a one-time schedule with count-based repeat and updates when editing", async () => {
    const updateJob = vi.fn().mockResolvedValue(true);
    const createJob = vi.fn().mockResolvedValue(true);
    await renderPage({ updateJob, createJob });

    // Enter edit mode so submit takes the update path
    await waitFor(() => expect(capturedColumns.handlers).toBeTruthy());
    act(() => {
      capturedColumns.handlers.onEdit(recurringJob);
    });

    // Re-read after re-render: onSubmit now closes over editingJob=job
    await act(async () => {
      await capturedDrawer.props.onSubmit({
        name: "Edited",
        task_type: "text",
        scheduleType: "once",
        onceRunAt: "2026-09-15T08:30:00",
        onceRepeatEnabled: true,
        onceRepeatEveryDays: "4",
        onceRepeatEndType: "count",
        onceRepeatCount: "3",
        schedule: {},
      });
    });

    expect(updateJob).toHaveBeenCalledTimes(1);
    expect(createJob).not.toHaveBeenCalled();
    const [id, submitted] = updateJob.mock.calls[0];
    expect(id).toBe("job-1");
    expect(submitted.schedule.type).toBe("once");
    expect(submitted.schedule.run_at).toBe("2026-09-15T08:30:00");
    expect(submitted.schedule.repeat_every_days).toBe(4);
    expect(submitted.schedule.repeat_end_type).toBe("count");
    expect(submitted.schedule.repeat_count).toBe(3);
    expect(submitted.schedule.repeat_until).toBeUndefined();
  });

  it("builds an until-bounded repeat and keeps a missing run_at undefined", async () => {
    const createJob = vi.fn().mockResolvedValue(false);
    await renderPage({ createJob });
    // Open the drawer so the "stays open on failure" assertion is meaningful
    const createBtn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("cronJobs.createJob"));
    fireEvent.click(createBtn!);
    await waitFor(() => expect(screen.getByTestId("job-drawer")).toBeTruthy());

    await act(async () => {
      await capturedDrawer.props.onSubmit({
        name: "NoRunAt",
        task_type: "text",
        scheduleType: "once",
        onceRepeatEnabled: true,
        onceRepeatEndType: "until",
        onceRepeatUntil: "2026-10-01T00:00:00",
        onceRepeatEveryDays: "2",
        schedule: { timezone: "UTC" },
      });
    });

    const submitted = createJob.mock.calls[0][0];
    expect(submitted.schedule.run_at).toBeUndefined();
    expect(submitted.schedule.repeat_until).toBe("2026-10-01T00:00:00");
    // failed submit keeps the drawer open
    await waitFor(() => expect(capturedDrawer.props.open).toBe(true));
  });

  it("builds weekly and custom cron schedules", async () => {
    const createJob = vi.fn().mockResolvedValue(false);
    const drawer = await renderPage({ createJob });

    await act(async () => {
      await drawer.onSubmit({
        name: "Weekly",
        task_type: "text",
        scheduleType: "cron",
        cronType: "weekly",
        cronTime: dayjs().hour(10).minute(15),
        cronDaysOfWeek: ["mon", "fri"],
        schedule: {},
      });
    });
    expect(createJob.mock.calls[0][0].schedule.cron).toBe("15 10 * * mon,fri");

    await act(async () => {
      await drawer.onSubmit({
        name: "Custom",
        task_type: "text",
        scheduleType: "cron",
        cronType: "custom",
        cronCustom: "*/5 * * * *",
        schedule: {},
      });
    });
    expect(createJob.mock.calls[1][0].schedule.cron).toBe("*/5 * * * *");

    // Hourly default when no cronType/time fields are present
    await act(async () => {
      await drawer.onSubmit({
        name: "Plain",
        task_type: "text",
        scheduleType: "cron",
        schedule: {},
      });
    });
    expect(createJob.mock.calls[2][0].schedule.cron).toBe("0 9 * * *");
  });

  it("parses agent-task request input JSON and keeps it on parse failure", async () => {
    const createJob = vi.fn().mockResolvedValue(false);
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const drawer = await renderPage({ createJob });

    await act(async () => {
      await drawer.onSubmit({
        name: "Agent",
        task_type: "agent",
        scheduleType: "cron",
        schedule: {},
        request: { input: '{"a":1}' },
      });
    });
    expect(createJob.mock.calls[0][0].request.input).toEqual({ a: 1 });

    await act(async () => {
      await drawer.onSubmit({
        name: "AgentBad",
        task_type: "agent",
        scheduleType: "cron",
        schedule: {},
        request: { input: "{not json" },
      });
    });
    expect(createJob.mock.calls[1][0].request.input).toBe("{not json");
    expect(consoleSpy).toHaveBeenCalled();

    // Agent task without a request object gets one
    await act(async () => {
      await drawer.onSubmit({
        name: "AgentNoReq",
        task_type: "agent",
        scheduleType: "cron",
        schedule: {},
      });
    });
    expect(createJob.mock.calls[2][0].request).toEqual({});
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// Template flow + create defaults
// ---------------------------------------------------------------------------
describe("CronJobsPage template flow", () => {
  it("create prefills defaults with the user timezone and opens the drawer", async () => {
    mockApi.getUserTimezone.mockResolvedValue({ timezone: "Asia/Shanghai" });
    mockHookReturn();
    renderWithProviders(<CronJobsPage />);

    // Let the timezone fetch settle so the ref holds the fetched value
    await act(async () => {
      await new Promise((res) => setTimeout(res, 0));
    });

    const createBtn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("cronJobs.createJob"));
    fireEvent.click(createBtn!);

    await waitFor(() => {
      expect(screen.getByTestId("job-drawer")).toBeTruthy();
    });
    const values =
      mockForm.setFieldsValue.mock.calls[
        mockForm.setFieldsValue.mock.calls.length - 1
      ]?.[0];
    expect(values.schedule.timezone).toBe("Asia/Shanghai");
    expect(capturedDrawer.props.editingJob).toBeNull();
  });

  it("applyTemplate closes the picker, resets the form and opens the drawer", async () => {
    mockHookReturn();
    renderWithProviders(<CronJobsPage />);
    await waitFor(() => expect(capturedTemplate.props).toBeTruthy());

    // Open the picker, then use a template
    const templateBtn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("cronJobs.createFromTemplate"));
    fireEvent.click(templateBtn!);
    await waitFor(() =>
      expect(screen.getByTestId("template-modal")).toBeTruthy(),
    );

    act(() => {
      capturedTemplate.props.onUseTemplate({ name: "From Template" });
    });

    expect(mockForm.resetFields).toHaveBeenCalled();
    const values =
      mockForm.setFieldsValue.mock.calls[
        mockForm.setFieldsValue.mock.calls.length - 1
      ]?.[0];
    expect(values.name).toBe("From Template");
    expect(values.schedule.timezone).toBe("UTC");
    await waitFor(() => expect(capturedDrawer.props.open).toBe(true));
    expect(capturedDrawer.props.editingJob).toBeNull();
  });

  it("drawer close resets editing state", async () => {
    mockHookReturn({ jobs: [recurringJob] });
    renderWithProviders(<CronJobsPage />);
    await waitFor(() => expect(capturedColumns.handlers).toBeTruthy());

    act(() => {
      capturedColumns.handlers.onEdit(recurringJob);
    });
    expect(capturedDrawer.props.editingJob).toBe(recurringJob);

    act(() => {
      capturedDrawer.props.onClose();
    });
    await waitFor(() => expect(capturedDrawer.props.open).toBe(false));
    expect(capturedDrawer.props.editingJob).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// formatSchedule via mobile cards + dispatch target loading edge cases
// ---------------------------------------------------------------------------
describe("CronJobsPage mobile schedule formatting", () => {
  beforeEach(() => {
    setMatchMedia(true);
  });

  it("formats hourly, daily, weekly, custom and once schedules", async () => {
    const onceAt = dayjs().add(2, "day");
    mockHookReturn({
      jobs: [
        {
          ...recurringJob,
          id: "j-h",
          schedule: { type: "cron", cron: "0 * * * *" },
        },
        {
          ...recurringJob,
          id: "j-d",
          schedule: { type: "cron", cron: "0 9 * * *" },
        },
        {
          ...recurringJob,
          id: "j-w",
          schedule: { type: "cron", cron: "0 9 * * mon,wed" },
        },
        {
          ...recurringJob,
          id: "j-c",
          schedule: { type: "cron", cron: "*/15 * * * *" },
        },
        {
          ...oneTimeJob,
          id: "j-o",
          schedule: {
            type: "once",
            run_at: onceAt.format("YYYY-MM-DDTHH:mm:ss"),
          },
        },
        { ...oneTimeJob, id: "j-n", schedule: { type: "once" } },
      ],
    });
    renderWithProviders(<CronJobsPage />);

    await waitFor(() =>
      expect(screen.getByText("cronJobs.cronTypeHourly")).toBeTruthy(),
    );
    expect(screen.getByText("cronJobs.cronTypeDaily 09:00")).toBeTruthy();
    expect(
      screen.getByText(
        "cronJobs.cronTypeWeekly cronJobs.cronDayMon,cronJobs.cronDayWed",
      ),
    ).toBeTruthy();
    expect(screen.getByText("*/15 * * * *")).toBeTruthy();
    expect(screen.getByText(onceAt.format("YYYY-MM-DD HH:mm"))).toBeTruthy();
    expect(screen.getByText("-")).toBeTruthy();
  });

  it("mobile action buttons drive toggle, execute-now and history", async () => {
    const toggleEnabled = vi.fn();
    const executeNow = vi.fn();
    mockHookReturn({ jobs: [recurringJob], toggleEnabled, executeNow });
    renderWithProviders(<CronJobsPage />);

    await waitFor(() => expect(screen.getByText("Daily Report")).toBeTruthy());
    fireEvent.click(screen.getByText("cronJobs.disable"));
    expect(toggleEnabled).toHaveBeenCalledWith(recurringJob);

    fireEvent.click(screen.getByText("cronJobs.executeNow"));
    expect(executeNow).toHaveBeenCalledWith("job-1");

    fireEvent.click(screen.getByText("cronJobs.executionHistory"));
    await waitFor(() =>
      expect(mockApi.getCronJobHistory).toHaveBeenCalledWith("job-1"),
    );
  });
});

describe("CronJobsPage schedule filter", () => {
  it("filters the table by schedule type", async () => {
    mockHookReturn({ jobs: [recurringJob, oneTimeJob] });
    renderWithProviders(<CronJobsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("cron-table").textContent).toBe("rows:2"),
    );

    fireEvent.change(screen.getByTestId("schedule-filter"), {
      target: { value: "once" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("cron-table").textContent).toBe("rows:1"),
    );

    fireEvent.change(screen.getByTestId("schedule-filter"), {
      target: { value: "all" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("cron-table").textContent).toBe("rows:2"),
    );
  });
});

describe("CronJobsPage bootstrap edge cases", () => {
  it("falls back to console channel when dispatch targets fail to load", async () => {
    mockApi.listCronDispatchTargets.mockRejectedValue(new Error("no targets"));
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    mockHookReturn();
    renderWithProviders(<CronJobsPage />);

    await waitFor(() => expect(capturedDrawer.props).toBeTruthy());
    await waitFor(() =>
      expect(capturedDrawer.props.targetChannels).toEqual(["console"]),
    );
    expect(capturedDrawer.props.targetItems).toEqual([]);
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it("keeps UTC when the timezone fetch fails", async () => {
    mockApi.getUserTimezone.mockRejectedValue(new Error("no tz"));
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    mockHookReturn();
    renderWithProviders(<CronJobsPage />);

    // Wait for the failed fetch to settle, then create: defaults use the
    // timezone ref, which must still be UTC
    await act(async () => {
      await new Promise((res) => setTimeout(res, 0));
    });
    const createBtn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("cronJobs.createJob"));
    fireEvent.click(createBtn!);
    await waitFor(() => {
      const values =
        mockForm.setFieldsValue.mock.calls[
          mockForm.setFieldsValue.mock.calls.length - 1
        ]?.[0];
      expect(values?.schedule?.timezone).toBe("UTC");
    });
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it("places offset-suffixed once jobs on the calendar", async () => {
    const jobWithOffset = {
      ...oneTimeJob,
      id: "job-tz",
      schedule: {
        type: "once",
        run_at: dayjs().add(1, "day").toISOString(),
        timezone: "UTC",
      },
    };
    mockHookReturn({ jobs: [jobWithOffset] });
    renderWithProviders(<CronJobsPage />);
    fireEvent.click(screen.getByTitle("cronJobs.calendarView"));
    await waitFor(() => {
      expect(screen.getByText(/Once Task/)).toBeTruthy();
    });
  });
});
