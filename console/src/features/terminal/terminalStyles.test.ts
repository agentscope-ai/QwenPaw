import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const styles = readFileSync(
  join(process.cwd(), "src/features/terminal/TerminalDock.module.less"),
  "utf8",
);

describe("terminal viewport background", () => {
  it("covers the unused row space with the terminal theme, not xterm black", () => {
    expect(styles).toMatch(/\.view\s*\{[^}]*--terminal-background:\s*#fafafa/);
    expect(styles).toMatch(
      /\.view\[data-dark="true"\]\s*\{[^}]*--terminal-background:\s*#17191c/,
    );
    expect(styles).toMatch(
      /\.screen :global\(\.xterm \.xterm-viewport\)\s*\{\s*background-color: var\(--terminal-background\)/,
    );
    expect(styles).toContain("max(12px, env(safe-area-inset-bottom, 0px))");
  });
});
