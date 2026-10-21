import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (file: string) =>
  readFileSync(join(process.cwd(), "src", file), "utf8");

describe("agent configuration interaction contracts", () => {
  it("uses steppers for bounded advisor intervention values", () => {
    const source = read("pages/Agent/Config/components/AdvisorModeTab.tsx");

    expect(source).toContain("NumberStepper as InputNumber");
    expect(source).not.toContain(
      'Form, InputNumber, Select, Switch } from "@agentscope-ai/design"',
    );
  });

  it("keeps mobile configuration actions on the touch token", () => {
    for (const file of [
      "pages/Agent/Tools/index.module.less",
      "pages/Agent/MCP/index.module.less",
      "pages/Agent/ACP/index.module.less",
      "pages/Agent/Skills/index.module.less",
      "pages/Agent/Checkpoints/index.module.less",
    ]) {
      expect(read(file)).toContain("var(--app-hit-touch)");
    }
  });
});
