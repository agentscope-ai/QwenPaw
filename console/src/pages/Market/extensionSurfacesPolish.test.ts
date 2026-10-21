import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (file: string) =>
  readFileSync(join(process.cwd(), "src", file), "utf8");

describe("extension surface polish contracts", () => {
  it("uses the current Select popup style API", () => {
    const source = read("pages/Settings/Market/MarketPanel.tsx");
    expect(source).toContain("classNames={{ popup:");
    expect(source).not.toContain("popupClassName=");
  });

  it("keeps extension actions on the mobile touch token", () => {
    for (const file of [
      "pages/AppCenter/index.module.less",
      "pages/Import/index.module.less",
      "pages/Settings/Market/index.module.less",
      "pages/Market/components/MarketplaceHeader/index.module.less",
    ]) {
      expect(read(file)).toContain("var(--app-hit-touch)");
    }
  });
});
