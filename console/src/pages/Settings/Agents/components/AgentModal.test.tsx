import { Form } from "antd";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { modelCatalogApi } from "@/api/modules/modelCatalog";
import { describe, expect, it, vi } from "vitest";
import type { AgentSummary } from "@/api/types/agents";
import { renderWithProviders } from "@/test/common_setup";
import { AgentModal, toAgentActiveModel } from "./AgentModal";

vi.mock("react-i18next", () => {
  const t = (key: string, options?: Record<string, string>) =>
    options?.model ? `${key}:${options.model}` : key;
  return { useTranslation: () => ({ t }) };
});

vi.mock("@/api/modules/provider", () => ({
  providerApi: {
    listProviders: vi.fn().mockResolvedValue([
      {
        id: "global",
        name: "Global Provider",
        api_key: "configured",
        base_url: "https://example.test/v1",
        require_api_key: true,
        is_custom: true,
        models: [{ id: "gpt-global", name: "GPT Global" }],
        extra_models: [],
      },
    ]),
    getActiveModels: vi.fn().mockRejectedValue(new Error("forbidden")),
  },
}));
vi.mock("@/api/modules/modelCatalog", () => ({
  modelCatalogApi: {
    list: vi.fn().mockResolvedValue({
      enforced: true,
      models: [
        {
          id: "m",
          provider_id: "global",
          provider_name: "Global Provider",
          model: "gpt-global",
          name: "GPT Global",
        },
      ],
    }),
    default: vi.fn().mockResolvedValue({
      active_llm: { provider_id: "global", model: "gpt-global" },
    }),
  },
}));

vi.mock("@/api/modules/skill", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/api/modules/skill")>(),
  skillApi: {
    listSkillPoolSkills: vi.fn().mockResolvedValue([]),
    listSkills: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock("@/api/modules/harness", () => ({
  harnessApi: { status: vi.fn() },
}));

function ModalHarness({ editingAgent }: { editingAgent: AgentSummary | null }) {
  const [form] = Form.useForm();
  return (
    <AgentModal
      open
      editingAgent={editingAgent}
      form={form}
      selectedSkills={[]}
      onSelectedSkillsChange={vi.fn()}
      onInstalledSkillsLoaded={vi.fn()}
      onSave={vi.fn().mockResolvedValue(undefined)}
      onCancel={vi.fn()}
    />
  );
}

describe("AgentModal model inheritance", () => {
  it("keeps authorized models when the platform default is forbidden", async () => {
    vi.mocked(modelCatalogApi.default).mockRejectedValueOnce(new Error("403"));
    renderWithProviders(<ModalHarness editingAgent={null} />);
    const selects = await screen.findAllByRole("combobox");
    fireEvent.mouseDown(selects[0]);
    expect(await screen.findByText("Global Provider")).toBeInTheDocument();
  });
  it("shows the current global model when the Agent inherits", async () => {
    renderWithProviders(<ModalHarness editingAgent={null} />);

    expect(
      await screen.findByText("agent.modelInheritCurrent:global/gpt-global"),
    ).toBeInTheDocument();
  });

  it("converts empty selection back to an inherited null payload", () => {
    expect(
      toAgentActiveModel({
        backend: "qwenpaw",
        active_model_provider: undefined,
        active_model_model: undefined,
      }),
    ).toBeNull();
    expect(
      toAgentActiveModel({
        backend: "qwenpaw",
        active_model_provider: "global",
        active_model_model: "gpt-explicit",
      }),
    ).toEqual({ provider_id: "global", model: "gpt-explicit" });
  });

  it("disables model selection for a run-only locked Agent", async () => {
    const locked: AgentSummary = {
      id: "public-agent",
      name: "Public Agent",
      description: "",
      workspace_dir: "",
      enabled: true,
      backend: "qwenpaw",
      can_edit: false,
      model_locked: true,
    };
    renderWithProviders(<ModalHarness editingAgent={locked} />);

    await waitFor(() => {
      const disabledModelInputs = screen
        .getAllByRole("combobox")
        .filter((element) => element.hasAttribute("disabled"));
      expect(disabledModelInputs.length).toBeGreaterThanOrEqual(2);
    });
  });
});
