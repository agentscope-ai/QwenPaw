import { describe, expect, it } from "vitest";
import { artifactLocatorFromFileCard } from "./fileCardLocator";

describe("artifactLocatorFromFileCard", () => {
  it("maps a registered artifact card to the stable file-center location", () => {
    expect(artifactLocatorFromFileCard({
      agentId: "agent-a",
      conversationId: "de307e1e-a799-4323-8fbb-4699dea2990c",
      file: {
        name: "青岛旅游总结文档.html",
        url: "/api/console/artifacts/d817638b-2710-422f-91b6-949908c4199b/download",
      },
    })).toEqual({
      category: "artifact",
      agentId: "agent-a",
      stableId: "d817638b-2710-422f-91b6-949908c4199b",
      relativePath: "青岛旅游总结文档.html",
      conversationId: "de307e1e-a799-4323-8fbb-4699dea2990c",
    });
  });

  it("does not treat legacy workspace preview URLs as registered artifacts", () => {
    expect(artifactLocatorFromFileCard({
      agentId: "agent-a",
      file: { name: "draft.md", url: "/api/workspace/file?path=draft.md" },
    })).toBeNull();
  });
});
