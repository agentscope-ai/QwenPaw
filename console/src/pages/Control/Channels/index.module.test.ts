import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(process.cwd(), "src/pages/Control/Channels/index.module.less"),
  "utf8",
);

describe("channel card visual states", () => {
  it("uses the tool and MCP hover treatment for inactive channels", () => {
    const availableItemRule = stylesSource.match(
      /\.availableItem\s*\{[\s\S]*?\n\}/,
    )?.[0];

    expect(availableItemRule).toContain("&:hover {");
    expect(availableItemRule).toContain(
      "border-color: var(--app-accent-border);",
    );
    expect(availableItemRule).toContain("background: var(--app-accent-faint);");
  });
});
