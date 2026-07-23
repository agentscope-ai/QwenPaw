import { describe, expect, it } from "vitest";
import type { MenuItem } from "../../plugins/registry/types";
import { filterMenuForAgentCapabilities } from "./capabilities";

const items: MenuItem[] = [
  {
    id: "core.channels",
    location: "primary.agentScoped",
    label: "Channels",
  },
  {
    id: "core.agent-group",
    location: "primary.agentScoped",
    label: "Workspace",
    isGroup: true,
  },
  {
    id: "core.workspace",
    location: "primary.agentScoped",
    label: "Files",
  },
  {
    id: "core.sessions",
    location: "primary.agentScoped",
    label: "Sessions",
  },
];

describe("filterMenuForAgentCapabilities", () => {
  it("hides native workspace entries without hiding shared controls", () => {
    const visible = filterMenuForAgentCapabilities(items, {
      workspace_ui: false,
    });

    expect(visible.map((item) => item.id)).toEqual([
      "core.channels",
      "core.sessions",
    ]);
  });

  it("keeps the complete menu for native agents", () => {
    expect(filterMenuForAgentCapabilities(items, { workspace_ui: true })).toBe(
      items,
    );
  });
});
