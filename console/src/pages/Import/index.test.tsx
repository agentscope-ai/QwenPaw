import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
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
    ...actions,
    ...overrides,
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
    vi.mocked(actions.detect).mockResolvedValue([]);
  });

  it("detects applications and supports multi-source selection", () => {
    vi.mocked(useImportJob).mockReturnValue(state() as never);
    renderPage();

    expect(actions.detect).toHaveBeenCalled();
    expect(screen.getByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Qoder")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "portabilityImport.continue" }),
    );
    expect(actions.scan).toHaveBeenCalledWith(["codex", "qoder"]);
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
