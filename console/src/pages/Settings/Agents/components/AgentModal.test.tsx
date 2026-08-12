import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Form } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { agentsApi } from "@/api/modules/agents";
import { providerApi } from "@/api/modules/provider";
import { skillApi } from "@/api/modules/skill";
import { AgentModal } from "./AgentModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/api/modules/agents", () => ({
  agentsApi: { listWorkspaceRoots: vi.fn() },
}));

vi.mock("@/api/modules/provider", () => ({
  providerApi: { listProviders: vi.fn() },
}));

vi.mock("@/api/modules/skill", () => ({
  skillApi: {
    listSkillPoolSkills: vi.fn(),
    listSkills: vi.fn(),
  },
}));

vi.mock("./AgentBackendFields", () => ({
  AgentBackendFields: () => null,
}));

function AgentModalHarness() {
  const [form] = Form.useForm();
  return (
    <AgentModal
      open
      editingAgent={null}
      form={form}
      selectedSkills={[]}
      onSelectedSkillsChange={vi.fn()}
      onInstalledSkillsLoaded={vi.fn()}
      onSave={vi.fn()}
      onCancel={vi.fn()}
    />
  );
}

describe("AgentModal workspace roots", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(agentsApi.listWorkspaceRoots).mockResolvedValue({
      roots: [
        { id: "default", label: "C:\\QwenPaw\\workspaces" },
        { id: "projects", label: "D:\\AgentWorkspaces" },
      ],
    });
    vi.mocked(providerApi.listProviders).mockResolvedValue([]);
    vi.mocked(skillApi.listSkillPoolSkills).mockResolvedValue([]);
    vi.mocked(skillApi.listSkills).mockResolvedValue([]);
  });

  it("renders only server-provided workspace root choices", async () => {
    render(<AgentModalHarness />);

    await waitFor(() => {
      expect(agentsApi.listWorkspaceRoots).toHaveBeenCalledOnce();
    });

    const rootSelect = screen.getByLabelText("agent.workspaceRoot");
    fireEvent.mouseDown(rootSelect);

    expect(
      await screen.findAllByText("C:\\QwenPaw\\workspaces"),
    ).not.toHaveLength(0);
    expect(screen.getByText("D:\\AgentWorkspaces")).toBeInTheDocument();
  });
});
