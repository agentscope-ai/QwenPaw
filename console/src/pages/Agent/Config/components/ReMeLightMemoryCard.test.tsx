import { Form } from "@agentscope-ai/design";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import { agentsApi, api } from "@/api";
import { useAgentStore } from "@/stores/agentStore";
import { renderWithProviders } from "@/test/common_setup";
import {
  isValidDreamCronShape,
  ReMeLightMemoryCard,
} from "./ReMeLightMemoryCard";
import { EmbeddingModelCard } from "./EmbeddingModelCard";
import { MemoryMaintenanceContext } from "../memoryMaintenanceContext";
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
  components_total_bytes: 0,
  components_total: "0 B",
  process_rss_bytes: 1024,
  process_rss: "1.00 KiB",
  runtime: {
    worker: {
      status: "idle" as const,
      queue_pending: 0,
      tasks_pending: 0,
      tasks_running: 0,
      current_task_started_at: null,
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

function MemoryForm() {
  const [form] = Form.useForm();
  return (
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

function NeedsReindexEmbeddingForm({ onOpen = vi.fn() }) {
  const [needsReindex, setNeedsReindex] = useState(true);
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex,
        setNeedsReindex,
        openMemorySettings: onOpen,
      }}
    >
      <ConfiguredEmbeddingForm />
    </MemoryMaintenanceContext.Provider>
  );
}

function MemoryAndEmbeddingForm() {
  const [form] = Form.useForm();
  const [needsReindex, setNeedsReindex] = useState(false);
  return (
    <MemoryMaintenanceContext.Provider
      value={{
        needsReindex,
        setNeedsReindex,
        openMemorySettings: vi.fn(),
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
    const getMemoryStatus = vi
      .spyOn(agentsApi, "getMemoryStatus")
      .mockResolvedValue(memoryStatus);
    useAgentStore.setState({ selectedAgent: "bot" });

    renderWithProviders(<MemoryForm />);

    expect(
      screen.getByText("agentConfig.memoryStatusChecking"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("agentConfig.memoryStatusRunning"),
    ).toBeInTheDocument();
    expect(getMemoryStatus).toHaveBeenCalledWith(
      "bot",
      expect.any(AbortSignal),
    );
  });

  it("shows a failed check instead of a healthy badge", async () => {
    vi.spyOn(agentsApi, "getMemoryStatus").mockRejectedValue(
      new Error("Agent is not running"),
    );

    renderWithProviders(<MemoryForm />);

    expect(
      await screen.findByText("agentConfig.memoryStatusCheckFailed"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("agentConfig.memoryStatusRunning"),
    ).not.toBeInTheDocument();
  });

  it("cancels the stale check when the selected agent changes", async () => {
    const pendingStatus = new Promise<typeof memoryStatus>(() => undefined);
    const getMemoryStatus = vi
      .spyOn(agentsApi, "getMemoryStatus")
      .mockImplementation((agentId) =>
        agentId === "default" ? pendingStatus : Promise.resolve(memoryStatus),
      );
    renderWithProviders(<MemoryForm />);
    await waitFor(() => expect(getMemoryStatus).toHaveBeenCalledTimes(1));
    const firstSignal = getMemoryStatus.mock.calls[0][1];

    act(() => useAgentStore.setState({ selectedAgent: "bot" }));

    await waitFor(() => {
      expect(getMemoryStatus).toHaveBeenLastCalledWith(
        "bot",
        expect.any(AbortSignal),
      );
    });
    expect(firstSignal?.aborted).toBe(true);
    expect(
      await screen.findByText("agentConfig.memoryStatusRunning"),
    ).toBeInTheDocument();
  });

  it("does not poll for maintenance state after the initial check", async () => {
    vi.useFakeTimers();
    try {
      const getMemoryStatus = vi
        .spyOn(agentsApi, "getMemoryStatus")
        .mockResolvedValue(memoryStatus);
      renderWithProviders(<MemoryAndEmbeddingForm />);

      await act(async () => {
        await Promise.resolve();
      });
      const initialRequestCount = getMemoryStatus.mock.calls.length;
      expect(initialRequestCount).toBeGreaterThan(0);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });

      expect(getMemoryStatus).toHaveBeenCalledTimes(initialRequestCount);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows aggregated worker and pending-turn status", async () => {
    vi.spyOn(agentsApi, "getMemoryStatus").mockResolvedValue({
      ...memoryStatus,
      runtime: {
        ...memoryStatus.runtime,
        worker: {
          ...memoryStatus.runtime.worker,
          status: "busy",
          queue_pending: 2,
          tasks_pending: 2,
          tasks_running: 1,
        },
      },
    });

    renderWithProviders(<MemoryForm />);

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
  it("enables notifications and the search tool but leaves auto recall off", async () => {
    vi.spyOn(agentsApi, "getMemoryStatus").mockResolvedValue(memoryStatus);

    renderWithProviders(<MemoryForm />);

    const switchInRow = (element: HTMLElement) =>
      element.parentElement?.parentElement?.querySelector(
        '[role="switch"]',
      ) as HTMLElement;
    fireEvent.click(
      screen.getByRole("button", {
        name: /agentConfig\.memoryDailyPaperTitle/,
      }),
    );
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

  it("links Daily Paper to the guide matching the interface language", async () => {
    vi.spyOn(agentsApi, "getMemoryStatus").mockResolvedValue(memoryStatus);

    renderWithProviders(<MemoryForm />);

    expect(
      screen.getByRole("link", {
        name: "agentConfig.dailyPaperDocumentation",
      }),
    ).toHaveAttribute(
      "href",
      "https://github.com/agentscope-ai/ReMe/blob/main/cookbook/daily_paper/README_ZH.md",
    );
  });

  it("shows Daily Paper topic and Hugging Face mirror settings", async () => {
    vi.spyOn(agentsApi, "getMemoryStatus").mockResolvedValue(memoryStatus);

    renderWithProviders(<MemoryForm />);

    fireEvent.click(
      screen.getByRole("button", {
        name: /agentConfig\.memoryDailyPaperTitle/,
      }),
    );
    expect(
      screen.getByText("agentConfig.dailyPaperTopics"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agentConfig.dailyPaperUseHfMirror"),
    ).toBeInTheDocument();
  });

  it("separates organization and search and collapses Daily Paper settings", async () => {
    vi.spyOn(agentsApi, "getMemoryStatus").mockResolvedValue(memoryStatus);

    renderWithProviders(<MemoryForm />);

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

    fireEvent.click(sourceToggle);

    expect(sourceToggle).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText("agentConfig.dailyPaperTopics"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "agentConfig.dailyPaperDocumentation",
      }),
    ).toBeInTheDocument();
  });
});

describe("embedding card separation", () => {
  it("keeps embedding settings out of the long-term memory card", async () => {
    vi.spyOn(agentsApi, "getMemoryStatus").mockResolvedValue(memoryStatus);

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

  it("links to long-term memory when a rebuild is required", async () => {
    const onOpen = vi.fn();
    renderWithProviders(<NeedsReindexEmbeddingForm onOpen={onOpen} />);

    const button = await screen.findByRole("button", {
      name: "agentConfig.goToLongTermMemory",
    });
    fireEvent.click(button);
    expect(onOpen).toHaveBeenCalledOnce();
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

  it("disables unknown backends", () => {
    expect(
      isEmbeddingEnabled({
        backend: "unknown",
        model_name: "embedding-model",
        api_key: "key",
      }),
    ).toBe(false);
  });
});

describe("getEmbeddingServiceFingerprint", () => {
  const base = {
    backend: "openai",
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
