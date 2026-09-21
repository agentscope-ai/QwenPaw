import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  pawappGrantsApi,
  type PawAppGrantCatalog,
} from "@/api/modules/pawappGrants";
import { useAgentStore } from "@/stores/agentStore";
import { renderWithProviders } from "@/test/common_setup";
import PawAppAccessSettings from "./PawAppAccessSettings";

vi.mock("@/api/modules/pawappGrants", () => ({
  pawappGrantsApi: {
    list: vi.fn(),
    update: vi.fn(),
    updateCapability: vi.fn(),
  },
}));

const enabledCatalog: PawAppGrantCatalog = {
  revision: 3,
  capabilities: [
    {
      schema_version: 1,
      capability_id: "read",
      app_id: "qwenpaw-data",
      label: "Read and inspect",
      summary: "View information exposed by this App.",
      action_ids: ["analyze"],
      permissions: ["data.read"],
      effects: ["model_usage"],
      risk: "read",
      enabled: true,
      partial: false,
      stale: false,
    },
  ],
  actions: [
    {
      app_id: "qwenpaw-data",
      action_id: "analyze",
      summary: "Analyze an approved datasource.",
      descriptor_digest: "a".repeat(64),
      input_schema: {
        properties: {
          datasource_id: { type: "string", title: "Datasource" },
        },
      },
      permissions: ["data.read"],
      effects: ["model_usage"],
      settings_entry: "/apps/qwenpaw-data",
      enabled: true,
      stale: false,
      input_values: { datasource_id: ["sales"] },
    },
  ],
};

describe("PawAppAccessSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAgentStore.setState({ selectedAgent: "agent-1" });
    vi.mocked(pawappGrantsApi.list).mockResolvedValue(enabledCatalog);
    vi.mocked(pawappGrantsApi.update).mockResolvedValue({
      revision: 4,
      actions: [
        {
          ...enabledCatalog.actions[0],
          enabled: false,
          input_values: {},
        },
      ],
    });
    vi.mocked(pawappGrantsApi.updateCapability).mockResolvedValue(
      enabledCatalog,
    );
  });

  it("revokes a registered action for the selected agent", async () => {
    renderWithProviders(<PawAppAccessSettings />);

    expect(await screen.findByText("Read and inspect")).toBeVisible();
    expect(screen.getByText("model_usage")).toBeVisible();

    await userEvent.click(
      screen.getByRole("button", { name: /Advanced action limits/ }),
    );
    await waitFor(() => expect(screen.getByText("analyze")).toBeVisible());
    expect(screen.getByText("data.read")).toBeVisible();
    await userEvent.click(
      screen.getByRole("switch", { name: "analyze access" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(pawappGrantsApi.update).toHaveBeenCalledWith(
        "agent-1",
        "qwenpaw-data",
        "analyze",
        {
          expected_revision: 3,
          enabled: false,
          input_values: {},
        },
      );
    });
  });
});
