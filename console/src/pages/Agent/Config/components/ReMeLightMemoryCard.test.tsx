import { Form } from "@agentscope-ai/design";
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState, type ReactNode } from "react";

import { agentsApi, api } from "@/api";
import { useAgentStore } from "@/stores/agentStore";
import { useEmbeddingVerificationStore } from "@/stores/embeddingVerificationStore";
import { renderWithProviders } from "@/test/common_setup";
import {
  isValidDreamCronShape,
  ReMeLightMemoryCard,
} from "./ReMeLightMemoryCard";
import { EmbeddingModelCard } from "./EmbeddingModelCard";
import { MemoryMaintenanceContext } from "../memoryMaintenanceContext";
import { useReMeRuntimeStatus } from "../useReMeRuntimeStatus";
import {
  getEmbeddingConfigFingerprint,
  getEmbeddingServiceFingerprint,
  isEmbeddingEnabled,
} from "./embeddingUtils";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "zh-CN", language: "zh-CN" },
  }),
}));

const memoryStatus = {
  components: {},
  components_total: "0 B",
  process_rss: "1.00 KiB",
  runtime: {
    worker: {
      status: "idle" as const,
      queue_pending: 0,
      tasks_running: 0,
    },
    auto_memory: {
      enabled: true,
      interval: 5,
    },
    tasks: [],
    recent: {
      last_error: null,
    },
    reindexing: false,
    embedding_reindex_required: false,
    embedding_reindex_undo_available: false,
  },
};

const unknownRuntime = { type: "unknown" as const };
const unknownDiagnostics = { type: "unknown" as const };
const noopStatusCheck = async () => {};

function RuntimeProvider({ children }: { children: ReactNode }) {
  const [localReindexing, setLocalReindexing] = useState(false);
  const { runtimeStatus, diagnosticsStatus, checkMemoryStatus } =
    useReMeRuntimeStatus(true);
  const remoteReindexing =
    runtimeStatus.type === "healthy" && runtimeStatus.data.reindexing;
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex: false,
        setNeedsReindex: vi.fn(),
        reindexing: localReindexing || remoteReindexing,
        setReindexing: setLocalReindexing,
        openMemorySettings: vi.fn(),
        runtimeStatus,
        diagnosticsStatus,
        checkMemoryStatus,
      }}
    >
      {children}
    </MemoryMaintenanceContext.Provider>
  );
}

function StaticMemoryProvider({ children }: { children: ReactNode }) {
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex: false,
        setNeedsReindex: vi.fn(),
        reindexing: false,
        setReindexing: vi.fn(),
        openMemorySettings: vi.fn(),
        runtimeStatus: unknownRuntime,
        diagnosticsStatus: unknownDiagnostics,
        checkMemoryStatus: noopStatusCheck,
      }}
    >
      {children}
    </MemoryMaintenanceContext.Provider>
  );
}

function MemoryForm({
  withRuntimeStatus = false,
}: {
  withRuntimeStatus?: boolean;
}) {
  const [form] = Form.useForm();
  const Provider = withRuntimeStatus ? RuntimeProvider : StaticMemoryProvider;
  return (
    <Provider>
      <Form
        form={form}
        initialValues={{
          reme_light_memory_config: {
            auto_memory_interval: 0,
            dream_cron_enabled: false,
            auto_memory_search_config: { enabled: false, max_results: 5 },
            embedding_model_config: {},
          },
        }}
      >
        <ReMeLightMemoryCard />
      </Form>
    </Provider>
  );
}

function EmbeddingForm() {
  const [form] = Form.useForm();
  return (
    <Form
      form={form}
      initialValues={{
        reme_light_memory_config: { embedding_model_config: {} },
      }}
    >
      <EmbeddingModelCard />
    </Form>
  );
}

