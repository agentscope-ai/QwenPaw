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
    __children: [
      {
        id: "core.workspace",
        location: "primary.agentScoped",
        label: "Files",
      },
      {
        id: "core.skills",
        location: "primary.agentScoped",
        label: "Skills",
      },
      {
        id: "core.tools",
        location: "primary.agentScoped",
        label: "Tools",
      },
      {
        id: "core.mcp",
        location: "primary.agentScoped",
        label: "MCP",
      },
    ],
  } as MenuItem,
  {
    id: "core.sessions",
    location: "primary.agentScoped",
    label: "Sessions",
  },
];

function visibleIds(menuItems: MenuItem[]): string[] {
  return menuItems.flatMap((item) => {
    const children = (item as MenuItem & { __children?: MenuItem[] })
      .__children;
    return [item.id, ...(children ? visibleIds(children) : [])];
  });
}

describe("filterMenuForAgentCapabilities", () => {
  it("hides native workspace entries without hiding shared controls", () => {
    const visible = filterMenuForAgentCapabilities(items, {
      workspace_ui: false,
    });

    expect(visibleIds(visible)).toEqual(["core.channels", "core.sessions"]);
  });

  it("keeps the complete menu for native agents", () => {
    expect(filterMenuForAgentCapabilities(items, { workspace_ui: true })).toBe(
      items,
    );
  });

  it("shows projected Skills and MCP without the native workspace", () => {
    const visible = filterMenuForAgentCapabilities(items, {
      workspace_ui: false,
      native_skills_ui: false,
      native_tools_ui: false,
      native_mcp_ui: false,
      qwenpaw_skills_projection: true,
      qwenpaw_mcp_projection: true,
      provider_mcp_discovery: true,
    });

    expect(visibleIds(visible)).toEqual([
      "core.channels",
      "core.agent-group",
      "core.skills",
      "core.mcp",
      "core.sessions",
    ]);
  });

  it("shows Provider MCP discovery without other workspace panels", () => {
    const visible = filterMenuForAgentCapabilities(items, {
      workspace_ui: false,
      provider_mcp_discovery: true,
    });

    expect(visibleIds(visible)).toEqual([
      "core.channels",
      "core.agent-group",
      "core.mcp",
      "core.sessions",
    ]);
  });
});
