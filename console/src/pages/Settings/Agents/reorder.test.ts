import { describe, it, expect } from "vitest";
import type { AgentSummary } from "@/api/types/agents";
import { reorderAgents } from "./reorder";

const agents = (ids: string[]): AgentSummary[] =>
  ids.map((id) => ({
    id,
    name: id,
    description: "",
    workspace_dir: "",
    enabled: true,
  }));

describe("reorderAgents", () => {
  it("returns the input array unchanged when activeId equals overId", () => {
    const list = agents(["a", "b", "c"]);
    expect(reorderAgents(list, "b", "b")).toBe(list);
  });

  it("returns the input array unchanged when activeId is not found", () => {
    const list = agents(["a", "b", "c"]);
    expect(reorderAgents(list, "missing", "b")).toBe(list);
  });

  it("returns the input array unchanged when overId is not found", () => {
    const list = agents(["a", "b", "c"]);
    expect(reorderAgents(list, "b", "missing")).toBe(list);
  });

  it("moves an agent forward (lower index -> higher index)", () => {
    const list = agents(["a", "b", "c", "d"]);
    const result = reorderAgents(list, "a", "c");
    expect(result.map((a) => a.id)).toEqual(["b", "c", "a", "d"]);
  });

  it("moves an agent backward (higher index -> lower index)", () => {
    const list = agents(["a", "b", "c", "d"]);
    const result = reorderAgents(list, "d", "b");
    expect(result.map((a) => a.id)).toEqual(["a", "d", "b", "c"]);
  });

  it("does not mutate the original array", () => {
    const list = agents(["a", "b", "c"]);
    const original = [...list];
    reorderAgents(list, "a", "c");
    expect(list.map((a) => a.id)).toEqual(original.map((a) => a.id));
  });
});