function ConfiguredEmbeddingForm({
  modelName = "text-embedding-v4",
}: {
  modelName?: string;
}) {
  const [form] = Form.useForm();
  return (
    <Form
      form={form}
      initialValues={{
        reme_light_memory_config: {
          embedding_model_config: {
            backend: "openai",
            model_name: modelName,
            api_key: "secret",
            dimensions: 1024,
            enable_cache: true,
          },
        },
      }}
    >
      <EmbeddingModelCard />
    </Form>
  );
}

function ReindexingEmbeddingForm() {
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex: false,
        setNeedsReindex: vi.fn(),
        reindexing: true,
        setReindexing: vi.fn(),
        openMemorySettings: vi.fn(),
        runtimeStatus: unknownRuntime,
        diagnosticsStatus: unknownDiagnostics,
        checkMemoryStatus: noopStatusCheck,
      }}
    >
      <ConfiguredEmbeddingForm />
    </MemoryMaintenanceContext.Provider>
  );
}

function PersistedEmbeddingForm() {
  const config = {
    backend: "openai" as const,
    model_name: "text-embedding-v4",
    api_key: "secret",
    dimensions: 1024,
    enable_cache: true,
  };
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex: false,
        setNeedsReindex: vi.fn(),
        reindexing: false,
        setReindexing: vi.fn(),
        persistedEmbeddingFingerprint: getEmbeddingConfigFingerprint(config),
        openMemorySettings: vi.fn(),
        runtimeStatus: unknownRuntime,
        diagnosticsStatus: unknownDiagnostics,
        checkMemoryStatus: noopStatusCheck,
      }}
    >
      <ConfiguredEmbeddingForm />
    </MemoryMaintenanceContext.Provider>
  );
}

function NeedsReindexEmbeddingForm({ undoAvailable = true }) {
  const [needsReindex, setNeedsReindex] = useState(true);
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex,
        setNeedsReindex,
        reindexing: false,
        setReindexing: vi.fn(),
        openMemorySettings: vi.fn(),
        runtimeStatus: {
          type: "healthy",
          agentId: "bot",
          data: {
            ...memoryStatus.runtime,
            embedding_reindex_undo_available: undoAvailable,
          },
        },
        diagnosticsStatus: unknownDiagnostics,
        checkMemoryStatus: noopStatusCheck,
      }}
    >
      <ConfiguredEmbeddingForm />
    </MemoryMaintenanceContext.Provider>
  );
}

function MemoryAndEmbeddingForm() {
  const [form] = Form.useForm();
  const [needsReindex, setNeedsReindex] = useState(false);
  const [localReindexing, setReindexing] = useState(false);
  const { runtimeStatus, diagnosticsStatus, checkMemoryStatus } =
    useReMeRuntimeStatus(true);
  const remoteReindexing =
    runtimeStatus.type === "healthy" && runtimeStatus.data.reindexing;
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex,
        setNeedsReindex,
        reindexing: localReindexing || remoteReindexing,
        setReindexing,
        openMemorySettings: vi.fn(),
        runtimeStatus,
        diagnosticsStatus,
        checkMemoryStatus,
      }}
    >
      <Form
        form={form}
        initialValues={{
          reme_light_memory_config: {
            auto_memory_interval: 0,
            embedding_model_config: {
              backend: "openai",
              model_name: "text-embedding-v4",
              api_key: "secret",
              dimensions: 1024,
            },
          },
        }}
      >
        <ReMeLightMemoryCard />
        <EmbeddingModelCard />
      </Form>
    </MemoryMaintenanceContext.Provider>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  useAgentStore.setState({ selectedAgent: "default" });
  useEmbeddingVerificationStore.setState({ verificationByAgent: {} });
});

