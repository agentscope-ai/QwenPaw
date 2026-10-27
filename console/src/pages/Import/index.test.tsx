import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { useAgentStore } from "@/stores/agentStore";
import { useImportJob } from "./useImportJob";
import ImportPage from ".";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { agent?: string; count?: number }) =>
      values?.agent
        ? `${key}:${values.agent}`
        : values?.count
        ? `${key}:${values.count}`
        : key,
  }),
}));
vi.mock("./useImportJob", () => ({ useImportJob: vi.fn() }));
vi.mock("@/components/PageHeader", () => ({
  PageHeader: ({ current }: { current: string }) => <h1>{current}</h1>,
}));

const actions = {
  detect: vi.fn(),
  scan: vi.fn(),
  start: vi.fn(),
  retry: vi.fn(),
  cancel: vi.fn(),
  reset: vi.fn(),
};

function state(overrides = {}) {
  return {
    sources: [
      { source: "codex", name: "Codex", detected: true },
      { source: "qoder", name: "Qoder", detected: true },
    ],
    job: null,
    selectedAgent: "agent",
    loading: false,
    error: "",
    detectError: "",
    ...actions,
    ...overrides,
  };
}

function jobSnapshot(jobState: string) {
  return {
    job_id: "job",
    agent_id: "agent",
    state: jobState,
    seq: 2,
    logs: [],
    providers: [],
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ImportPage />
    </MemoryRouter>,
  );
}

