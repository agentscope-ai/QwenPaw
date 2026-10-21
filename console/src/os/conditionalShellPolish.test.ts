import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (file: string) =>
  readFileSync(join(process.cwd(), "src", file), "utf8");

describe("conditional shell polish contracts", () => {
  it("uses the current Dropdown popup style API", () => {
    const source = read("os/DesktopOS.tsx");
    expect(source).toContain("classNames={{ root:");
    expect(source).not.toContain("overlayClassName=");
  });

  it("keeps mobile OS window and settings controls touchable", () => {
    const source = read("os/useOsStyles.ts");
    expect(source).toContain("width: 44px");
    expect(source).toContain("min-height: 44px");
    expect(source).toContain("flex-direction: column");
  });

  it("renders settings navigation as native buttons", () => {
    const source = read("os/SettingsApp.tsx");
    expect(source).toContain('<button\n              type="button"');
  });
});
