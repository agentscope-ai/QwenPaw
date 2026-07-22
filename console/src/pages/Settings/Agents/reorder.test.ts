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

  it("keeps the default agent pinned at the top", () => {
    const list = agents(["default", "a", "b"]);
    expect(reorderAgents(list, "default", "b")).toBe(list);
    expect(reorderAgents(list, "b", "default")).toBe(list);
  });

  it("does not move agents across the pinned boundary", () => {
    const list = agents(["default", "pinned", "regular"]);
    list[1].pinned = true;

    expect(reorderAgents(list, "pinned", "regular")).toBe(list);
    expect(reorderAgents(list, "regular", "pinned")).toBe(list);
  });

  it("reorders peers within the pinned group", () => {
    const list = agents(["default", "pinned-a", "pinned-b", "regular"]);
    list[1].pinned = true;
    list[2].pinned = true;

    const result = reorderAgents(list, "pinned-b", "pinned-a");

    expect(result.map((agent) => agent.id)).toEqual([
      "default",
      "pinned-b",
      "pinned-a",
      "regular",
    ]);
  });
});
