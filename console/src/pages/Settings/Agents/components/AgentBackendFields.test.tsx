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
    list: vi.fn().mockResolvedValue({
      providers: [
        {
          id: "codex",
          name: "Codex",
          available: true,
          coming_soon: false,
          installed: true,
          authenticated: true,
          account: { email: "person@example.com" },
          error: null,
          capabilities: {
            authentication: true,
            model_selection: true,
            reasoning_effort: true,
          },
        },
      ],
    }),
    listModels: vi.fn().mockResolvedValue({ models: [] }),
    login: vi.fn(),
    logout: vi.fn(),
  },
}));

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
});
