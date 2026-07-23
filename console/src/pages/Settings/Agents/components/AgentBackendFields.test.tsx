import { fireEvent, screen } from "@testing-library/react";
import { Form } from "antd";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import { AgentBackendFields } from "./AgentBackendFields";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/api/modules/harness", () => ({
  harnessApi: {
    status: vi.fn().mockResolvedValue({
      id: "codex",
      name: "Codex",
      available: true,
      coming_soon: false,
      installed: true,
      authenticated: true,
      account: { type: "chatgpt", email: "person@example.com" },
      runtime_path: "/Applications/ChatGPT.app/Contents/Resources/codex",
      runtime_source: "chatgpt-app",
      error: null,
      capabilities: {
        authentication: true,
        model_selection: true,
        reasoning_effort: true,
      },
    }),
    list: vi.fn().mockResolvedValue({
      providers: [],
    }),
    listModels: vi.fn().mockResolvedValue({ models: [] }),
    login: vi.fn(),
    logout: vi.fn(),
  },
}));

import { harnessApi } from "@/api/modules/harness";

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: vi.fn(), error: vi.fn() },
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
});
