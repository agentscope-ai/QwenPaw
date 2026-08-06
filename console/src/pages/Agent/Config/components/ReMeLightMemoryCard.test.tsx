import { Form } from "@agentscope-ai/design";
import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { agentsApi } from "@/api";
import { useAgentStore } from "@/stores/agentStore";
import { renderWithProviders } from "@/test/common_setup";
import {
  getDailyCronTime,
  getEmbeddingServiceFingerprint,
  isEmbeddingEnabled,
  isValidDreamCronShape,
  ReMeLightMemoryCard,
} from "./ReMeLightMemoryCard";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const memoryStatus = {
  components: {},
  components_total_bytes: 0,
  components_total: "0 B",
  process_rss_bytes: 1024,
  process_rss: "1.00 KiB",
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
});

describe("getDailyCronTime", () => {
  it("formats a daily cron expression for the status summary", () => {
    expect(getDailyCronTime("0 23 * * *")).toBe("23:00");
    expect(getDailyCronTime("5 3 * * *")).toBe("03:05");
  });

  it("rejects non-daily and out-of-range schedules", () => {
    expect(getDailyCronTime("0 23 * * mon-fri")).toBeNull();
    expect(getDailyCronTime("60 23 * * *")).toBeNull();
    expect(getDailyCronTime("0 24 * * *")).toBeNull();
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
