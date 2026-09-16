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
  getPawAppTask,
  openPawAppTask,
  parsePawAppOpenResult,
  parsePawAppTaskResult,
} from "../../../../api/modules/pawappTasks";
import type { PawAppTask } from "../../../../api/modules/pawappTasks";
import type { ToolCallContent } from "../shared/types";

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
  getPawAppTask: vi.fn(),
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
const api = vi.mocked(getPawAppTask);
const openApi = vi.mocked(openPawAppTask);
beforeEach(() => {
  vi.useFakeTimers();
  api.mockReset();
  openApi.mockReset();
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
