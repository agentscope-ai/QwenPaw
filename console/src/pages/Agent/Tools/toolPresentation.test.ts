import { describe, expect, it } from "vitest";
import { toolGroup } from "./toolPresentation";
import type { ToolInfo } from "../../../api/modules/tools";
const tool = { name: "read_file" } as ToolInfo;
describe("tool categories", () => {
  it("classifies builtins by their explicit catalog", () => {
    expect(toolGroup(tool)).toBe("files");
  });
  it("does not infer plugin categories from a familiar tool name", () => {
    expect(toolGroup({ ...tool, source_plugin_id: "plugin" })).toBe("other");
  });
  it("uses the per-tool category and rejects unknown categories", () => {
    expect(
      toolGroup({ ...tool, source_plugin_id: "plugin", category: "web" }),
    ).toBe("web");
    expect(
      toolGroup({ ...tool, source_plugin_id: "plugin", category: "unknown" }),
    ).toBe("other");
  });
});
