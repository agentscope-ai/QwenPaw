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
});
