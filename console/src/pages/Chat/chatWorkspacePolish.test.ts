import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (file: string) =>
  readFileSync(join(process.cwd(), "src", file), "utf8");

describe("chat workspace polish contracts", () => {
  it("uses current Ant Design popup and card style APIs", () => {
    for (const file of [
      "pages/Chat/RichFileReferenceInput.tsx",
      "pages/Chat/components/HarnessModelSelector.tsx",
      "pages/Chat/components/ChatHeaderTitle/index.tsx",
      "pages/Inbox/components/ApprovalCard.tsx",
      "pages/Inbox/components/HarvestCard.tsx",
      "pages/Inbox/components/PushMessageCard.tsx",
    ]) {
      const source = read(file);
      expect(source).not.toContain("overlayClassName=");
      expect(source).not.toContain("bodyStyle=");
    }
  });

  it("keeps Files and Inbox mobile actions on the touch token", () => {
    for (const file of [
      "features/files-workspace/FilesWorkspace.module.less",
      "pages/Coding/TabbedEditor.module.less",
      "pages/Inbox/index.module.less",
    ]) {
      expect(read(file)).toContain("var(--app-hit-touch)");
    }
  });

  it("uses semantic surfaces for inbox cards in both themes", () => {
    for (const file of [
      "pages/Inbox/components/ApprovalCard.module.less",
      "pages/Inbox/components/HarvestCard.module.less",
      "pages/Inbox/components/MagazineStackViewer.module.less",
      "pages/Inbox/components/PushMessageCard.module.less",
    ]) {
      expect(read(file)).not.toContain("rgba(0, 0, 0");
    }
  });
});
