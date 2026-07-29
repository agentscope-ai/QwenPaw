import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { Form } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import { AgentBackendFields } from "./AgentBackendFields";

const { mockCopyText, mockMessage, mockProvider } = vi.hoisted(() => ({
  mockCopyText: vi.fn().mockResolvedValue(undefined),
  mockMessage: {
    success: vi.fn(),
    error: vi.fn(),
  },
  mockProvider: {
    id: "codex",
    name: "Codex",
    available: true,
    coming_soon: false,
    installed: true,
    authenticated: true,
    account: { type: "chatgpt", email: "person@example.com" },
    runtime_path: "/opt/qwenpaw/site-packages/codex_cli_bin/bin/codex",
    runtime_source: "python-sdk",
    error: null,
    capabilities: {
      authentication: true,
      model_selection: true,
      reasoning_effort: true,
      reasoning_stream: true,
      tool_stream: true,
      session_resume: true,
      workspace_ui: false,
      native_skills_ui: false,
      native_tools_ui: false,
      native_mcp_ui: false,
      qwenpaw_skills_projection: true,
      qwenpaw_mcp_projection: true,
      provider_skills_discovery: true,
      provider_mcp_discovery: true,
      mcp_tool_allowlist: true,
      loop_modes: false,
      attachments: false,
      context_usage: false,
      skills_commands: false,
      commands: [],
      approval_presets: [],
    },
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { type?: string }) =>
      key === "harnesses.cliAuthenticated"
        ? `${options?.type} CLI authenticated`
        : key,
  }),
}));

vi.mock("@/api/modules/harness", () => ({
  harnessApi: {
    status: vi.fn().mockResolvedValue(mockProvider),
    list: vi.fn().mockResolvedValue({
      providers: [],
    }),
    listModels: vi.fn().mockResolvedValue({ models: [] }),
    login: vi.fn(),
    logout: vi.fn(),
  },
}));

vi.mock("@/utils/clipboard", () => ({
  copyText: mockCopyText,
}));

import { harnessApi } from "@/api/modules/harness";

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: mockMessage,
  }),
}));

function BackendForm() {
  const [form] = Form.useForm();
  return (
    <Form form={form} initialValues={{ backend: "qwenpaw" }}>
      <AgentBackendFields form={form} open />
    </Form>
  );
}