describe("ReMe runtime status", () => {
  it("groups the ReMe attribution and documentation with service status", () => {
    renderWithProviders(<MemoryForm />);

    const serviceStatus = screen
      .getByText("agentConfig.memoryRuntimeStatus")
      .closest("div");
    const statusLabel = screen.getByText("agentConfig.memoryStatusUnknown");
    const poweredBy = screen.getByText("agentConfig.memoryPoweredBy");

    expect(serviceStatus).not.toBeNull();
    expect(statusLabel.parentElement).toContainElement(poweredBy);
    expect(
      within(serviceStatus as HTMLElement).getByText(
        "agentConfig.memoryPoweredBy",
      ),
    ).toBeInTheDocument();
    expect(
      within(serviceStatus as HTMLElement).getByRole("link", { name: "ReMe" }),
    ).toHaveAttribute("href", "https://github.com/agentscope-ai/ReMe");
    expect(
      within(serviceStatus as HTMLElement).getByRole("link", {
        name: "agentConfig.memoryDocumentation",
      }),
    ).toHaveAttribute("href", "https://qwenpaw.agentscope.io/docs/memory");
  });

  it("loads the selected agent's complete status on entry", async () => {
    const getMemoryRuntimeStatus = vi
      .spyOn(agentsApi, "getMemoryRuntimeStatus")
      .mockResolvedValue(memoryStatus.runtime);
    const getMemoryStatus = vi
      .spyOn(agentsApi, "getMemoryStatus")
      .mockResolvedValue(memoryStatus);
    useAgentStore.setState({ selectedAgent: "bot" });

    renderWithProviders(<MemoryForm withRuntimeStatus />);

    expect(
      screen.getByText("agentConfig.memoryStatusChecking"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("agentConfig.memoryStatusRunning"),
    ).toBeInTheDocument();
    expect(getMemoryRuntimeStatus).toHaveBeenCalledWith(
      "bot",
      expect.any(AbortSignal),
    );
    expect(getMemoryStatus).toHaveBeenCalledTimes(1);
    expect(getMemoryStatus).toHaveBeenCalledWith(
      "bot",
      expect.any(AbortSignal),
    );
    const diagnosticsButton = screen.getByRole("button", {
      name: /agentConfig\.memoryDiagnostics/,
    });
    expect(diagnosticsButton).toHaveTextContent("0 B");
    expect(diagnosticsButton).toHaveTextContent("1.00 KiB");
  });

  it("shows the checking state while manually refreshing", async () => {
    const pendingStatus = new Promise<typeof memoryStatus.runtime>(
      () => undefined,
    );
    const getMemoryRuntimeStatus = vi
      .spyOn(agentsApi, "getMemoryRuntimeStatus")
      .mockResolvedValueOnce(memoryStatus.runtime)
      .mockImplementationOnce(() => pendingStatus);
    vi.spyOn(agentsApi, "getMemoryStatus").mockResolvedValue(memoryStatus);

    renderWithProviders(<MemoryForm withRuntimeStatus />);
    await screen.findByText("agentConfig.memoryStatusRunning");

    fireEvent.click(
      screen.getByRole("button", {
        name: /agentConfig\.memoryBackgroundTasks/,
      }),
    );

    expect(
      await screen.findByText("agentConfig.memoryStatusChecking"),
    ).toBeInTheDocument();
    expect(getMemoryRuntimeStatus).toHaveBeenCalledTimes(2);
  });

  it("shows a failed check instead of a healthy badge", async () => {
    vi.spyOn(agentsApi, "getMemoryRuntimeStatus").mockRejectedValue(
      new Error("Agent is not running"),
    );

    renderWithProviders(<MemoryForm withRuntimeStatus />);

    expect(
      await screen.findByText("agentConfig.memoryStatusCheckFailed"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("agentConfig.memoryStatusRunning"),
    ).not.toBeInTheDocument();
  });

  it("keeps runtime healthy when diagnostics fail", async () => {
    vi.spyOn(agentsApi, "getMemoryRuntimeStatus").mockResolvedValue(
      memoryStatus.runtime,
    );
    vi.spyOn(agentsApi, "getMemoryStatus").mockRejectedValue(
      new Error("Diagnostics unavailable"),
    );

    renderWithProviders(<MemoryForm withRuntimeStatus />);

    expect(
      await screen.findByText("agentConfig.memoryStatusRunning"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: /agentConfig\.memoryDiagnostics/,
      }),
    );
    expect(
      await screen.findByText("agentConfig.remeStatusFailed"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.memoryStatusRunning"),
    ).toBeInTheDocument();
  });

  it("cancels the stale check when the selected agent changes", async () => {
    const pendingStatus = new Promise<typeof memoryStatus.runtime>(
      () => undefined,
    );
    const getMemoryRuntimeStatus = vi
      .spyOn(agentsApi, "getMemoryRuntimeStatus")
      .mockImplementation((agentId) =>
        agentId === "default"
          ? pendingStatus
          : Promise.resolve(memoryStatus.runtime),
      );
    vi.spyOn(agentsApi, "getMemoryStatus").mockResolvedValue(memoryStatus);
    renderWithProviders(<MemoryForm withRuntimeStatus />);
    await waitFor(() =>
      expect(getMemoryRuntimeStatus).toHaveBeenCalledTimes(1),
    );
    const firstSignal = getMemoryRuntimeStatus.mock.calls[0][1];

    act(() => useAgentStore.setState({ selectedAgent: "bot" }));

    await waitFor(() => {
      expect(getMemoryRuntimeStatus).toHaveBeenLastCalledWith(
        "bot",
        expect.any(AbortSignal),
      );
    });
    expect(firstSignal?.aborted).toBe(true);
    expect(
      await screen.findByText("agentConfig.memoryStatusRunning"),
    ).toBeInTheDocument();
  });

  it("uses runtime reindex state while full diagnostics are blocked", async () => {
    vi.useFakeTimers();
    try {
      const rebuildingRuntime = {
        ...memoryStatus.runtime,
        reindexing: true,
      };
      const getMemoryRuntimeStatus = vi
        .spyOn(agentsApi, "getMemoryRuntimeStatus")
        .mockResolvedValue(rebuildingRuntime);
      vi.spyOn(agentsApi, "getMemoryStatus").mockImplementation(
        () => new Promise(() => undefined),
      );
      const { container } = renderWithProviders(<MemoryAndEmbeddingForm />);

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      const modelInput = container.querySelector(
        'input[placeholder="agentConfig.embeddingModelNamePlaceholder"]',
      );
      expect(modelInput).toBeDisabled();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });

      expect(getMemoryRuntimeStatus).toHaveBeenCalledTimes(1);
      expect(modelInput).toBeDisabled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows worker and auto-memory history status", async () => {
    const busyStatus = {
      ...memoryStatus,
      runtime: {
        ...memoryStatus.runtime,
        worker: {
          ...memoryStatus.runtime.worker,
          status: "busy" as const,
          queue_pending: 2,
          tasks_running: 1,
        },
      },
    };
    vi.spyOn(agentsApi, "getMemoryRuntimeStatus").mockResolvedValue(
      busyStatus.runtime,
    );
    vi.spyOn(agentsApi, "getMemoryStatus").mockResolvedValue(busyStatus);

    renderWithProviders(<MemoryForm withRuntimeStatus />);

    expect(
      await screen.findByText("agentConfig.memoryStatusBusy"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.memoryWorkerStatus.busy"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /agentConfig\.memoryBackgroundTasks/,
      }),
    ).toBeInTheDocument();
  });

  it("opens task history and diagnostics from separate overview actions", async () => {
    vi.spyOn(agentsApi, "getMemoryRuntimeStatus").mockResolvedValue(
      memoryStatus.runtime,
    );
    vi.spyOn(agentsApi, "getMemoryStatus").mockResolvedValue(memoryStatus);

    renderWithProviders(<MemoryForm withRuntimeStatus />);
    const diagnosticsButton = await screen.findByRole("button", {
      name: /agentConfig\.memoryDiagnostics/,
    });
    fireEvent.click(
      await screen.findByRole("button", {
        name: /agentConfig\.memoryBackgroundTasks/,
      }),
    );

    expect(
      await screen.findByText("agentConfig.memoryQueueIdleSummary"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.memoryAutoMemoryEnabledSummary"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.memoryRecentTasksEmpty"),
    ).toBeInTheDocument();

    fireEvent.click(diagnosticsButton);

    await waitFor(() => {
      expect(diagnosticsButton).toHaveTextContent("0 B");
      expect(diagnosticsButton).toHaveTextContent("1.00 KiB");
    });

    expect(
      await screen.findByText("agentConfig.remeStatusComponentsTotal"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.remeStatusProcessRss"),
    ).toBeInTheDocument();
  });
});

describe("long-term memory defaults", () => {
  it("renders defaults, sections, and collapsed Daily Paper settings", () => {
    renderWithProviders(<MemoryForm />);

    const switchInRow = (element: HTMLElement) =>
      element.parentElement?.parentElement?.querySelector(
        '[role="switch"]',
      ) as HTMLElement;

    expect(
      screen.getByText("agentConfig.memoryOrganizeSectionTitle"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.memorySearchSectionTitle"),
    ).toBeInTheDocument();

    const sourceToggle = screen.getByRole("button", {
      name: /agentConfig\.memoryDailyPaperTitle/,
    });
    expect(sourceToggle).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByText("agentConfig.dailyPaperTopics"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "agentConfig.dailyPaperDocumentation",
      }),
    ).toHaveAttribute("href", "https://qwenpaw.agentscope.io/docs/memory");

    fireEvent.click(sourceToggle);

    expect(sourceToggle).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText("agentConfig.dailyPaperTopics"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.dailyPaperUseHfMirror"),
    ).toBeInTheDocument();
    const notificationSwitches = screen
      .getAllByText("agentConfig.memoryNotifyTitle")
      .map(switchInRow);

    expect(notificationSwitches).toHaveLength(3);
    notificationSwitches.forEach((control) =>
      expect(control).toHaveAttribute("aria-checked", "true"),
    );
    expect(
      switchInRow(screen.getByText("agentConfig.memorySearchToolTitle")),
    ).toHaveAttribute("aria-checked", "true");
    expect(
      switchInRow(screen.getByText("agentConfig.memoryAutoRecallTitle")),
    ).toHaveAttribute("aria-checked", "false");
  });
});

