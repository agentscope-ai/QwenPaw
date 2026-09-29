import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(
    process.cwd(),
    "src/pages/Settings/Agents/components/AgentGallery.module.less",
  ),
  "utf8",
);

describe("agent gallery visual states", () => {
  it("uses the restrained tool and MCP hover border", () => {
    expect(stylesSource).toContain("&:hover,");
    expect(stylesSource).toContain("&:focus-within {");
    expect(stylesSource).toContain("border-color: var(--app-accent-border);");
    expect(stylesSource).toContain("background: var(--app-accent-faint);");
  });
});
