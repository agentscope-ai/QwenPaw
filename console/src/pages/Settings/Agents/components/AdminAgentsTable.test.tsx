import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AdminAgentsTable } from "./AdminAgentsTable";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("AdminAgentsTable", () => {
  it("renders governance operations as accessible icon buttons", () => {
    const { container } = render(
      <AdminAgentsTable
        agents={[
          {
            id: "managed-agent",
            name: "Managed Agent",
            description: "",
            owner_user_id: "owner-2",
            visibility: "private",
            status: "active",
            governed_by_admin: true,
          },
        ]}
        loading={false}
        onEdit={vi.fn()}
        onMemoryFiles={vi.fn()}
        onRuntimeConfig={vi.fn()}
        onPublication={vi.fn()}
      />,
    );

    for (const name of [
      "agent.governanceEdit",
      "agent.governanceRuntimeConfig",
      "agent.governanceMemoryFiles",
      "agent.publishPublic",
    ]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeVisible();
      expect(button).toHaveTextContent("");
    }
    expect(
      container.querySelectorAll("button .anticon, button svg").length,
    ).toBeGreaterThanOrEqual(4);
  });
  it("opens runtime configuration through a distinct governance action", () => {
    const onRuntimeConfig = vi.fn();
    render(
      <AdminAgentsTable
        agents={[
          {
            id: "managed-agent",
            name: "Managed Agent",
            description: "",
            owner_user_id: "owner-2",
            visibility: "private",
            status: "active",
            governed_by_admin: true,
          },
        ]}
        loading={false}
        onEdit={vi.fn()}
        onMemoryFiles={vi.fn()}
        onRuntimeConfig={onRuntimeConfig}
        onPublication={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "agent.governanceRuntimeConfig",
      }),
    );

    expect(onRuntimeConfig).toHaveBeenCalledWith(
      expect.objectContaining({ id: "managed-agent" }),
    );
  });

  it("opens public memory files through a distinct governance action", () => {
    const onMemoryFiles = vi.fn();
    render(
      <AdminAgentsTable
        agents={[
          {
            id: "managed-agent",
            name: "Managed Agent",
            description: "",
            owner_user_id: "owner-2",
            visibility: "private",
            status: "active",
            governed_by_admin: true,
          },
        ]}
        loading={false}
        onEdit={vi.fn()}
        onMemoryFiles={onMemoryFiles}
        onRuntimeConfig={vi.fn()}
        onPublication={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "agent.governanceMemoryFiles",
      }),
    );
    expect(onMemoryFiles).toHaveBeenCalledWith(
      expect.objectContaining({ id: "managed-agent" }),
    );
  });
});