describe("embedding card separation", () => {
  it("keeps embedding settings out of the long-term memory card", async () => {
    renderWithProviders(<MemoryForm />);

    expect(
      screen.queryByText("agentConfig.embeddingServiceTitle"),
    ).not.toBeInTheDocument();
  });

  it("renders embedding settings in the dedicated card", () => {
    renderWithProviders(<EmbeddingForm />);

    expect(
      screen.getByText("agentConfig.embeddingServiceTitle"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.embeddingIndexTitle"),
    ).toBeInTheDocument();
  });

  it("shows test results in the status overview", async () => {
    vi.spyOn(api, "testEmbedding").mockResolvedValue({
      success: true,
      configured_dimensions: 1024,
      actual_dimensions: 1024,
      latency_ms: 86,
      message: "ok",
    });

    renderWithProviders(<ConfiguredEmbeddingForm />);

    expect(
      screen.getByText("agentConfig.embeddingNotVerified"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "agentConfig.embeddingTestConnection",
      }),
    );

    expect(
      await screen.findByText("agentConfig.embeddingVerified"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.embeddingVerificationMetrics"),
    ).toBeInTheDocument();
  });

  it("keeps a successful verification after the embedding card remounts", async () => {
    vi.spyOn(api, "testEmbedding").mockResolvedValue({
      success: true,
      configured_dimensions: 1024,
      actual_dimensions: 1024,
      latency_ms: 86,
      message: "ok",
    });

    const view = renderWithProviders(<ConfiguredEmbeddingForm />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "agentConfig.embeddingTestConnection",
      }),
    );
    expect(
      await screen.findByText("agentConfig.embeddingVerified"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "agentConfig.embeddingTestConnection",
        }),
      ).toHaveAttribute("aria-busy", "false"),
    );

    view.unmount();
    renderWithProviders(<ConfiguredEmbeddingForm />);

    expect(
      screen.getByText("agentConfig.embeddingVerified"),
    ).toBeInTheDocument();
    expect(api.testEmbedding).toHaveBeenCalledOnce();
  });

  it("does not reuse verification for different service settings", async () => {
    vi.spyOn(api, "testEmbedding").mockResolvedValue({
      success: true,
      configured_dimensions: 1024,
      actual_dimensions: 1024,
      latency_ms: 86,
      message: "ok",
    });

    const view = renderWithProviders(<ConfiguredEmbeddingForm />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "agentConfig.embeddingTestConnection",
      }),
    );
    expect(
      await screen.findByText("agentConfig.embeddingVerified"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "agentConfig.embeddingTestConnection",
        }),
      ).toHaveAttribute("aria-busy", "false"),
    );

    view.unmount();
    renderWithProviders(
      <ConfiguredEmbeddingForm modelName="text-embedding-v5" />,
    );

    expect(
      screen.getByText("agentConfig.embeddingNotVerified"),
    ).toBeInTheDocument();
  });

  it("isolates verification by selected agent", async () => {
    vi.spyOn(api, "testEmbedding").mockResolvedValue({
      success: true,
      configured_dimensions: 1024,
      actual_dimensions: 1024,
      latency_ms: 86,
      message: "ok",
    });
    renderWithProviders(<ConfiguredEmbeddingForm />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "agentConfig.embeddingTestConnection",
      }),
    );
    expect(
      await screen.findByText("agentConfig.embeddingVerified"),
    ).toBeInTheDocument();

    act(() => useAgentStore.setState({ selectedAgent: "another-agent" }));

    expect(
      await screen.findByText("agentConfig.embeddingNotVerified"),
    ).toBeInTheDocument();

    act(() => useAgentStore.setState({ selectedAgent: "default" }));

    expect(
      await screen.findByText("agentConfig.embeddingVerified"),
    ).toBeInTheDocument();
  });

  it("shows explicit embedding rebuild and undo actions when required", async () => {
    renderWithProviders(<NeedsReindexEmbeddingForm />);

    expect(
      await screen.findByRole("button", {
        name: "agentConfig.rebuildEmbeddingIndex",
      }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", {
        name: "agentConfig.undoEmbeddingChange",
      }),
    ).toBeEnabled();
    expect(
      screen.getByText("agentConfig.embeddingSearchModeBm25Pending"),
    ).toBeInTheDocument();
  });

  it("hides undo when a legacy pending state has no indexed snapshot", async () => {
    renderWithProviders(<NeedsReindexEmbeddingForm undoAvailable={false} />);

    expect(
      await screen.findByText("agentConfig.embeddingIndexNeedsRebuild"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "agentConfig.undoEmbeddingChange",
      }),
    ).not.toBeInTheDocument();
  });

  it("always shows embedding index status and the manual rebuild action", async () => {
    renderWithProviders(<ConfiguredEmbeddingForm />);

    expect(
      await screen.findByText("agentConfig.embeddingIndexAvailable"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.embeddingIndexMatchesConfig"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "agentConfig.rebuildEmbeddingIndex",
      }),
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", {
        name: "agentConfig.undoEmbeddingChange",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.embeddingSearchModeHybrid"),
    ).toBeInTheDocument();
  });

  it("disables embedding reindex while embedding is not enabled", async () => {
    renderWithProviders(<EmbeddingForm />);

    expect(
      await screen.findByText("agentConfig.embeddingIndexDisabled"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "agentConfig.rebuildEmbeddingIndex",
      }),
    ).toBeDisabled();
    expect(
      screen.getByText("agentConfig.embeddingSearchModeBm25"),
    ).toBeInTheDocument();
  });

  it("disables every embedding config field while rebuilding", () => {
    const { container } = renderWithProviders(<ReindexingEmbeddingForm />);

    const configFields = container.querySelectorAll(
      '[role="combobox"], [role="textbox"], [role="spinbutton"], [role="switch"]',
    );

    expect(configFields.length).toBeGreaterThan(1);
    configFields.forEach((control) => expect(control).toBeDisabled());
    expect(
      screen.getByRole("button", {
        name: "agentConfig.embeddingTestConnection",
      }),
    ).toBeEnabled();
    expect(
      screen.getByText("agentConfig.embeddingIndexRebuilding"),
    ).toBeInTheDocument();
  });

  it("requires unsaved embedding changes to be saved before rebuilding", async () => {
    renderWithProviders(<PersistedEmbeddingForm />);

    fireEvent.change(
      await screen.findByLabelText("agentConfig.embeddingModelName"),
      { target: { value: "unsaved-model" } },
    );

    expect(
      screen.getByText("agentConfig.embeddingIndexSaveFirst"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "agentConfig.rebuildEmbeddingIndex",
      }),
    ).toBeDisabled();
  });
});

