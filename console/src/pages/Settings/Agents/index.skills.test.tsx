import { Form, Radio } from "antd";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import AgentsPage from "./index";

const mocks = vi.hoisted(() => ({
  agent: {
    id: "existing-agent",
    name: "Existing Agent",
    description: "Existing description",
    workspace_dir: "/workspace/existing-agent",
    enabled: true,
    backend: "qwenpaw",
  },
  getAgent: vi.fn(),
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  listSkillPoolSkills: vi.fn(),
  listSkills: vi.fn(),
  downloadSkillPoolSkill: vi.fn(),
  loadAgents: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/api/modules/agents", () => ({
  agentsApi: mocks,
}));

vi.mock("@/api/modules/skill", () => ({
  skillApi: mocks,
  invalidateSkillCache: vi.fn(),
}));

vi.mock("./useAgents", () => ({
  useAgents: () => ({ agents: [mocks.agent], loading: false, ...mocks }),
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: () => ({
    selectedAgent: "default",
    setSelectedAgent: vi.fn(),
  }),
}));

vi.mock("./components/CopyAgentModal", () => ({ CopyAgentModal: () => null }));

vi.mock("./components/AgentBackendFields", () => ({
  AgentBackendFields: () => (
    <Form.Item name="backend">
      <Radio.Group
        options={[
          { label: "Native backend", value: "qwenpaw" },
          { label: "External backend", value: "codex" },
        ]}
      />
    </Form.Item>
  ),
}));

describe("agent skill creation workflow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getAgent.mockResolvedValue(mocks.agent);
    mocks.createAgent.mockResolvedValue({ id: "new-agent" });
    mocks.updateAgent.mockResolvedValue(mocks.agent);
    mocks.listSkillPoolSkills.mockResolvedValue([
      { name: "browser", source: "builtin" },
      { name: "custom-skill", source: "custom" },
    ]);
    mocks.listSkills.mockResolvedValue([]);
    mocks.downloadSkillPoolSkill.mockResolvedValue({});
    mocks.loadAgents.mockResolvedValue(undefined);
  });

  it("keeps skill selection and installation available during creation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await user.click(screen.getByRole("button", { name: "agent.create" }));

    const browser = await screen.findByText("browser");
    const customSkill = screen.getByText("custom-skill");
    await user.click(screen.getByRole("button", { name: "agent.selectAll" }));
    expect(browser.parentElement?.className).toContain("pickerCardSelected");
    expect(customSkill.parentElement?.className).toContain(
      "pickerCardSelected",
    );

    await user.click(screen.getByRole("button", { name: "agent.selectNone" }));
    expect(browser.parentElement?.className).not.toContain(
      "pickerCardSelected",
    );
    expect(customSkill.parentElement?.className).not.toContain(
      "pickerCardSelected",
    );

    await user.click(
      screen.getByRole("button", { name: "agent.selectBuiltin" }),
    );
    expect(browser.parentElement?.className).toContain("pickerCardSelected");
    expect(customSkill.parentElement?.className).not.toContain(
      "pickerCardSelected",
    );
    await user.click(customSkill);
    await user.click(browser);
    await user.type(screen.getByLabelText("agent.name"), "New Agent");
    await user.click(screen.getByRole("button", { name: "common.save" }));

    await waitFor(() => {
      expect(mocks.createAgent).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "New Agent",
          backend: "qwenpaw",
          skill_names: ["custom-skill"],
        }),
      );
    });
    expect(mocks.listSkills).not.toHaveBeenCalled();
    expect(mocks.downloadSkillPoolSkill).not.toHaveBeenCalled();
  });

  it("hides skills and updates only agent configuration when editing", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await user.click(screen.getByRole("button", { name: "common.edit" }));
    await screen.findByText("agent.editTitle");

    expect(
      screen.queryByText("agent.addSkillsToAgent"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("agent.initialSkills")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "agent.selectAll" }),
    ).not.toBeInTheDocument();
    expect(mocks.listSkillPoolSkills).not.toHaveBeenCalled();
    expect(mocks.listSkills).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("agent.name"));
    await user.type(screen.getByLabelText("agent.name"), "Updated Agent");
    await user.click(screen.getByRole("button", { name: "common.save" }));

    await waitFor(() => {
      expect(mocks.updateAgent).toHaveBeenCalledWith(
        "existing-agent",
        expect.objectContaining({ name: "Updated Agent" }),
      );
    });
    expect(mocks.updateAgent.mock.calls[0][1]).not.toHaveProperty(
      "skill_names",
    );
    expect(mocks.downloadSkillPoolSkill).not.toHaveBeenCalled();
    expect(mocks.createAgent).not.toHaveBeenCalled();
  });

  it("keeps skill controls out of the detail preview", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await user.click(
      screen.getByRole("button", {
        name: /Existing Agent.*agent.modelPlaceholder/,
      }),
    );

    const preview = within(await screen.findByRole("dialog"));
    expect(preview.getByText("Existing description")).toBeVisible();
    expect(preview.queryByText("agent.initialSkills")).not.toBeInTheDocument();
    expect(
      preview.queryByText("agent.addSkillsToAgent"),
    ).not.toBeInTheDocument();
    expect(
      preview.queryByRole("button", { name: "agent.selectAll" }),
    ).not.toBeInTheDocument();
    expect(mocks.listSkillPoolSkills).not.toHaveBeenCalled();
    expect(mocks.listSkills).not.toHaveBeenCalled();
  });

  it("excludes selected native skills when creating an external agent", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await user.click(screen.getByRole("button", { name: "agent.create" }));
    await user.click(await screen.findByText("browser"));
    await user.click(screen.getByRole("radio", { name: "External backend" }));

    expect(screen.queryByText("agent.initialSkills")).not.toBeInTheDocument();
    expect(screen.queryByText("browser")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("agent.name"), "External Agent");
    await user.click(screen.getByRole("button", { name: "common.save" }));

    await waitFor(() => {
      expect(mocks.createAgent).toHaveBeenCalledWith(
        expect.objectContaining({ backend: "codex", skill_names: [] }),
      );
    });
  });
});
