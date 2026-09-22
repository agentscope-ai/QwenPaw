// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PawAppTaskCard from "./PawAppTaskCard";
import {
  answerPawAppTask,
  getPawAppTask,
  openPawAppSetup,
  openPawAppTask,
  parsePawAppOpenResult,
  parsePawAppTaskResult,
} from "../../../../api/modules/pawappTasks";
import type { PawAppTask } from "../../../../api/modules/pawappTasks";
import type { ToolCallContent } from "../shared/types";
import { PawAppTaskSurfaceProvider } from "../PawAppTaskSurfaceProvider";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../shared", () => ({
  ToolCardShell: ({
    title,
    children,
  }: {
    title: string;
    children: React.ReactNode;
  }) => <section aria-label={title}>{children}</section>,
  DefaultBlock: ({ content }: { content: string }) => <pre>{content}</pre>,
}));
vi.mock("../../../../api/modules/pawappTasks", async (original) => ({
  ...(await original<typeof import("../../../../api/modules/pawappTasks")>()),
  answerPawAppTask: vi.fn(),
  getPawAppTask: vi.fn(),
  openPawAppSetup: vi.fn(),
  openPawAppTask: vi.fn(),
}));

const task: PawAppTask = {
  task_id: "task-1",
  action_id: "analyze",
  scope: {
    principal_id: "alice",
    app_id: "qwenpaw-data",
    workspace_id: "sales",
  },
  status: "pending",
  recovery_state: "none",
  event_sequence: 1,
  text_result: null,
};
function content(value: unknown = task): ToolCallContent {
  return {
    id: "call-1",
    name: "delegate",
    type: "tool_call",
    params: {},
    status: "done",
    result: JSON.stringify({
      kind: "pawapp_task",
      state: "accepted",
      app_id: "qwenpaw-data",
      workspace_id: "sales",
      task: value,
    }),
  };
}
function observedContent(
  value: unknown,
  id: string,
  name: "delegate" | "get_app_task",
): ToolCallContent {
  return { ...content(value), id, name };
}
const api = vi.mocked(getPawAppTask);
const answerApi = vi.mocked(answerPawAppTask);
const openApi = vi.mocked(openPawAppTask);
const setupApi = vi.mocked(openPawAppSetup);
beforeEach(() => {
  vi.useFakeTimers();
  window.history.replaceState(null, "", "/");
  api.mockReset();
  answerApi.mockReset();
  openApi.mockReset();
  setupApi.mockReset();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
const flush = () =>
  act(async () => {
    await Promise.resolve();
  });

describe("PawApp task cards", () => {
  it("renders one canonical surface and folds repeated status checks", async () => {
    const latest: PawAppTask = {
      ...task,
      status: "waiting_for_approval",
      event_sequence: 9,
    };
    api.mockResolvedValue(latest);
    render(
      <PawAppTaskSurfaceProvider scopeKey="default:chat-one">
        <PawAppTaskCard
          content={observedContent(task, "delegate-call", "delegate")}
        />
        <PawAppTaskCard
          content={observedContent(
            { ...task, status: "running", event_sequence: 5 },
            "status-call-one",
            "get_app_task",
          )}
        />
        <PawAppTaskCard
          content={observedContent(latest, "status-call-two", "get_app_task")}
        />
      </PawAppTaskSurfaceProvider>,
    );
    await flush();
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toBe(
      "tool.pawappTask.status.waiting_for_approval",
    );
    expect(screen.getByText("tool.pawappTask.statusChecksFolded")).toBeTruthy();
    expect(api).toHaveBeenCalledTimes(1);
  });

  it("keeps one compact open-task prompt beside the latest explicit status check", async () => {
    const withProject: PawAppTask = {
      ...task,
      project_ref: {
        schema_version: 1,
        app_id: "qwenpaw-data",
        project_id: "session-1",
        kind: "analysis-session",
        revision: 1,
      },
    };
    const latest = {
      ...withProject,
      status: "running" as const,
      event_sequence: 3,
    };
    api.mockResolvedValue(latest);
    openApi.mockResolvedValue({
      schema_version: 1,
      app_id: "qwenpaw-data",
      handoff_id: "handoff-1",
      path: "/apps/qwenpaw-data?handoff=handoff-1",
      project_ref: withProject.project_ref!,
    });

    render(
      <PawAppTaskSurfaceProvider scopeKey="default:chat-one">
        <PawAppTaskCard
          content={observedContent(withProject, "delegate-call", "delegate")}
        />
        <PawAppTaskCard
          content={observedContent(
            { ...withProject, event_sequence: 2 },
            "status-call-one",
            "get_app_task",
          )}
        />
        <PawAppTaskCard
          content={observedContent(latest, "status-call-two", "get_app_task")}
        />
      </PawAppTaskSurfaceProvider>,
    );
    await flush();

    expect(screen.getAllByText("tool.pawappTask.openTaskPrompt")).toHaveLength(
      1,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "tool.pawappTask.openTask" }),
    );
    await flush();

    expect(openApi).toHaveBeenCalledWith("qwenpaw-data", "sales", "task-1");
    expect(window.location.pathname + window.location.search).toBe(
      "/apps/qwenpaw-data?handoff=handoff-1",
    );
  });

  it("ignores stale terminal responses and keeps following the newer run state", async () => {
    api
      .mockResolvedValueOnce({ ...task, status: "failed", event_sequence: 2 })
      .mockResolvedValueOnce({
        ...task,
        status: "succeeded",
        event_sequence: 4,
        text_result: "Complete",
      });
    render(
      <PawAppTaskCard
        content={content({ ...task, status: "running", event_sequence: 3 })}
      />,
    );
    await flush();
    expect(screen.getByRole("status").textContent).toBe(
      "tool.pawappTask.status.running",
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText("Complete")).toBeTruthy();
  });

  it("uses newer snapshots for the same handle without regressing on refresh", async () => {
    api.mockResolvedValue(task);
    const view = render(<PawAppTaskCard content={content()} />);
    await flush();
    view.rerender(
      <PawAppTaskCard
        content={content({
          ...task,
          status: "succeeded",
          event_sequence: 3,
          text_result: "Saved result",
        })}
      />,
    );
    await flush();
    expect(screen.getByRole("status").textContent).toBe(
      "tool.pawappTask.status.succeeded",
    );
    expect(screen.getByText("Saved result")).toBeTruthy();
    const calls = api.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(api).toHaveBeenCalledTimes(calls);
  });

  it("refreshes persisted handles through progress and explicit completion", async () => {
    api
      .mockResolvedValueOnce({
        ...task,
        status: "running",
        event_sequence: 2,
        text_result: "Revenue is",
      })
      .mockResolvedValueOnce({
        ...task,
        status: "succeeded",
        event_sequence: 3,
        text_result: "Revenue is 42.",
      });
    render(<PawAppTaskCard content={content()} />);
    await flush();
    expect(screen.getByRole("status").textContent).toBe(
      "tool.pawappTask.status.running",
    );
    expect(screen.getByText("Revenue is")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByRole("status").textContent).toBe(
      "tool.pawappTask.status.succeeded",
    );
    expect(screen.getByText("Revenue is 42.")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(api).toHaveBeenCalledTimes(2);
  });

  it("keeps recovery distinct from success and errors preserve partial output", async () => {
    api
      .mockResolvedValueOnce({
        ...task,
        status: "running",
        recovery_state: "reconciling",
        text_result: "partial",
        event_sequence: 2,
      })
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        ...task,
        status: "interrupted",
        event_sequence: 3,
        text_result: "partial",
      });
    render(<PawAppTaskCard content={content()} />);
    await flush();
    expect(screen.getByRole("status").textContent).toBe(
      "tool.pawappTask.status.recovering",
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByRole("status").textContent).toBe(
      "tool.pawappTask.status.unavailable",
    );
    expect(screen.getByText("partial")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "tool.pawappTask.refresh" }),
    );
    await flush();
    expect(screen.getByRole("status").textContent).toBe(
      "tool.pawappTask.status.interrupted",
    );
  });

  it("shows blocked setup without starting work or trusting an external URL", async () => {
    const value = {
      ...content(),
      result: JSON.stringify({
        kind: "pawapp_task",
        state: "blocked",
        app_id: "qwenpaw-data",
        workspace_id: "sales",
        reason: "analysis_model_missing",
        settings_entry: "https://untrusted.test",
      }),
    };
    render(<PawAppTaskCard content={value} />);
    expect(screen.getByRole("status").textContent).toBe(
      "tool.pawappTask.status.blocked",
    );
    expect(screen.getByRole("link").getAttribute("href")).toBe(
      "/apps/qwenpaw-data",
    );
    await flush();
    expect(api).not.toHaveBeenCalled();
  });

  it("opens linked setup only through a Host-resolved App path", async () => {
    const waiting: PawAppTask = {
      ...task,
      status: "waiting_for_setup",
      event_sequence: 2,
      setup_request_id: "setup-1",
      setup_attempt: 1,
    };
    api.mockResolvedValue(waiting);
    setupApi.mockResolvedValue({
      schema_version: 1,
      app_id: "qwenpaw-data",
      request_id: "setup-1",
      entry_id: "creator.video-model-settings",
      presentation: "app_entry",
      path: "/apps/qwenpaw-data?setup=video&setupRequest=setup-1",
    });
    render(<PawAppTaskCard content={content(waiting)} />);

    fireEvent.click(
      screen.getByRole("button", { name: "tool.pawappTask.completeSetup" }),
    );
    await flush();

    expect(setupApi).toHaveBeenCalledWith("qwenpaw-data", "sales", "setup-1");
    expect(window.location.pathname + window.location.search).toBe(
      "/apps/qwenpaw-data?setup=video&setupRequest=setup-1",
    );
  });

  it("keeps the approval command stable across a rejected retry and refreshes immediately", async () => {
    const waiting: PawAppTask = {
      ...task,
      status: "waiting_for_approval",
      event_sequence: 2,
      input_request: {
        request_id: "approval-1",
        title: "Approve video generation",
        questions: [
          {
            question: "Run this generation?",
            description: "Provider: local-test",
            multi_select: false,
            options: [
              { label: "Approve once", description: "Run once" },
              { label: "Do not run", description: "Decline" },
            ],
          },
        ],
      },
    };
    let finishFirst!: () => void;
    api.mockResolvedValue(waiting);
    answerApi
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishFirst = () =>
              resolve({
                protocol_version: 1,
                task_id: "task-1",
                command_id: "ignored-by-component",
                kind: "answer",
                request_id: "approval-1",
                state: "rejected",
                reason: "retry",
              });
          }),
      )
      .mockResolvedValueOnce({
        protocol_version: 1,
        task_id: "task-1",
        command_id: "ignored-by-component",
        kind: "answer",
        request_id: "approval-1",
        state: "accepted",
        reason: null,
      });
    render(<PawAppTaskCard content={content(waiting)} />);
    fireEvent.click(screen.getByRole("radio", { name: /Approve once/ }));
    fireEvent.click(
      screen.getByRole("button", { name: "tool.pawappTask.submitAnswer" }),
    );

    expect(
      screen.getByRole("button", {
        name: "tool.pawappTask.submittingAnswer",
      }),
    ).toBeDisabled();
    finishFirst();
    await flush();
    const firstCommandId = answerApi.mock.calls[0][3];
    expect(answerApi.mock.calls[0].slice(0, 3)).toEqual([
      "qwenpaw-data",
      "sales",
      "task-1",
    ]);
    expect(answerApi.mock.calls[0].slice(4)).toEqual([
      "approval-1",
      [
        {
          question: "Run this generation?",
          selected_options: ["Approve once"],
          custom_text: null,
        },
      ],
    ]);
    expect(api.mock.calls.length).toBeGreaterThan(1);

    fireEvent.click(
      screen.getByRole("button", { name: "tool.pawappTask.submitAnswer" }),
    );
    await flush();
    expect(answerApi).toHaveBeenCalledTimes(2);
    expect(answerApi.mock.calls[1][3]).toBe(firstCommandId);
  });

  it("submits multi-select and custom answers without App-specific fields", async () => {
    const waiting: PawAppTask = {
      ...task,
      status: "waiting_for_input",
      event_sequence: 2,
      input_request: {
        request_id: "input-1",
        title: "Choose output",
        questions: [
          {
            question: "Formats",
            description: "Select formats",
            multi_select: true,
            options: [
              { label: "Video", description: "Composed video" },
              { label: "Captions", description: "Caption track" },
            ],
          },
          {
            question: "Delivery note",
            description: "Choose or enter a note",
            multi_select: false,
            options: [
              { label: "Standard", description: "Default note" },
              { label: "None", description: "No preset" },
            ],
          },
        ],
      },
    };
    api.mockResolvedValue(waiting);
    answerApi.mockResolvedValue({
      protocol_version: 1,
      task_id: "task-1",
      command_id: "ignored-by-component",
      kind: "answer",
      request_id: "input-1",
      state: "accepted",
      reason: null,
    });
    render(<PawAppTaskCard content={content(waiting)} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Video/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Captions/ }));
    fireEvent.change(screen.getAllByRole("textbox")[1], {
      target: { value: "  Deliver privately  " },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "tool.pawappTask.submitAnswer" }),
    );
    await flush();

    expect(answerApi.mock.calls[0][5]).toEqual([
      {
        question: "Formats",
        selected_options: ["Video", "Captions"],
        custom_text: null,
      },
      {
        question: "Delivery note",
        selected_options: [],
        custom_text: "Deliver privately",
      },
    ]);
  });

  it("replaces stale input requests and rejects malformed task contracts", async () => {
    const request = {
      request_id: "approval-1",
      title: "First request",
      questions: [
        {
          question: "First question",
          description: "",
          multi_select: false,
          options: [
            { label: "Approve once", description: "" },
            { label: "Do not run", description: "" },
          ],
        },
      ],
    };
    const first: PawAppTask = {
      ...task,
      status: "waiting_for_approval",
      event_sequence: 2,
      input_request: request,
    };
    api.mockResolvedValue(first);
    const view = render(<PawAppTaskCard content={content(first)} />);
    fireEvent.click(screen.getByRole("radio", { name: /Approve once/ }));

    const second: PawAppTask = {
      ...first,
      event_sequence: 3,
      input_request: {
        ...request,
        request_id: "approval-2",
        title: "Replacement request",
        questions: [
          {
            ...request.questions[0],
            question: "Replacement question",
          },
        ],
      },
    };
    view.rerender(<PawAppTaskCard content={content(second)} />);
    await flush();
    expect(screen.queryByText("First question")).toBeNull();
    expect(screen.getByText("Replacement question")).toBeTruthy();
    expect(
      screen
        .getAllByRole("radio")
        .every((input) => !(input as HTMLInputElement).checked),
    ).toBe(true);

    expect(
      parsePawAppTaskResult(
        content({
          ...first,
          input_request: {
            ...request,
            questions: [
              {
                ...request.questions[0],
                options: [{ label: "Only one", description: "" }],
              },
            ],
          },
        }).result,
      ),
    ).toBeNull();
  });

  it("aborts when unmounted and ignores a late response from another handle", async () => {
    let oldResolve!: (value: PawAppTask) => void;
    api
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            oldResolve = resolve;
          }),
      )
      .mockResolvedValueOnce({
        ...task,
        task_id: "task-2",
        status: "running",
        event_sequence: 2,
      });
    const view = render(<PawAppTaskCard content={content()} />);
    const signal = api.mock.calls[0][3];
    view.rerender(
      <PawAppTaskCard content={content({ ...task, task_id: "task-2" })} />,
    );
    await flush();
    expect(signal.aborted).toBe(true);
    await act(async () => {
      oldResolve({ ...task, status: "succeeded", text_result: "stale" });
    });
    expect(screen.queryByText("stale")).toBeNull();
    expect(screen.getByRole("status").textContent).toBe(
      "tool.pawappTask.status.running",
    );
  });

  it("parses both renderers' text blocks and rejects mismatched scope", () => {
    expect(
      parsePawAppTaskResult([{ type: "text", text: content().result }])?.task
        ?.task_id,
    ).toBe("task-1");
    expect(
      parsePawAppTaskResult(
        content({ ...task, scope: { ...task.scope, app_id: "other" } }).result,
      ),
    ).toBeNull();
    expect(parsePawAppTaskResult("{invalid")).toBeNull();
  });

  it("mints a handoff before opening an existing App project", async () => {
    const withProject: PawAppTask = {
      ...task,
      project_ref: {
        schema_version: 1,
        app_id: "qwenpaw-data",
        project_id: "session-1",
        kind: "analysis-session",
        revision: 1,
      },
    };
    api.mockResolvedValue(withProject);
    openApi.mockResolvedValue({
      schema_version: 1,
      app_id: "qwenpaw-data",
      handoff_id: "handoff-1",
      path: "/apps/qwenpaw-data?handoff=handoff-1",
      project_ref: withProject.project_ref!,
    });
    render(<PawAppTaskCard content={content(withProject)} />);

    fireEvent.click(
      screen.getByRole("button", { name: "tool.pawappTask.openApp" }),
    );
    await flush();

    expect(openApi).toHaveBeenCalledWith("qwenpaw-data", "sales", "task-1");
    expect(window.location.pathname + window.location.search).toBe(
      "/apps/qwenpaw-data?handoff=handoff-1",
    );
    expect(window.history.state).toEqual({ pawappInline: true });
  });

  it("renders app-owned progress and keeps app-only artifacts out of chat", async () => {
    const rich: PawAppTask = {
      ...task,
      status: "running",
      event_sequence: 2,
      project_ref: {
        schema_version: 1,
        app_id: "qwenpaw-data",
        project_id: "session-1",
        kind: "analysis-session",
        revision: 1,
      },
      experience: {
        schema_version: 1,
        definition_digest: "experience-digest",
        definition: {
          schema_version: 1,
          action_id: "analyze",
          title: { default: "Data analysis", translations: {} },
          steps: [
            {
              id: "read",
              label: { default: "Read data", translations: {} },
            },
            {
              id: "analyze",
              label: { default: "Analyze", translations: {} },
            },
          ],
          views: [
            {
              id: "summary",
              label: { default: "Summary", translations: {} },
              open_label: { default: "Open analysis", translations: {} },
            },
          ],
          default_view_id: "summary",
        },
        step_states: [
          { step_id: "read", status: "complete", progress: null },
          { step_id: "analyze", status: "running", progress: null },
        ],
        active_step_id: "analyze",
        context_items: [
          {
            id: "datasource",
            label: { default: "Data source", translations: {} },
            value: "sales",
          },
        ],
        view_id: "summary",
      },
      output_refs: [
        {
          schema_version: 1,
          artifact_id: "report",
          type: "qwenpaw:file",
          version: 1,
          name: "report.md",
          media_type: "text/markdown",
          size_bytes: 10,
          digest: `sha256:${"a".repeat(64)}`,
          presentation: {
            schema_version: 1,
            role: "primary",
            kind: "data/report",
            visibility: "chat",
            preview: "inline",
            rank: 0,
          },
        },
        {
          schema_version: 1,
          artifact_id: "trace",
          type: "qwenpaw:file",
          version: 1,
          name: "trace.json",
          media_type: "application/json",
          size_bytes: 10,
          digest: `sha256:${"b".repeat(64)}`,
          presentation: {
            schema_version: 1,
            role: "diagnostic",
            kind: "data/diagnostic",
            visibility: "app_only",
            preview: "none",
            rank: 300,
          },
        },
      ],
    };
    api.mockResolvedValue(rich);

    render(<PawAppTaskCard content={content(rich)} />);

    expect(screen.getByRole("region", { name: "Data analysis" })).toBeTruthy();
    expect(screen.getByText("Read data")).toBeTruthy();
    expect(screen.getByText("sales")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Open analysis/ })).toBeTruthy();
    expect(screen.getByText(/report.md/)).toBeTruthy();
    expect(screen.queryByText(/trace.json/)).toBeNull();
  });

  it("parses Host-issued open_app results and rejects external paths", () => {
    const result = {
      kind: "pawapp_open_app",
      app_id: "qwenpaw-data",
      workspace_id: "sales",
      action: {
        schema_version: 1,
        app_id: "qwenpaw-data",
        handoff_id: "handoff-1",
        path: "/apps/qwenpaw-data?handoff=handoff-1",
        project_ref: {
          schema_version: 1,
          app_id: "qwenpaw-data",
          project_id: "session-1",
          kind: "analysis-session",
          revision: 1,
        },
      },
    };
    expect(parsePawAppOpenResult(JSON.stringify(result))).toEqual(result);
    expect(
      parsePawAppOpenResult(
        JSON.stringify({
          ...result,
          action: { ...result.action, path: "https://untrusted.test" },
        }),
      ),
    ).toBeNull();
  });

  it("loads an authorized HTML artifact into a sandboxed preview", async () => {
    const complete: PawAppTask = {
      ...task,
      status: "succeeded",
      event_sequence: 3,
      text_result: "Report ready",
      output_refs: [
        {
          schema_version: 1,
          artifact_id: "artifact-1",
          type: "qwenpaw:file",
          version: 2,
          name: "report.html",
          media_type: "text/html",
          size_bytes: 32,
          digest: `sha256:${"a".repeat(64)}`,
        },
      ],
    };
    api.mockResolvedValue(complete);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("<h1>Quarterly report</h1>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<PawAppTaskCard content={content(complete)} />);
    fireEvent.click(
      screen.getByRole("button", { name: "tool.pawappTask.previewArtifact" }),
    );
    await flush();

    expect(fetchMock.mock.calls[0][0]).toContain(
      "/api/pawapps/qwenpaw-data/workspaces/sales/artifacts/artifact-1/versions/2/content",
    );
    const preview = screen.getByTitle("report.html");
    expect(preview.getAttribute("sandbox")).toBe("");
    expect(preview.getAttribute("srcdoc")).toContain("default-src 'none'");
    expect(preview.getAttribute("srcdoc")).toContain("Quarterly report");
  });
});
