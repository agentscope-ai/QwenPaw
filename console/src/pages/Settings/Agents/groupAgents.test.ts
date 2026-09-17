import { describe, expect, it } from "vitest";
import type { AgentSummary } from "@/api/types/agents";
import { groupAgentsByAccess } from "./groupAgents";

const agent = (
  id: string,
  access_role: AgentSummary["access_role"],
): AgentSummary =>
  ({
    id,
    name: id,
    description: "",
    workspace_dir: "",
    enabled: true,
    backend: "qwenpaw",
    access_role,
  }) as AgentSummary;

describe("groupAgentsByAccess", () => {
  it("preserves order inside my, collaborative and usable groups", () => {
    const grouped = groupAgentsByAccess([
      agent("owner-a", "owner"),
      agent("user-a", "user"),
      agent("collaborator-a", "collaborator"),
      agent("owner-b", "owner"),
    ]);

    expect(grouped.owner.map((item) => item.id)).toEqual([
      "owner-a",
      "owner-b",
    ]);
    expect(grouped.collaborator.map((item) => item.id)).toEqual([
      "collaborator-a",
    ]);
    expect(grouped.user.map((item) => item.id)).toEqual(["user-a"]);
  });
});
