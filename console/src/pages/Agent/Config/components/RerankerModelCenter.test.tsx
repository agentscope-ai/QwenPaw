/**
 * RerankerModelCenter — the rendered service-verification status must never
 * claim "Verified" unless a real probe completed for the current service.
 */
import { Form } from "@agentscope-ai/design";
import { act, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";

import { api } from "@/api";
import { useAgentStore } from "@/stores/agentStore";
import { useRerankerVerificationStore } from "@/stores/rerankerVerificationStore";
import { renderWithProviders } from "@/test/common_setup";
import { getRerankerServiceFingerprint } from "./rerankerUtils";
import { RerankerModelCenter } from "./RerankerModelCenter";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "zh-CN", language: "zh-CN" },
  }),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    modal: { success: vi.fn(), error: vi.fn() },
  }),
}));

// Generated per run so no credential-like literal lives in the repository.
const TEST_API_KEY = `probe-${crypto.randomUUID().replace(/-/g, "")}`;

const enabledConfig = {
  enabled: true,
  api_key: TEST_API_KEY,
  base_url: "https://api.example.com/v1",
  model_name: "probe-reranker",
  candidate_multiplier: 3,
  timeout: 10,
  auto_verify_interval_hours: 0,
};

const historyRecord = {
  ts: 1_700_000_000_000,
  latency_ms: 120,
  precision: 0.8,
  correct_count: 4,
  total: 5,
};

function Harness({ config = enabledConfig }: { config?: typeof enabledConfig }) {
  const [form] = Form.useForm();
  useEffect(() => {
    form.setFieldsValue({
      reme_light_memory_config: { reranker_config: config },
    });
  }, [form, config]);
  return (
    <Form
      form={form}
      initialValues={{ reme_light_memory_config: { reranker_config: config } }}
    >
      {/* Register the watched path so antd's Form.useWatch observes it. */}
      <Form.Item
        name={["reme_light_memory_config", "reranker_config"]}
        hidden
      >
        <input />
      </Form.Item>
      <RerankerModelCenter />
    </Form>
  );
}

function mockHistory(history: (typeof historyRecord)[]) {
  return vi.spyOn(api, "getRerankerHistory").mockResolvedValue({
    fingerprint: `sha256:${"a".repeat(64)}`,
    history,
  });
}

beforeEach(() => {
  useAgentStore.setState({ selectedAgent: "default" });
  useRerankerVerificationStore.setState({
    verificationByAgent: {},
    historyByAgent: {},
  });
  vi.restoreAllMocks();
});

describe("RerankerModelCenter verification status", () => {
  it("does not render Verified for an empty history response", async () => {
    mockHistory([]);

    renderWithProviders(<Harness />);

    await waitFor(() => expect(api.getRerankerHistory).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        screen.getAllByText("agentConfig.rerankerNotVerified").length,
      ).toBeGreaterThan(0),
    );
    expect(screen.queryByText("agentConfig.rerankerVerified")).toBeNull();
  });

  it("shows history-only precision but not Verified when history exists", async () => {
    mockHistory([historyRecord]);

    renderWithProviders(<Harness />);

    await waitFor(() =>
      expect(
        screen.queryByText("agentConfig.rerankerPrecisionHistoryOnly"),
      ).not.toBeNull(),
    );
    expect(screen.queryByText("agentConfig.rerankerVerified")).toBeNull();
    expect(screen.queryByText("agentConfig.rerankerPrecisionHint")).toBeNull();
  });

  it("renders Verified for a completed probe of the current service", async () => {
    mockHistory([]);
    const fingerprint = await getRerankerServiceFingerprint(enabledConfig);
    useRerankerVerificationStore.getState().setVerification("default", {
      fingerprint,
      latency: 42,
      precision: 1,
      correctCount: 5,
      total: 5,
      verifiedAt: Date.now(),
    });

    renderWithProviders(<Harness />);

    await waitFor(() =>
      expect(screen.queryByText("agentConfig.rerankerVerified")).not.toBeNull(),
    );
    // The empty history response must not erase the completed result.
    expect(
      screen.queryByText("agentConfig.rerankerVerificationMetrics", {
        exact: false,
      }),
    ).not.toBeNull();
  });

  it("does not treat a verdict for another service as current", async () => {
    mockHistory([]);
    const otherFingerprint = await getRerankerServiceFingerprint({
      ...enabledConfig,
      model_name: "some-other-reranker",
    });
    useRerankerVerificationStore.getState().setVerification("default", {
      fingerprint: otherFingerprint,
      latency: 42,
      precision: 1,
      correctCount: 5,
      total: 5,
      verifiedAt: Date.now(),
    });

    renderWithProviders(<Harness />);

    await waitFor(() =>
      expect(
        screen.getAllByText("agentConfig.rerankerNotVerified").length,
      ).toBeGreaterThan(0),
    );
    expect(screen.queryByText("agentConfig.rerankerVerified")).toBeNull();
  });

  it("ignores a stale history response that arrives after the form changed", async () => {
    let resolveStale: (value: {
      fingerprint: string;
      history: (typeof historyRecord)[];
    }) => void = () => {};
    const stale = new Promise<{
      fingerprint: string;
      history: (typeof historyRecord)[];
    }>((resolve) => {
      resolveStale = resolve;
    });
    const spy = vi.spyOn(api, "getRerankerHistory");
    spy.mockReturnValueOnce(stale);
    spy.mockResolvedValue({ fingerprint: "", history: [] });

    const { rerender } = renderWithProviders(<Harness />);
    await waitFor(() => expect(spy).toHaveBeenCalled());

    rerender(
      <Harness config={{ ...enabledConfig, model_name: "changed-reranker" }} />,
    );

    await act(async () => {
      resolveStale({
        fingerprint: `sha256:${"b".repeat(64)}`,
        history: [historyRecord],
      });
      await stale;
    });

// The superseded response belongs to another service and must be dropped;
    // the new service only ever receives its own (empty) series.
    await waitFor(() => {
      const stored =
        useRerankerVerificationStore.getState().historyByAgent.default;
      expect(stored?.records ?? []).toEqual([]);
    });
  });
});