/**
 * RerankerModelCenter — rendered status and manual-request lifecycle.
 *
 * A "Verified" badge requires a completed probe of the current service, and a
 * late response must not touch state, dialogs or the loading flag once the
 * agent or configuration changed.
 */
import { Form } from "@agentscope-ai/design";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";

import { api } from "@/api";
import type { RerankerTestResponse } from "@/api/modules/agent";
import { useAgentStore } from "@/stores/agentStore";
import { useRerankerVerificationStore } from "@/stores/rerankerVerificationStore";
import { renderWithProviders } from "@/test/common_setup";
import { getRerankerConfigKey } from "./rerankerUtils";
import { RerankerModelCenter } from "./RerankerModelCenter";

const modalMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string) => key,
      i18n: { resolvedLanguage: "zh-CN", language: "zh-CN" },
    }),
  };
});

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ modal: modalMocks }),
}));

// Generated per run so no credential-like literal is committed.
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

const disabledConfig = { ...enabledConfig, enabled: false };

const historyRecord = {
  ts: 1_700_000_000_000,
  latency_ms: 120,
  precision: 0.8,
  correct_count: 4,
  total: 5,
};

function Harness({
  config = enabledConfig,
}: {
  config?: typeof enabledConfig;
}) {
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
      <Form.Item name={["reme_light_memory_config", "reranker_config"]} hidden>
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

async function clickTest() {
  await act(async () => {
    fireEvent.click(
      screen.getByLabelText("agentConfig.rerankerTestConnection"),
    );
  });
}

beforeEach(() => {
  useAgentStore.setState({ selectedAgent: "default" });
  useRerankerVerificationStore.setState({
    verificationByAgent: {},
    historyByAgent: {},
  });
  vi.restoreAllMocks();
  modalMocks.success.mockReset();
  modalMocks.error.mockReset();
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
    useRerankerVerificationStore.getState().setVerification("default", {
      configKey: getRerankerConfigKey(enabledConfig),
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
  });

  it("does not treat a verdict for another service as current", async () => {
    mockHistory([]);
    useRerankerVerificationStore.getState().setVerification("default", {
      configKey: getRerankerConfigKey({
        ...enabledConfig,
        model_name: "some-other-reranker",
      }),
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

  it("history is resolved by the backend, without a client fingerprint", async () => {
    const spy = mockHistory([historyRecord]);

    renderWithProviders(<Harness />);

    await waitFor(() => expect(spy).toHaveBeenCalledWith());
  });
});

describe("RerankerModelCenter manual request identity", () => {
  it("a late failure does not clear the verdict of a newly selected config", async () => {
    mockHistory([]);
    const response = deferred<RerankerTestResponse>();
    vi.spyOn(api, "testReranker").mockReturnValue(response.promise);

    const { rerender } = renderWithProviders(<Harness />);
    await clickTest();

    const nextConfig = { ...enabledConfig, model_name: "new-reranker" };
    rerender(<Harness config={nextConfig} />);
    const newKey = getRerankerConfigKey(nextConfig);
    await waitFor(() =>
      expect(
        useRerankerVerificationStore.getState().verificationByAgent.default
          ?.configKey,
      ).not.toBe(getRerankerConfigKey(enabledConfig)),
    );
    useRerankerVerificationStore.getState().setVerification("default", {
      configKey: newKey,
      latency: 11,
      precision: 1,
      correctCount: 5,
      total: 5,
      verifiedAt: Date.now(),
    });

    await act(async () => {
      response.resolve({
        success: false,
        latency_ms: 5,
        message: "old failure",
        total: 0,
        correct_count: 0,
        precision: null,
        cases: null,
        history: null,
      });
      await response.promise;
    });

    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default
        ?.configKey,
    ).toBe(newKey);
    expect(modalMocks.error).not.toHaveBeenCalled();
  });

  it("a late success does not verify after reranking was disabled", async () => {
    mockHistory([]);
    const response = deferred<RerankerTestResponse>();
    vi.spyOn(api, "testReranker").mockReturnValue(response.promise);

    const { rerender } = renderWithProviders(<Harness />);
    await clickTest();
    rerender(<Harness config={disabledConfig} />);
    await waitFor(() =>
      expect(
        screen.queryByText("agentConfig.rerankerCapabilityDisabled"),
      ).not.toBeNull(),
    );

    await act(async () => {
      response.resolve({
        success: true,
        latency_ms: 42,
        message: "ok",
        total: 5,
        correct_count: 5,
        precision: 1,
        cases: null,
        history: [],
      });
      await response.promise;
    });

    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default,
    ).toBeUndefined();
    expect(modalMocks.success).not.toHaveBeenCalled();
    expect(screen.queryByText("agentConfig.rerankerVerified")).toBeNull();
  });

  it("a late success for a superseded config is not stored", async () => {
    mockHistory([]);
    const response = deferred<RerankerTestResponse>();
    vi.spyOn(api, "testReranker").mockReturnValue(response.promise);

    const { rerender } = renderWithProviders(<Harness />);
    await clickTest();
    rerender(
      <Harness config={{ ...enabledConfig, model_name: "changed-reranker" }} />,
    );
    await waitFor(() =>
      expect(
        useRerankerVerificationStore.getState().verificationByAgent.default,
      ).toBeUndefined(),
    );

    await act(async () => {
      response.resolve({
        success: true,
        latency_ms: 42,
        message: "ok",
        total: 5,
        correct_count: 5,
        precision: 1,
        cases: null,
        history: [],
      });
      await response.promise;
    });

    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default,
    ).toBeUndefined();
    expect(modalMocks.success).not.toHaveBeenCalled();
  });

  it("does not display model A history after switching to model B within the same agent", async () => {
    const secondRecord = {
      ...historyRecord,
      ts: 1_700_000_005_000,
      precision: 1.0,
    };
    mockHistory([historyRecord, secondRecord]);

    const { rerender, container } = renderWithProviders(<Harness />);
    await waitFor(() =>
      expect(
        screen.queryByText("agentConfig.rerankerPrecisionHistoryOnly"),
      ).not.toBeNull(),
    );
    expect(container.querySelector("svg polyline")).not.toBeNull();

    rerender(<Harness config={{ ...enabledConfig, model_name: "model-b" }} />);
    await waitFor(() =>
      expect(
        screen.queryByText("agentConfig.rerankerPrecisionHint"),
      ).not.toBeNull(),
    );
    expect(
      screen.queryByText("agentConfig.rerankerPrecisionHistoryOnly"),
    ).toBeNull();
    expect(container.querySelector("svg polyline")).toBeNull();
  });

  it("preserves the displayed trend when a manual probe fails", async () => {
    const secondRecord = {
      ...historyRecord,
      ts: 1_700_000_005_000,
      precision: 1.0,
    };
    mockHistory([historyRecord, secondRecord]);
    vi.spyOn(api, "testReranker").mockResolvedValue({
      success: false,
      latency_ms: 12,
      message: "service unavailable",
      total: 0,
      correct_count: 0,
      precision: null,
      cases: null,
      history: null,
    });

    const { container } = renderWithProviders(<Harness />);
    await waitFor(() =>
      expect(
        screen.queryByText("agentConfig.rerankerPrecisionHistoryOnly"),
      ).not.toBeNull(),
    );
    expect(container.querySelector("svg polyline")).not.toBeNull();

    await clickTest();

    await waitFor(() => expect(modalMocks.error).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByText("agentConfig.rerankerPrecisionHistoryOnly"),
    ).not.toBeNull();
    expect(container.querySelector("svg polyline")).not.toBeNull();
  });

  it("does not open the success dialog if unmounted while a manual probe is pending", async () => {
    mockHistory([]);
    const response = deferred<RerankerTestResponse>();
    vi.spyOn(api, "testReranker").mockReturnValue(response.promise);

    const { unmount } = renderWithProviders(<Harness />);
    await clickTest();
    unmount();

    await act(async () => {
      response.resolve({
        success: true,
        latency_ms: 42,
        message: "ok",
        total: 5,
        correct_count: 5,
        precision: 1,
        cases: null,
        fingerprint: `sha256:${"a".repeat(64)}`,
        history: [historyRecord],
      });
      await response.promise;
    });

    expect(modalMocks.success).not.toHaveBeenCalled();
    expect(modalMocks.error).not.toHaveBeenCalled();
    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default,
    ).toBeUndefined();
  });

  it("does not open the error dialog if unmounted while a manual probe is pending", async () => {
    mockHistory([]);
    const response = deferred<RerankerTestResponse>();
    vi.spyOn(api, "testReranker").mockReturnValue(response.promise);

    const { unmount } = renderWithProviders(<Harness />);
    await clickTest();
    unmount();

    await act(async () => {
      response.resolve({
        success: false,
        latency_ms: 10,
        message: "boom",
        total: 0,
        correct_count: 0,
        precision: null,
        cases: null,
        history: null,
      });
      await response.promise;
    });

    expect(modalMocks.error).not.toHaveBeenCalled();
    expect(modalMocks.success).not.toHaveBeenCalled();
  });

  it("unlocks testing immediately when switching models mid-probe", async () => {
    mockHistory([]);
    const modelAResponse = deferred<RerankerTestResponse>();
    const modelBResponse = deferred<RerankerTestResponse>();
    vi.spyOn(api, "testReranker")
      .mockReturnValueOnce(modelAResponse.promise)
      .mockReturnValueOnce(modelBResponse.promise);

    const { rerender } = renderWithProviders(<Harness />);
    const button = screen.getByLabelText("agentConfig.rerankerTestConnection");
    await clickTest();
    expect(button).toBeDisabled();

    // Switch to model B before model A's probe returns: button unlocks at once.
    const modelB = { ...enabledConfig, model_name: "model-b" };
    rerender(<Harness config={modelB} />);
    await waitFor(() => expect(button).not.toBeDisabled());

    // Start testing model B, then resolve model A's stale failure first.
    await clickTest();
    expect(button).toBeDisabled();
    await act(async () => {
      modelAResponse.resolve({
        success: false,
        latency_ms: 5,
        message: "model A failed",
        total: 0,
        correct_count: 0,
        precision: null,
        cases: null,
        history: null,
      });
      await modelAResponse.promise;
    });
    expect(modalMocks.error).not.toHaveBeenCalled();
    expect(button).toBeDisabled();

    // Model B succeeds cleanly.
    await act(async () => {
      modelBResponse.resolve({
        success: true,
        latency_ms: 30,
        message: "ok",
        total: 5,
        correct_count: 5,
        precision: 1,
        cases: null,
        fingerprint: `sha256:${"b".repeat(64)}`,
        history: [{ ...historyRecord, ts: 1_700_000_009_000, precision: 1 }],
      });
      await modelBResponse.promise;
    });
    expect(modalMocks.success).toHaveBeenCalledTimes(1);
    expect(button).not.toBeDisabled();
    expect(screen.queryByText("agentConfig.rerankerVerified")).not.toBeNull();
  });

  it("surfaces history_error on a successful probe without rendering 0% rolling average", async () => {
    mockHistory([]);
    vi.spyOn(api, "testReranker").mockResolvedValue({
      success: true,
      latency_ms: 42,
      message: "ok",
      total: 5,
      correct_count: 5,
      precision: 1,
      cases: null,
      fingerprint: `sha256:${"a".repeat(64)}`,
      history: null,
      history_error: "Failed to save verification history: disk full",
    });

    renderWithProviders(<Harness />);
    await clickTest();

    await waitFor(() => expect(modalMocks.success).toHaveBeenCalledTimes(1));
    expect(modalMocks.success.mock.calls[0][0].content).toContain("disk full");
    expect(screen.queryByText("agentConfig.rerankerVerified")).not.toBeNull();
    expect(
      screen.queryByText("agentConfig.rerankerPrecisionRolling"),
    ).toBeNull();
  });
});
