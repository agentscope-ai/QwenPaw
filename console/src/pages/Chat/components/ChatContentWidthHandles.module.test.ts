import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(
    process.cwd(),
    "src/pages/Chat/components/ChatContentWidthHandles.module.less",
  ),
  "utf8",
);

describe("Chat conversation width handle styles", () => {
  it("draws the drag affordance as a warm gradient comet at the pointer height", () => {
    expect(stylesSource).toContain("linear-gradient(\n      to bottom,");
    expect(stylesSource).toContain(
      "var(--qwenpaw-width-handle-pointer-y, 50%)",
    );
    expect(stylesSource).toContain("var(--app-accent)");
    expect(stylesSource).toContain("var(--app-accent-hover)");
    expect(stylesSource).toContain(
      "color-mix(in srgb, var(--app-accent-hover) 62%, white)",
    );
    expect(stylesSource).toContain("color-mix(in srgb, var(--app-accent)");
    expect(stylesSource).toMatch(/border-radius:\s*999px/);
    expect(stylesSource).toContain("drop-shadow(");
    expect(stylesSource).toMatch(/filter:\s*blur\(6px\)/);
    expect(stylesSource).toContain("&::before");
  });

  it("keeps a wide invisible pointer target around the thin line", () => {
    expect(stylesSource).toMatch(/width:\s*28px/);
    expect(stylesSource).toMatch(
      /var\(--qwenpaw-chat-content-display-width, 960px\) \/ 2 \+ 16px/,
    );
    expect(stylesSource).toMatch(
      /&\[data-side="right"\]::after\s*\{\s*left:\s*12px;/,
    );
    expect(stylesSource).toMatch(
      /&\[data-side="left"\]::after\s*\{\s*right:\s*12px;/,
    );
    expect(stylesSource).toMatch(
      /&\[data-side="right"\]::before\s*\{\s*left:\s*9px;/,
    );
  });

  it("reveals the gradient on hover, focus and drag without a hard divider", () => {
    expect(stylesSource).toMatch(
      /&:hover::before,\s*&:focus-visible::before\s*\{\s*opacity:\s*0\.55;/,
    );
    expect(stylesSource).toMatch(
      /&:hover::after,\s*&:focus-visible::after\s*\{\s*opacity:\s*1;/,
    );
    expect(stylesSource).toMatch(
      /&\[data-active="true"\]::before\s*\{\s*opacity:\s*0\.85;/,
    );
    expect(stylesSource).toMatch(
      /&\[data-active="true"\]::after\s*\{[^}]*opacity:\s*1;/,
    );
    expect(stylesSource).toMatch(
      /&\[data-active="true"\]::after\s*\{[^}]*drop-shadow/,
    );
    expect(stylesSource).not.toContain("background: transparent;");
    expect(stylesSource).not.toContain("background: var(--app-accent);");
  });

  it("keeps the motion accessible and hides on phones", () => {
    expect(stylesSource).toContain("@media (prefers-reduced-motion: reduce)");
    expect(stylesSource).toMatch(/transition:\s*none/);
    expect(stylesSource).toContain("@media (max-width: 768px)");
  });
});