describe("AgentBackendFields", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(harnessApi.status).mockResolvedValue(mockProvider);
    mockCopyText.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("separates native and third-party agent creation", async () => {
    renderWithProviders(<BackendForm />);

    expect(screen.getByText("agent.backend.nativeTitle")).toBeInTheDocument();
    expect(
      screen.getByText("agent.backend.thirdPartyTitle"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("agent.backend.providerTitle"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("agent.backend.thirdPartyTitle"));

    expect(
      await screen.findByText("agent.backend.providerTitle"),
    ).toBeInTheDocument();
    expect(screen.getByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText("Qoder")).toBeInTheDocument();
  });

  it("probes the executable path entered by the user", async () => {
    renderWithProviders(<BackendForm />);
    fireEvent.click(screen.getByText("agent.backend.thirdPartyTitle"));

    const input = await screen.findByLabelText("agent.backend.binary");
    fireEvent.change(input, { target: { value: "/custom/bin/codex" } });
    fireEvent.click(screen.getByText("agent.backend.detect"));

    expect(harnessApi.status).toHaveBeenLastCalledWith("codex", {
      binary: "/custom/bin/codex",
    });
  });

  it("shows a compact detected path and copies the full path", async () => {
    renderWithProviders(<BackendForm />);
    fireEvent.click(screen.getByText("agent.backend.thirdPartyTitle"));

    expect(
      await screen.findByText("agent.backend.detectedBinary"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agent.backend.capabilityTitle"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("agent.backend.runtimeInherited")).toHaveLength(
      2,
    );
    expect(
      screen.getByText("agent.backend.toolAllowlistSupported"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("/opt/qwenpaw/site-packages/codex_cli_bin/bin/codex"),
    ).toHaveProperty("tagName", "CODE");
    expect(
      screen.queryByText("agent.backend.binaryHelp"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "common.copy" }));

    await waitFor(() =>
      expect(mockCopyText).toHaveBeenCalledWith(
        "/opt/qwenpaw/site-packages/codex_cli_bin/bin/codex",
      ),
    );
    expect(mockMessage.success).toHaveBeenCalledWith("common.copied");
  });

  it("shows a compact not-detected state", async () => {
    vi.mocked(harnessApi.status).mockResolvedValueOnce({
      ...mockProvider,
      installed: false,
      authenticated: false,
      account: null,
      runtime_path: null,
      runtime_source: null,
    });
    renderWithProviders(<BackendForm />);
    fireEvent.click(screen.getByText("agent.backend.thirdPartyTitle"));

    expect(
      (await screen.findAllByText("agent.backend.codexNotFound")).length,
    ).toBeGreaterThan(0);
  });

  it("shows API key authentication without an OAuth action", async () => {
    vi.mocked(harnessApi.status).mockResolvedValueOnce({
      id: "codex",
      name: "Codex",
      available: true,
      coming_soon: false,
      installed: true,
      authenticated: true,
      account: { type: "apiKey" },
      runtime_path: "/usr/local/bin/codex",
      runtime_source: "path",
      error: null,
      capabilities: {
        authentication: true,
        model_selection: true,
        reasoning_effort: true,
        reasoning_stream: true,
        tool_stream: true,
        session_resume: true,
        workspace_ui: false,
        native_skills_ui: false,
        native_tools_ui: false,
        native_mcp_ui: false,
        qwenpaw_skills_projection: true,
        qwenpaw_mcp_projection: true,
        provider_skills_discovery: true,
        provider_mcp_discovery: true,
        mcp_tool_allowlist: true,
        loop_modes: false,
        attachments: false,
        context_usage: false,
        skills_commands: false,
        commands: [],
        approval_presets: [],
      },
    });
    renderWithProviders(<BackendForm />);
    fireEvent.click(screen.getByText("agent.backend.thirdPartyTitle"));

    expect(
      await screen.findByText("harnesses.apiKeyAuthenticated"),
    ).toBeInTheDocument();
    expect(screen.queryByText("harnesses.connect")).not.toBeInTheDocument();
    expect(screen.queryByText("harnesses.disconnect")).not.toBeInTheDocument();
  });

  it("selects Qoder and uses its executable and login flow", async () => {
    vi.mocked(harnessApi.status).mockImplementation(async (providerId) => ({
      ...mockProvider,
      id: providerId,
      name: providerId === "qoder" ? "Qoder" : "Codex",
      authenticated: false,
      account: null,
      runtime_path:
        providerId === "qoder"
          ? "/opt/qoder/qodercli"
          : mockProvider.runtime_path,
      runtime_source: "python-sdk",
    }));
    vi.mocked(harnessApi.login).mockResolvedValue({
      type: "external",
      loginId: "qoder-login",
      command: "/opt/qoder/qodercli login",
    });
    const view = renderWithProviders(<BackendForm />);
    fireEvent.click(screen.getByText("agent.backend.thirdPartyTitle"));
    fireEvent.click(screen.getByText("Qoder"));

    const input = await screen.findByLabelText("agent.backend.qoderBinary");
    fireEvent.change(input, { target: { value: "/custom/qodercli" } });
    fireEvent.click(screen.getByText("agent.backend.detect"));

    await waitFor(() =>
      expect(harnessApi.status).toHaveBeenLastCalledWith("qoder", {
        binary: "/custom/qodercli",
      }),
    );
    expect(screen.queryByText("harnesses.connect")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("agent.backend.qoderConnect"));
    await waitFor(() =>
      expect(harnessApi.login).toHaveBeenCalledWith("qoder", false, {
        binary: "/custom/qodercli",
      }),
    );
    view.unmount();
  });

  it("waits for each login status request before polling again", async () => {
    vi.mocked(harnessApi.status).mockImplementation(async (providerId) => ({
      ...mockProvider,
      id: providerId,
      name: providerId === "qoder" ? "Qoder" : "Codex",
      authenticated: false,
      account: null,
    }));
    vi.mocked(harnessApi.login).mockResolvedValue({
      type: "external",
      loginId: "qoder-login",
      command: "/opt/qoder/qodercli login",
    });
    const view = renderWithProviders(<BackendForm />);
    fireEvent.click(screen.getByText("agent.backend.thirdPartyTitle"));
    fireEvent.click(screen.getByText("Qoder"));

    const connect = await screen.findByText("agent.backend.qoderConnect");
    await waitFor(() =>
      expect(harnessApi.status).toHaveBeenCalledWith("qoder", {}),
    );
    vi.mocked(harnessApi.status).mockClear();
    vi.mocked(harnessApi.status).mockImplementation(
      () => new Promise(() => undefined),
    );
    vi.useFakeTimers();

    fireEvent.click(connect);
    await act(async () => undefined);
    await act(async () => {
      vi.advanceTimersByTime(2_000);
    });

    expect(harnessApi.status).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });

    expect(harnessApi.status).toHaveBeenCalledTimes(1);
    view.unmount();
  });

  it("shows the authenticated Qoder CLI account", async () => {
    vi.mocked(harnessApi.status).mockImplementation(async (providerId) => ({
      ...mockProvider,
      id: providerId,
      name: providerId === "qoder" ? "Qoder" : "Codex",
      authenticated: providerId === "qoder",
      account:
        providerId === "qoder"
          ? { type: "qodercli", username: "qoder-user" }
          : mockProvider.account,
      runtime_path:
        providerId === "qoder"
          ? "/opt/qoder/qodercli"
          : mockProvider.runtime_path,
      runtime_source: "python-sdk",
    }));
    renderWithProviders(<BackendForm />);
    fireEvent.click(screen.getByText("agent.backend.thirdPartyTitle"));
    fireEvent.click(screen.getByText("Qoder"));

    expect(
      await screen.findByText("Qoder CLI authenticated · qoder-user"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Codex CLI/)).not.toBeInTheDocument();
    expect(
      screen.queryByText("agent.backend.qoderConnect"),
    ).not.toBeInTheDocument();
  });
});