describe("ImportPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAgentStore.setState({
      selectedAgent: "agent",
      agents: ["qwenpaw", "codex", "qoder"].map((backend) => ({
        id: backend === "qwenpaw" ? "agent" : backend,
        name: backend,
        description: "",
        workspace_dir: "",
        enabled: true,
        backend,
      })),
    });
    vi.mocked(actions.detect).mockResolvedValue([]);
  });

  it.each(["codex", "qoder"])(
    "blocks direct access and unmounts the workflow when switching to %s",
    (backend) => {
      vi.mocked(useImportJob).mockReturnValue(state() as never);
      useAgentStore.setState({ selectedAgent: backend });
      renderPage();
      expect(useImportJob).not.toHaveBeenCalled();
      expect(screen.getByText("portabilityImport.qwenpawOnly")).toBeVisible();

      act(() => useAgentStore.setState({ selectedAgent: "agent" }));
      expect(actions.detect).toHaveBeenCalled();
      const calls = vi.mocked(useImportJob).mock.calls.length;

      act(() => useAgentStore.setState({ selectedAgent: backend }));
      expect(useImportJob).toHaveBeenCalledTimes(calls);
      expect(screen.getByText("portabilityImport.qwenpawOnly")).toBeVisible();
      expect(screen.queryByRole("button")).toBeNull();
    },
  );

  it("detects applications and supports multi-source selection", () => {
    vi.mocked(useImportJob).mockReturnValue(state() as never);
    renderPage();

    expect(actions.detect).toHaveBeenCalled();
    expect(screen.getByRole("checkbox", { name: "Codex" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Qoder" })).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "portabilityImport.continue" }),
    );
    expect(actions.scan).toHaveBeenCalledWith(["codex", "qoder"]);
  });

  it("isolates stale Agent A sources while Agent B retries detection", async () => {
    vi.mocked(actions.detect)
      .mockReset()
      .mockRejectedValueOnce(new Error("Sources unavailable"))
      .mockResolvedValueOnce([
        { source: "qoder", name: "Qoder", detected: true },
      ]);
    vi.mocked(useImportJob).mockReturnValue(
      state({
        selectedAgent: "agent-b",
        sources: [{ source: "codex", name: "Agent A Codex", detected: true }],
        error: "Sources unavailable",
        detectError: "Sources unavailable",
      }) as never,
    );
    const view = renderPage();

    const retry = screen.getByRole("button", { name: "common.retry" });
    expect(screen.getByRole("alert")).toHaveTextContent("Sources unavailable");
    expect(screen.queryByText("Agent A Codex")).toBeNull();
    expect(screen.queryByText("portabilityImport.noSources")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "portabilityImport.continue" }),
    ).toBeNull();

    fireEvent.click(retry);
    await waitFor(() => expect(actions.detect).toHaveBeenCalledTimes(2));
    expect(actions.scan).not.toHaveBeenCalled();
    expect(actions.start).not.toHaveBeenCalled();
    expect(actions.retry).not.toHaveBeenCalled();

    vi.mocked(useImportJob).mockReturnValue(
      state({
        selectedAgent: "agent-b",
        sources: [{ source: "qoder", name: "Qoder", detected: true }],
      }) as never,
    );
    view.rerender(
      <MemoryRouter>
        <ImportPage />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Agent A Codex")).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Qoder" })).toBeChecked();
    expect(
      screen.getByRole("button", { name: "portabilityImport.continue" }),
    ).toBeEnabled();
    expect(actions.scan).not.toHaveBeenCalled();
    expect(actions.start).not.toHaveBeenCalled();
    expect(actions.retry).not.toHaveBeenCalled();
  });

  it("keeps a successful empty detection distinct from failure", () => {
    vi.mocked(useImportJob).mockReturnValue(
      state({ sources: [], error: "" }) as never,
    );
    renderPage();

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
    expect(screen.getByText("portabilityImport.noSources")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "portabilityImport.continue" }),
    ).toBeDisabled();
  });

  it("previews source changes and the destination without starting an import", async () => {
    vi.mocked(useImportJob).mockReturnValue(state() as never);
    renderPage();
    const route = within(
      screen.getByRole("region", { name: "portabilityImport.title" }),
    );
    await waitFor(() => expect(route.getByText("Codex")).toBeVisible());
    expect(
      route.getByText("portabilityImport.targetAgent:qwenpaw"),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("checkbox", { name: "Codex" }));
    await waitFor(() => expect(route.queryByText("Codex")).toBeNull());
    expect(route.getByText("Qoder")).toBeVisible();
    expect(actions.scan).not.toHaveBeenCalled();
    expect(actions.start).not.toHaveBeenCalled();
  });

  it("keeps scanning in the inventory stage without import progress", () => {
    vi.mocked(useImportJob).mockReturnValue(
      state({ job: jobSnapshot("scanning") }) as never,
    );
    renderPage();

    expect(screen.getByText("portabilityImport.scanning")).toBeVisible();
    expect(screen.queryByText("portabilityImport.importing")).toBeNull();
    expect(screen.queryByText("portabilityImport.keepOpen")).toBeNull();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(
      screen
        .getByText("portabilityImport.steps.inventory")
        .closest(".ant-steps-item"),
    ).toHaveClass("ant-steps-item-process");
  });

  it.each([
    ["running", "portabilityImport.importing", "portabilityImport.keepOpen"],
    [
      "cancelling",
      "portabilityImport.cancelling",
      "portabilityImport.cancellingHint",
    ],
    ["completed", "portabilityImport.finished", "portabilityImport.keepOpen"],
    ["failed", "portabilityImport.finished", "portabilityImport.keepOpen"],
  ])("shows %s progress with its matching copy", (jobState, title, hint) => {
    vi.mocked(useImportJob).mockReturnValue(
      state({ job: jobSnapshot(jobState) }) as never,
    );
    renderPage();

    expect(screen.queryByText("portabilityImport.scanning")).toBeNull();
    expect(screen.getByRole("heading", { name: title })).toBeVisible();
    expect(screen.getByText(hint)).toBeVisible();
    expect(screen.getByRole("progressbar")).toBeVisible();
  });

  it("shows default-selected conversations and grouped assets", () => {
    vi.mocked(useImportJob).mockReturnValue(
      state({
        selectedAgent: "other-agent",
        job: {
          job_id: "job",
          agent_id: "agent",
          state: "awaiting_selection",
          seq: 2,
          logs: [],
          providers: [
            {
              source: "codex",
              state: "ready",
              plan_id: "plan",
              sessions_total: 4,
              sessions_processed: 0,
              sessions_imported: 0,
              selection: {
                sessions: true,
                cron: ["heartbeat-1"],
                skills: ["skill-1"],
              },
              assets: [
                {
                  asset_type: "cron",
                  source_id: "heartbeat-1",
                  name: "Heartbeat",
                  state: "pending",
                  enabled: null,
                  message: "",
                  requires_sessions: true,
                },
                {
                  asset_type: "skill",
                  source_id: "skill-1",
                  name: "Review Skill",
                  state: "pending",
                  enabled: null,
                  message: "",
                  requires_sessions: false,
                },
              ],
              error: "",
            },
          ],
        },
      }) as never,
    );
    renderPage();

    expect(screen.queryByText("portabilityImport.scanning")).toBeNull();
    expect(screen.queryByText("portabilityImport.importing")).toBeNull();
    expect(screen.queryByText("portabilityImport.keepOpen")).toBeNull();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(
      screen.getByText("portabilityImport.conversations"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("portabilityImport.toolsSetup"),
    ).toBeInTheDocument();
    expect(screen.getByText("Review Skill")).toBeInTheDocument();
    expect(
      screen.getByText("portabilityImport.targetAgent:agent"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "portabilityImport.start" }),
    );
    expect(actions.start).toHaveBeenCalledWith({
      codex: expect.objectContaining({ sessions: true, skills: ["skill-1"] }),
    });
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "portabilityImport.conversations",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "portabilityImport.start" }),
    );
    expect(actions.start).toHaveBeenLastCalledWith({
      codex: expect.objectContaining({
        sessions: false,
        cron: ["heartbeat-1"],
      }),
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Heartbeat" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Review Skill" }));
    expect(
      screen.getByRole("button", { name: "portabilityImport.start" }),
    ).toBeDisabled();
  });

  it("requires an explicit confirmation before importing a plugin", () => {
    vi.mocked(useImportJob).mockReturnValue(
      state({
        job: {
          job_id: "job",
          agent_id: "agent",
          state: "awaiting_selection",
          seq: 2,
          logs: [],
          providers: [
            {
              source: "codex",
              state: "ready",
              plan_id: "plan",
              sessions_total: 0,
              sessions_processed: 0,
              sessions_imported: 0,
              selection: { plugins: [] },
              assets: [
                {
                  asset_type: "plugin",
                  source_id: "plugin-1",
                  name: "Plugin One",
                  state: "pending",
                  enabled: null,
                  message: "",
                },
              ],
              error: "",
            },
          ],
        },
      }) as never,
    );
    renderPage();

    const plugin = screen.getByRole("checkbox", { name: "Plugin One" });
    expect(plugin).not.toBeChecked();
    fireEvent.click(plugin);
    fireEvent.click(
      screen.getByRole("button", { name: "portabilityImport.start" }),
    );
    expect(actions.start).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "portabilityImport.pluginWarningConfirm",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "portabilityImport.pluginWarningAction",
      }),
    );
    expect(actions.start).toHaveBeenCalledWith(
      { codex: { plugins: ["plugin-1"] } },
      true,
    );
  });

  it.each(["toolsSetup", "groups.skill"])(
    "excludes blocked assets from %s selection without blocking conversations",
    (toggle) => {
      vi.mocked(useImportJob).mockReturnValue(
        state({
          job: {
            job_id: "job",
            agent_id: "agent",
            state: "awaiting_selection",
            seq: 2,
            logs: [],
            providers: [
              {
                source: "codex",
                state: "ready",
                plan_id: "plan",
                sessions_total: 1,
                sessions_processed: 0,
                sessions_imported: 0,
                selection: { sessions: true, skills: [], plugins: [] },
                assets: [
                  {
                    asset_type: "skill",
                    source_id: "good",
                    name: "Good Skill",
                    state: "pending",
                  },
                  {
                    asset_type: "skill",
                    source_id: "bad",
                    name: "Bad Skill",
                    state: "pending",
                    blocked_reason: "Skill exceeds size limit",
                  },
                  {
                    asset_type: "plugin",
                    source_id: "bad-plugin",
                    name: "Bad Plugin",
                    state: "pending",
                    blocked_reason: "Cannot read plugin",
                  },
                ],
                error: "",
              },
            ],
          },
        }) as never,
      );
      renderPage();
      expect(screen.getByText("Skill exceeds size limit")).toBeVisible();
      expect(
        screen.getByRole("checkbox", { name: "Bad Skill" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("checkbox", { name: "Bad Plugin" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("checkbox", {
          name: /portabilityImport.groups.plugin/,
        }),
      ).toBeDisabled();
      fireEvent.click(
        screen.getByRole("checkbox", {
          name: new RegExp(`portabilityImport.${toggle}`),
        }),
      );
      expect(
        screen.getByRole("checkbox", { name: "Good Skill" }),
      ).toBeChecked();
      expect(
        screen.getByRole("checkbox", { name: "Bad Skill" }),
      ).not.toBeChecked();
      fireEvent.click(
        screen.getByRole("button", { name: "portabilityImport.start" }),
      );
      expect(actions.start).toHaveBeenCalledWith({
        codex: expect.objectContaining({
          sessions: true,
          skills: ["good"],
          plugins: [],
        }),
      });
    },
  );

  it("keeps a cancelling import visible", async () => {
    vi.mocked(actions.cancel).mockResolvedValue({ state: "cancelling" });
    vi.mocked(useImportJob).mockReturnValue(
      state({
        job: {
          job_id: "job",
          agent_id: "agent",
          state: "running",
          seq: 2,
          logs: [],
          providers: [],
        },
      }) as never,
    );
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "common.cancel" }));

    await waitFor(() => expect(actions.cancel).toHaveBeenCalled());
    expect(actions.reset).not.toHaveBeenCalled();
  });
});
