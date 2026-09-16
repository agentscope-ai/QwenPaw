import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentSummary } from "@/api/types/agents";
import { renderWithProviders } from "@/test/common_setup";
import { AgentTable } from "./AgentTable";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string>) =>
      options?.model ? `${key}:${options.model}` : key,
  }),
}));

const agent = (
  id: string,
  pinned: boolean,
  backend: AgentSummary["backend"] = "qwenpaw",
  overrides: Partial<AgentSummary> = {},
): AgentSummary => ({
  id,
  name: id,
  description: "",
  workspace_dir: "",
  enabled: true,
  backend,
  pinned,
  startup_status: "running",
  access_role: "owner",
  registration_state: "registered",
  can_edit: true,
  can_delete: true,
  can_copy: true,
  can_toggle: true,
  can_reorder: true,
  ...overrides,
});

describe("AgentTable", () => {
  it("shows the effective global model for inherited Agents", () => {
    renderWithProviders(
      <AgentTable
        agents={[agent("inherited", false)]}
        loading={false}
        reordering={false}
        globalActiveModel={{ provider_id: "global", model: "gpt-global" }}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
      />,
    );

    expect(
      screen.getByText("agent.modelInheritCurrent:global/gpt-global"),
    ).toBeInTheDocument();
  });

  it("uses click-specific labels for pin actions", () => {
    renderWithProviders(
      <AgentTable
        agents={[agent("unpinned", false), agent("pinned", true)]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
        onManageMembers={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "agent.pinAgent" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "agent.unpinAgent" }),
    ).toBeInTheDocument();
  });

  it("does not size the scroll area from the browser viewport", () => {
    const { container } = renderWithProviders(
      <AgentTable
        agents={[agent("a", false)]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
        onManageMembers={vi.fn()}
      />,
    );

    // Regression guard: the table body height must come from the container
    // (measured), never from 100vh, so OS windows don't nest scrollbars.
    expect(container.innerHTML).not.toContain("100vh");
  });

  it("keeps Copy enabled for default agent with template tooltip", () => {
    renderWithProviders(
      <AgentTable
        agents={[agent("default", true), agent("custom", false)]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
        onManageMembers={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("button", { name: "agent.copy" })).toHaveLength(
      2,
    );
  });

  it("shows each agent runtime backend", () => {
    renderWithProviders(
      <AgentTable
        agents={[
          agent("native", false),
          agent("coding", false, "codex"),
          agent("qoder", false, "qoder"),
        ]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
        onManageMembers={vi.fn()}
      />,
    );

    expect(screen.getByText(/QwenPaw/)).toBeInTheDocument();
    expect(screen.getByText(/Codex/)).toBeInTheDocument();
    expect(screen.getByText(/Qoder/)).toBeInTheDocument();
  });

  it("shows the resource role and disables management for run-only users", () => {
    renderWithProviders(
      <AgentTable
        agents={[
          agent("run-only", false, "qwenpaw", {
            access_role: "user",
            can_edit: false,
            can_delete: false,
            can_copy: false,
            can_toggle: false,
            can_reorder: false,
          }),
        ]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
        onManageMembers={vi.fn()}
      />,
    );

    expect(screen.getByText("agent.accessRole.user")).toBeInTheDocument();
    expect(screen.getByLabelText("agent.dragHandleTooltip")).toBeDisabled();
    expect(screen.getByRole("button", { name: "agent.edit" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "agent.copy" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "agent.disable" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "agent.delete" })).toBeDisabled();
  });

  it("shows member management only for owners and marks public Agents", () => {
    renderWithProviders(
      <AgentTable
        agents={[
          agent("owned", false, "qwenpaw", { can_manage_members: true }),
          agent("public", false, "qwenpaw", {
            access_role: "user",
            visibility: "public",
            can_manage_members: false,
            model_locked: true,
          }),
        ]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
        onManageMembers={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "agent.manageMembers" }),
    ).toBeEnabled();
    expect(screen.getByText("agent.visibility.public")).toBeInTheDocument();
    expect(screen.getByText("agent.modelLocked")).toBeInTheDocument();
  });

  it("offers portable export only for owners", () => {
    renderWithProviders(
      <AgentTable
        agents={[
          agent("owned", false),
          agent("shared", false, "qwenpaw", {
            access_role: "collaborator",
          }),
        ]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onExport={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
      />,
    );

    expect(
      screen.getAllByRole("button", { name: "agent.exportPortable" }),
    ).toHaveLength(1);
  });

  it("lets an administrator publish an owned Agent from the owner tab", () => {
    const onPublication = vi.fn();
    const owned = agent("owned", false, "qwenpaw", {
      visibility: "private",
    });
    renderWithProviders(
      <AgentTable
        agents={[owned]}
        loading={false}
        reordering={false}
        isAdmin
        onPublication={onPublication}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "agent.publishPublic" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));

    expect(onPublication).toHaveBeenCalledWith(owned, true);
  });

  it("gives every icon action an explicit accessible label", () => {
    renderWithProviders(
      <AgentTable
        agents={[
          agent("owned", false, "qwenpaw", { can_manage_members: true }),
        ]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onExport={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
        onManageMembers={vi.fn()}
      />,
    );

    for (const label of [
      "agent.manageMembers",
      "agent.pinAgent",
      "agent.edit",
      "agent.exportPortable",
      "agent.copy",
      "agent.disable",
      "agent.delete",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });
});
