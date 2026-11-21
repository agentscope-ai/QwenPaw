import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import api from "../../../api";
import { useAuthStore } from "../../../stores/authStore";
import { useAgentStore } from "../../../stores/agentStore";
import CronJobsPage from "./index";

const fixture = vi.hoisted(() => ({
  form: { resetFields: vi.fn(), setFieldsValue: vi.fn() },
  destroy: vi.fn(),
}));
vi.mock("../../../api", () => ({
  default: {
    getUserTimezone: vi.fn(),
    listCronDispatchTargets: vi.fn(),
    getCronJobHistory: vi.fn(),
  },
}));
vi.mock("../../../components/PageHeader", () => ({
  PageHeader: ({ extra }: { extra: React.ReactNode }) => <div>{extra}</div>,
}));
vi.mock("react-i18next", async (original) => ({
  ...(await original<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string, values?: { name?: string }) =>
      values?.name ? `${key}:${values.name}` : key,
  }),
}));
vi.mock("./components", () => ({
  createColumns: (handlers: unknown) => handlers,
  useCronJobs: () => ({
    jobs:
      useAuthStore.getState().user?.id === "account-a"
        ? [
            {
              id: "a",
              name: "private A job",
              schedule: { type: "cron" },
              enabled: true,
            },
          ]
        : [],
    loading: false,
    createJob: vi.fn(),
    updateJob: vi.fn(),
    deleteJob: vi.fn(),
    toggleEnabled: vi.fn(),
    executeNow: vi.fn(),
    authorizeJob: vi.fn(),
  }),
  JobDrawer: ({
    open,
    editingJob,
  }: {
    open: boolean;
    editingJob: { name: string } | null;
  }) => (open ? <div>editing:{editingJob?.name}</div> : null),
  TemplatePickerModal: () => null,
  DEFAULT_FORM_VALUES: { schedule: {} },
}));
vi.mock("@agentscope-ai/design", () => {
  const Modal = Object.assign(
    ({
      visible,
      children,
      title,
    }: {
      visible: boolean;
      children: React.ReactNode;
      title: React.ReactNode;
    }) =>
      visible ? (
        <section>
          {title}
          {children}
        </section>
      ) : null,
    {
      confirm: (options: { content: string }) => {
        const element = document.createElement("div");
        element.dataset.reviewConfirm = "yes";
        element.textContent = options.content;
        document.body.append(element);
        return {
          destroy: () => {
            fixture.destroy();
            element.remove();
          },
        };
      },
    },
  );
  const Box = ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  );
  return {
    Button: ({
      children,
      onClick,
    }: {
      children: React.ReactNode;
      onClick: () => void;
    }) => <button onClick={onClick}>{children}</button>,
    Card: Box,
    Dropdown: Box,
    Popover: Box,
    Select: () => null,
    Modal,
    Form: { useForm: () => [fixture.form] },
    Table: ({
      dataSource,
      columns,
    }: {
      dataSource: unknown[];
      columns: Record<string, (job: unknown) => void>;
    }) =>
      dataSource.length ? (
        <div>
          <button onClick={() => columns.onEdit(dataSource[0])}>
            edit first
          </button>
          <button onClick={() => columns.onExecuteNow(dataSource[0])}>
            execute first
          </button>
          <button onClick={() => columns.onViewHistory(dataSource[0])}>
            history first
          </button>
        </div>
      ) : (
        <div>empty task list</div>
      ),
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getUserTimezone).mockResolvedValue({ timezone: "UTC" });
  vi.mocked(api.listCronDispatchTargets).mockResolvedValue({
    items: [],
    channels: ["console"],
  });
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "account-a", platform_role: "member" } as never,
  });
  useAgentStore.setState({ selectedAgent: "default", agents: [] });
});
afterEach(() => {
  cleanup();
  document
    .querySelectorAll("[data-review-confirm]")
    .forEach((element) => element.remove());
});
function switchAccount() {
  act(() => {
    useAuthStore.setState({
      user: { id: "account-b", platform_role: "member" } as never,
    });
  });
}

it("clears the previous account's open job editor", () => {
  render(<CronJobsPage />);
  fireEvent.click(screen.getByText("edit first"));
  expect(screen.getByText("editing:private A job")).toBeVisible();
  switchAccount();
  expect(screen.queryByText("editing:private A job")).not.toBeInTheDocument();
  expect(screen.getByText("empty task list")).toBeVisible();
});

it("destroys only this page's private confirmation when the account changes", () => {
  render(<CronJobsPage />);
  fireEvent.click(screen.getByText("execute first"));
  expect(
    screen.getByText("cronJobs.executeNowContent:private A job"),
  ).toBeVisible();
  const unrelated = document.createElement("div");
  unrelated.textContent = "unrelated confirmation";
  unrelated.dataset.reviewConfirm = "other";
  document.body.append(unrelated);
  switchAccount();
  expect(
    screen.queryByText("cronJobs.executeNowContent:private A job"),
  ).not.toBeInTheDocument();
  expect(screen.getByText("unrelated confirmation")).toBeVisible();
  expect(fixture.destroy).toHaveBeenCalledOnce();
});

it("does not show a history response from the previous account", async () => {
  let finish!: (records: never[]) => void;
  vi.mocked(api.getCronJobHistory).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  render(<CronJobsPage />);
  fireEvent.click(screen.getByText("history first"));
  expect(screen.getByText("cronJobs.historyTitle:private A job")).toBeVisible();
  switchAccount();
  await act(async () => {
    finish([]);
  });
  await waitFor(() =>
    expect(
      screen.queryByText("cronJobs.historyTitle:private A job"),
    ).not.toBeInTheDocument(),
  );
});
