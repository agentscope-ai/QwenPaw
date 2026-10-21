import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (file: string) =>
  readFileSync(join(process.cwd(), "src", file), "utf8");

describe("models interaction density", () => {
  it("uses the shared icon button for refresh and provider actions", () => {
    const page = read("pages/Settings/Models/index.tsx");
    const providerActions = read(
      "pages/Settings/Models/components/cards/ProviderCloseButton.tsx",
    );

    expect(page).toContain("<IconButton");
    expect(page).toContain("icon={RefreshCw}");
    expect(providerActions.match(/<IconButton/g)).toHaveLength(2);
  });

  it("keeps mobile model actions on the 44px touch token", () => {
    const models = read("pages/Settings/Models/index.module.less");
    const modelChoice = read("pages/Chat/ModelSelector/index.module.less");

    expect(models).toContain("Mobile is touch-first");
    expect(models).toContain("min-height: var(--app-hit-touch)");
    expect(models).toContain("height: var(--app-hit-touch)");
    expect(modelChoice).toContain("(max-width: 768px), (any-pointer: coarse)");
  });
});