describe("isValidDreamCronShape", () => {
  it("accepts a five-field cron expression", () => {
    expect(isValidDreamCronShape("0 23 * * *")).toBe(true);
    expect(isValidDreamCronShape("  0 3 * * mon-fri  ")).toBe(true);
  });

  it("rejects empty and malformed expressions", () => {
    expect(isValidDreamCronShape("")).toBe(false);
    expect(isValidDreamCronShape("0 23 * *")).toBe(false);
    expect(isValidDreamCronShape("0 23 * * ?")).toBe(false);
    expect(isValidDreamCronShape("61 * * * *")).toBe(false);
    expect(isValidDreamCronShape("0 24 * * *")).toBe(false);
    expect(isValidDreamCronShape("0 9 0 * *")).toBe(false);
  });
});

describe("isEmbeddingEnabled", () => {
  it("requires model name for every backend", () => {
    expect(
      isEmbeddingEnabled({ backend: "openai", model_name: "", api_key: "key" }),
    ).toBe(false);
    expect(isEmbeddingEnabled({ backend: "ollama", model_name: "   " })).toBe(
      false,
    );
  });

  it("requires api key for OpenAI-compatible backends", () => {
    expect(
      isEmbeddingEnabled({
        backend: "openai",
        model_name: "text-embedding-3-small",
        api_key: "",
      }),
    ).toBe(false);
    expect(
      isEmbeddingEnabled({
        backend: "dashscope",
        model_name: "text-embedding-v3",
        api_key: "key",
      }),
    ).toBe(true);
    expect(
      isEmbeddingEnabled({
        backend: "dashscope_multimodal",
        model_name: "multimodal-embedding",
        api_key: "key",
      }),
    ).toBe(true);
  });

  it("requires api key for gemini", () => {
    expect(
      isEmbeddingEnabled({
        backend: "gemini",
        model_name: "gemini-embedding-001",
        api_key: "",
      }),
    ).toBe(false);
    expect(
      isEmbeddingEnabled({
        backend: "gemini",
        model_name: "gemini-embedding-001",
        api_key: "key",
      }),
    ).toBe(true);
  });

  it("enables ollama with a model name and no api key", () => {
    expect(
      isEmbeddingEnabled({
        backend: "ollama",
        model_name: "nomic-embed-text",
      }),
    ).toBe(true);
  });
});

describe("getEmbeddingServiceFingerprint", () => {
  const base = {
    backend: "openai" as const,
    api_key: "key",
    base_url: "https://example.com/v1/",
    model_name: "embedding-model",
    dimensions: 1024,
    use_dimensions: false,
  };

  it("normalizes the service URL", () => {
    expect(getEmbeddingServiceFingerprint(base)).toBe(
      getEmbeddingServiceFingerprint({
        ...base,
        base_url: " https://example.com/v1 ",
      }),
    );
  });

  it("ignores ReMe cache and batching settings", () => {
    expect(
      getEmbeddingServiceFingerprint({
        ...base,
        enable_cache: true,
        max_cache_size: 10,
        max_input_length: 100,
        max_batch_size: 2,
      }),
    ).toBe(
      getEmbeddingServiceFingerprint({
        ...base,
        enable_cache: false,
        max_cache_size: 20,
        max_input_length: 200,
        max_batch_size: 4,
      }),
    );
  });
});
