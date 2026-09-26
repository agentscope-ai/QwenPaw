import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { AgentGallery } from "./AgentGallery";
import type { AgentSummary } from "@/api/types/agents";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
describe("AgentGallery", () => {
  it("keeps default-agent protections while allowing copying from detail", async () => {
    const copy = vi.fn();
    renderWithProviders(
      <AgentGallery
        agents={[
          {
            id: "default",
            name: "Default",
            description: "Description",
            workspace_dir: "/workspace",
            enabled: true,
            backend: "qwenpaw",
            startup_status: "running",
          } as AgentSummary,
        ]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={copy}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "agent.dragHandleTooltip" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: /agent.modelPlaceholder/ }),
    );
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("button", { name: "common.edit" })).toBeDisabled();
    expect(
      dialog.getByRole("button", { name: "common.disable" }),
    ).toBeDisabled();
    expect(
      dialog.getByRole("button", { name: "common.delete" }),
    ).toBeDisabled();
    fireEvent.click(dialog.getByRole("button", { name: "common.copy" }));
    expect(copy).toHaveBeenCalledWith(
      expect.objectContaining({ id: "default" }),
    );
  });
  it("keeps pin actions and backend identities in the active gallery", () => {
    const onPin = vi.fn();
    renderWithProviders(
      <AgentGallery
        agents={[
          { id: "native", name: "Native", backend: "qwenpaw", pinned: false },
          { id: "external", name: "External", backend: "codex", pinned: true },
        ].map(
          (agent) =>
            ({
              ...agent,
              description: "",
              workspace_dir: "",
              enabled: true,
            }) as AgentSummary,
        )}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={onPin}
        onReorder={vi.fn()}
      />,
    );
    expect(screen.getByText("QwenPaw")).toBeVisible();
    expect(screen.getAllByText("codex").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "agent.pinAgent" }));
    expect(onPin).toHaveBeenLastCalledWith("native", false);
    fireEvent.click(screen.getByRole("button", { name: "agent.unpinAgent" }));
    expect(onPin).toHaveBeenLastCalledWith("external", true);
  });

  it("uses the latest action callback after a parent rerender", () => {
    const firstCopy = vi.fn();
    const nextCopy = vi.fn();
    const agent = {
      id: "sample",
      name: "Sample",
      description: "",
      workspace_dir: "/sample",
      enabled: true,
      backend: "qwenpaw",
    } as AgentSummary;
    const props = {
      agents: [agent],
      loading: false,
      reordering: false,
      onEdit: vi.fn(),
      onDelete: vi.fn(),
      onToggle: vi.fn(),
      onPin: vi.fn(),
      onReorder: vi.fn(),
    };
    const view = renderWithProviders(
      <AgentGallery {...props} onCopy={firstCopy} />,
    );
    view.rerender(<AgentGallery {...props} onCopy={nextCopy} />);
    fireEvent.click(screen.getByRole("button", { name: "common.copy" }));
    expect(firstCopy).not.toHaveBeenCalled();
    expect(nextCopy).toHaveBeenCalledWith(agent);
  });
});
