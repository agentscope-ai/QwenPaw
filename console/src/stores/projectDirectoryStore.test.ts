import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useAgentStore } from "./agentStore";
import {
  useProjectDirectoryStore,
  useProjectDir,
} from "./projectDirectoryStore";

beforeEach(() => {
  useProjectDirectoryStore.setState({ projectDirByAgent: {} });
  useAgentStore.setState({ selectedAgent: "test-agent", agents: [] });
});

describe("projectDirectoryStore", () => {
  it("stores a project directory independently by agent", () => {
    useProjectDirectoryStore.getState().setProjectDir("a1", "/path/to/project");
    expect(useProjectDirectoryStore.getState().projectDirByAgent.a1).toBe(
      "/path/to/project",
    );
  });

  it("stores null for workspace fallback", () => {
    useProjectDirectoryStore.getState().setProjectDir("a1", null);
    expect(useProjectDirectoryStore.getState().projectDirByAgent.a1).toBeNull();
  });

  it("returns undefined before an agent project has been loaded", () => {
    const { result } = renderHook(() => useProjectDir());
    expect(result.current.projectDir).toBeUndefined();
  });
});
