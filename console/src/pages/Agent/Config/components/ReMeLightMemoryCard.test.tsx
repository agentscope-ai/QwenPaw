import { Form } from "@agentscope-ai/design";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState, type ReactNode } from "react";

import { agentsApi, api } from "@/api";
import { useAgentStore } from "@/stores/agentStore";
import { renderWithProviders } from "@/test/common_setup";
import {
  isValidDreamCronShape,
  ReMeLightMemoryCard,
} from "./ReMeLightMemoryCard";
import { EmbeddingModelCard } from "./EmbeddingModelCard";
import { MemoryMaintenanceContext } from "../memoryMaintenanceContext";
import { useReMeRuntimeStatus } from "../useReMeRuntimeStatus";
import {
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
      active_sessions: 1,
      sessions_with_pending: 1,
      pending_turns: 3,
    },
    recent: {
      last_completed_at: "2026-08-10T10:18:00",
      last_failed_at: null,
      last_error: null,
    },
    reindexing: false,
  },
};

const unknownRuntime = { type: "unknown" as const };
const noopStatusCheck = async () => {};

function RuntimeProvider({ children }: { children: ReactNode }) {
  const [localReindexing, setLocalReindexing] = useState(false);
  const { runtimeStatus, checkMemoryStatus } = useReMeRuntimeStatus(true);
  const remoteReindexing =
    runtimeStatus.type === "healthy" && runtimeStatus.data.runtime.reindexing;
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex: false,
        setNeedsReindex: vi.fn(),
        reindexing: localReindexing || remoteReindexing,
        setReindexing: setLocalReindexing,
        openMemorySettings: vi.fn(),
        runtimeStatus,
        checkMemoryStatus,
        configRevision: 0,
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
        checkMemoryStatus: noopStatusCheck,
        configRevision: 0,
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

function ConfiguredEmbeddingForm() {
  const [form] = Form.useForm();
  return (
    <Form
      form={form}
      initialValues={{
        reme_light_memory_config: {
          embedding_model_config: {
            backend: "openai",
            model_name: "text-embedding-v4",
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
        checkMemoryStatus: noopStatusCheck,
        configRevision: 0,
      }}
    >
      <ConfiguredEmbeddingForm />
    </MemoryMaintenanceContext.Provider>
  );
}

function NeedsReindexEmbeddingForm({ onOpen = vi.fn() }) {
  const [needsReindex, setNeedsReindex] = useState(true);
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex,
        setNeedsReindex,
        reindexing: false,
        setReindexing: vi.fn(),
        openMemorySettings: onOpen,
        runtimeStatus: unknownRuntime,
        checkMemoryStatus: noopStatusCheck,
        configRevision: 0,
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
  const { runtimeStatus, checkMemoryStatus } = useReMeRuntimeStatus(true);
  const remoteReindexing =
    runtimeStatus.type === "healthy" && runtimeStatus.data.runtime.reindexing;
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex,
        setNeedsReindex,
        reindexing: localReindexing || remoteReindexing,
        setReindexing,
        openMemorySettings: vi.fn(),
        runtimeStatus,
        checkMemoryStatus,
        configRevision: 0,
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
});

describe("ReMe runtime status", () => {
  it("checks the selected agent automatically and only then shows healthy", async () => {
    const getMemoryRuntimeStatus = vi
      .spyOn(agentsApi, "getMemoryRuntimeStatus")
      .mockResolvedValue(memoryStatus.runtime);
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

  it("cancels the stale check when the selected agent changes", async () => {
    const pendingStatus = new Promise<typeof memoryStatus>(() => undefined);
    const getMemoryRuntimeStatus = vi
      .spyOn(agentsApi, "getMemoryRuntimeStatus")
      .mockImplementation((agentId) =>
        agentId === "default"
          ? pendingStatus.then((status) => status.runtime)
          : Promise.resolve(memoryStatus.runtime),
      );
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

  it("polls remote reindex state and keeps embedding fields in sync", async () => {
    vi.useFakeTimers();
    try {
      const rebuildingStatus = {
        ...memoryStatus,
        runtime: { ...memoryStatus.runtime, reindexing: true },
      };
      const getMemoryRuntimeStatus = vi
        .spyOn(agentsApi, "getMemoryRuntimeStatus")
        .mockResolvedValueOnce(rebuildingStatus.runtime)
        .mockResolvedValue(memoryStatus.runtime);
      const { container } = renderWithProviders(<MemoryAndEmbeddingForm />);

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(getMemoryRuntimeStatus).toHaveBeenCalledTimes(1);
      const modelInput = container.querySelector(
        'input[placeholder="agentConfig.embeddingModelNamePlaceholder"]',
      );
      expect(modelInput).toBeDisabled();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });

      expect(getMemoryRuntimeStatus).toHaveBeenCalledTimes(2);
      expect(modelInput).toBeEnabled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("waits for the current runtime poll before scheduling the next one", async () => {
    vi.useFakeTimers();
    try {
      let resolveFirstPoll: (value: typeof memoryStatus.runtime) => void = () =>
        undefined;
      const firstPoll = new Promise<typeof memoryStatus.runtime>((resolve) => {
        resolveFirstPoll = resolve;
      });
      const getMemoryRuntimeStatus = vi
        .spyOn(agentsApi, "getMemoryRuntimeStatus")
        .mockReturnValueOnce(firstPoll)
        .mockResolvedValue(memoryStatus.runtime);

      renderWithProviders(<MemoryForm withRuntimeStatus />);
      await act(async () => Promise.resolve());
      expect(getMemoryRuntimeStatus).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(getMemoryRuntimeStatus).toHaveBeenCalledTimes(1);

      await act(async () => {
        resolveFirstPoll(memoryStatus.runtime);
        await firstPoll;
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(getMemoryRuntimeStatus).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows aggregated worker and pending-turn status", async () => {
    vi.spyOn(agentsApi, "getMemoryRuntimeStatus").mockResolvedValue({
      ...memoryStatus.runtime,
      worker: {
        ...memoryStatus.runtime.worker,
        status: "busy",
        queue_pending: 2,
        tasks_running: 1,
      },
    });

    renderWithProviders(<MemoryForm withRuntimeStatus />);

    expect(
      await screen.findByText("agentConfig.memoryStatusBusy"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.memoryWorkerStatus.busy"),
    ).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
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
    ).toHaveAttribute(
      "href",
      "https://github.com/agentscope-ai/ReMe/blob/main/cookbook/daily_paper/README_ZH.md",
    );

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

  it("clears verification when the selected agent changes", async () => {
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
  });

  it("links to long-term memory when a rebuild is required", async () => {
    const onOpen = vi.fn();
    renderWithProviders(<NeedsReindexEmbeddingForm onOpen={onOpen} />);

    const button = await screen.findByRole("button", {
      name: "agentConfig.goToLongTermMemory",
    });
    fireEvent.click(button);
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("disables every embedding config field while rebuilding", () => {
    const { container } = renderWithProviders(<ReindexingEmbeddingForm />);

    const configFields = container.querySelectorAll(
      '[role="combobox"], [role="textbox"], [role="spinbutton"], [role="switch"]',
    );

    expect(configFields.length).toBeGreaterThan(1);
    configFields.forEach((control) => expect(control).toBeDisabled());
    expect(
      screen.getByText("agentConfig.embeddingTestConnection").closest("button"),
    ).toBeEnabled();
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
